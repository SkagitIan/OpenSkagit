# -*- coding: utf-8 -*-
"""Standalone competition analysis runner.

Run:
    python3 gastronet/competition_analysis.py
    python3 gastronet/competition_analysis.py --subject-place-id <GOOGLE_PLACE_ID> --output-file /tmp/competition_output.json
    python3 gastronet/competition_analysis.py --report-engine generate_content
"""

import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import re
import time

import httpx
import outscraper
import requests
from dotenv import load_dotenv
from google import genai
from google.genai import types
from openai import OpenAI

# Load .env before reading any key.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")

# --- CONFIGURATION / API KEYS ---
GOOGLE_API_KEY = os.getenv("GOOGLE_PLACES_API_KEY", "")
OUTSCRAPER_API_KEY = os.getenv("OUTSCRAPER_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GENAI_API_KEY", "")
OUTSCRAPER_REVIEWS_LIMIT = int(os.getenv("OUTSCRAPER_REVIEWS_LIMIT", "5"))
OUTSCRAPER_POLL_INTERVAL_SECONDS = float(
    os.getenv("OUTSCRAPER_POLL_INTERVAL_SECONDS", "3")
)
OUTSCRAPER_POLL_TIMEOUT_SECONDS = int(
    os.getenv("OUTSCRAPER_POLL_TIMEOUT_SECONDS", "600")
)
OUTSCRAPER_REQUESTS_BASE_URL = os.getenv(
    "OUTSCRAPER_REQUESTS_BASE_URL", "https://api.outscraper.cloud"
)
DEFAULT_FINAL_REPORT_ENGINE = os.getenv("GEMINI_FINAL_REPORT_ENGINE", "deep_research")
DEEP_RESEARCH_AGENT = os.getenv(
    "GEMINI_DEEP_RESEARCH_AGENT", "deep-research-pro-preview-12-2025"
)
GENERATE_CONTENT_MODEL = os.getenv("GEMINI_GENERATE_CONTENT_MODEL", "gemini-2.0-flash")
VALID_FINAL_REPORT_ENGINES = {"deep_research", "generate_content"}

# Global clients initialized once in initialize_clients().
client = None
outscraper_client = None
client_openai = None

# Global session enables connection pooling (Keep-Alive).
session = requests.Session()


def initialize_clients():
    """Validate required .env keys and initialize API clients."""
    global client
    global outscraper_client
    global client_openai

    missing = []
    if not GOOGLE_API_KEY:
        missing.append("GOOGLE_PLACES_API_KEY")
    if not OUTSCRAPER_API_KEY:
        missing.append("OUTSCRAPER_API_KEY")
    if not OPENAI_API_KEY:
        missing.append("OPENAI_API_KEY")
    if not GEMINI_API_KEY:
        missing.append("GENAI_API_KEY")

    if missing:
        env_path = PROJECT_ROOT / ".env"
        raise RuntimeError(
            f"Missing required environment variables in {env_path}: {', '.join(missing)}"
        )

    client = genai.Client(api_key=GEMINI_API_KEY)
    outscraper_client = outscraper.ApiClient(api_key=OUTSCRAPER_API_KEY)
    client_openai = OpenAI(api_key=OPENAI_API_KEY)


# --- HELPER: JSON CLEANER ---
def clean_json_response(raw_text):
    # Handles ```json, ```, and any whitespace robustly
    return re.sub(r"^```(?:json)?\s*|\s*```$", "", raw_text.strip())


def poll_outscraper_request_archive(results_location, request_id):
    """Poll an async Outscraper request until completion or timeout."""
    poll_url = results_location or f"{OUTSCRAPER_REQUESTS_BASE_URL}/requests/{request_id}"
    headers = {"X-API-KEY": OUTSCRAPER_API_KEY}
    timeout = httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=30.0)
    deadline = time.monotonic() + OUTSCRAPER_POLL_TIMEOUT_SECONDS

    with httpx.Client(timeout=timeout) as http_client:
        while time.monotonic() < deadline:
            response = http_client.get(poll_url, headers=headers, params={"flat": False})

            if response.status_code == 204:
                return []

            response.raise_for_status()
            archive_payload = response.json()
            request_status = archive_payload.get("status", "")

            if request_status == "Success":
                return archive_payload.get("data", [])
            if request_status == "Failure":
                return []

            time.sleep(OUTSCRAPER_POLL_INTERVAL_SECONDS)

    raise TimeoutError(f"Timed out polling Outscraper request {request_id}")


def fetch_outscraper_reviews_data(place_query, reviews_limit):
    """Submit an async review request and fetch completed data via polling."""
    submission = outscraper_client.google_maps_reviews(
        place_query,
        reviews_limit=reviews_limit,
        ignore_empty=True,
        language="en",
        fields=["reviews_data", "google_id"],
        async_request=True,
    )

    if isinstance(submission, list):
        return submission

    submission_status = submission.get("status")
    if submission_status == "Success":
        return submission.get("data", [])
    if submission_status == "Failure":
        return []

    request_id = submission.get("id")
    if not request_id:
        return []

    return poll_outscraper_request_archive(
        results_location=submission.get("results_location"),
        request_id=request_id,
    )


def extract_review_texts(outscraper_reviews_data):
    """Extract review text entries from Outscraper response payload."""
    if not outscraper_reviews_data:
        return []

    first_entry = outscraper_reviews_data[0]
    if isinstance(first_entry, list):
        first_entry = first_entry[0] if first_entry else {}

    if not isinstance(first_entry, dict):
        return []

    return [
        review.get("review_text")
        for review in first_entry.get("reviews_data", [])
        if review.get("review_text")
    ]


# --- HELPER: GROUNDED EXTRACTION ---
def get_grounded_intel(business_name, location, business_type):
    """Uses Gemini with Google Search Grounding to find menu/vibe/community info."""
    prompt_template = """
            Research the restaurant '{business_name}' ({business_type}) in {location}.
            Provide a structured summary including:
            0. All Menu Items
            1. Signature Menu Items: (The 3-5 things they are famous for)
            2. Vibe & Atmosphere: (e.g., upscale, family-friendly, industrial, romantic)
            3. Community Involvement: (Local events, news or sponsorships)
            4. Target Audience: (Who is eating here?)
            5. Find any RECENT Operational Changes?
            6. Research the social media presence:
                1. What is the 'vibe' of their social media? (e.g. professional, meme-heavy, community-focused)
                2. Are there any recent 'viral' moments or public PR issues?

            Return the data ONLY in the following strict JSON schema format, with no additional text or conversational filler. Do not include 'sources' fields.

            Schema:
        {{
          "menu_items": [{{"item": "...", "price": "...", "description": "..."}}],
          "signature_items": [{{"item": "...", "why": "..."}}],
          "vibe": {{"summary": "...", "tags": ["..."]}},
          "community": [{{"claim": "..."}}],
          "target_audience": [{{"segment": "...", "signals": ["..."]}}],
          "recent_changes": [{{"change": "...", "evidence": "..."}}],
          "social_media": {{
            "vibe": {{"summary": "...", "tags": ["..."]}},
            "viral_moments_pr_issues": [{{"event": "...", "summary": "..."}}]
          }},
          "notes": "..."
        }}
    """
    prompt = prompt_template.format(
        business_name=business_name,
        business_type=business_type,
        location=location,
    )

    raw_text = ""  # Initialize raw_text for error handling
    # Enabling Google Search Grounding
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                tools=[types.Tool(google_search=types.GoogleSearch())]
            ),
        )
        # Attempt to parse the response text as JSON
        raw_text = response.text.strip()
        intel_data = json.loads(clean_json_response(raw_text))
        return intel_data
    except Exception as e:
        print(f"Error parsing Gemini response for {business_name}: {e}")
        return {
            "menu_items": [],
            "signature_items": [],
            "vibe": {"summary": "Error or no information found.", "tags": []},
            "community": [],
            "target_audience": [],
            "recent_changes": [],
            "social_media": {
                "vibe": {"summary": "Not found", "tags": []},
                "viral_moments_pr_issues": [],
            },
            "notes": f"Failed to get grounded intel or parse JSON: {e}. Raw response: {raw_text}",
        }


# --- HELPER: REVIEW DISTILLER ---
def distill_reviews(business_name, reviews):
    """Analyzes a list of reviews for a business using Gemini with Google Search Grounding.
    Extracts sentiment themes like complaints, praises, staff mentions, price perception, etc.
    """
    if not reviews:
        return {
            "top_complaints": [],
            "top_praises": [],
            "staff_mentions": [],
            "price_perception": [],
            "service": [],
            "location": [],
            "general_themes": [],
            "notes": "No reviews provided.",
        }

    # 1. Concatenate reviews
    reviews_text = "\n---\n".join(reviews)

    # 2. Construct detailed prompt
    prompt_template = """
    You are an expert in sentiment analysis and business intelligence. Analyze the following reviews for '{business_name}'.

    Extract the following sentiment themes, considering both positive and negative aspects:

    0. Top Complaints: List common criticisms or negative experiences mentioned.
    1. Top Praises: List common compliments or positive experiences mentioned.
    2. Staff Mentions: Identify any specific staff names mentioned and the sentiment (positive, negative, neutral) associated with them.
    3. Price Perception: Summarize how customers perceive the pricing (e.g., good value, expensive, affordable, overpriced).
    4. Service: Describe the overall perception of the service quality (e.g., attentive, slow, friendly, disorganized).
    5. Location: Identify any comments related to the business's location (e.g., convenient, hard to find, good ambiance, noisy).
    6. General Themes: List any other significant recurring themes or topics in the reviews not covered above.

    Provide the output ONLY in a strict JSON object with the following schema. If no information is found for a category, return an empty list for that category. Do not include 'sources' fields or any conversational filler.

    Schema:
{{
      "top_complaints": ["..."],
      "top_praises": ["..."],
      "staff_mentions": [{{"name": "...", "sentiment": "..."}}],
      "price_perception": ["..."],
      "service": ["..."],
      "location": ["..."],
      "general_themes": ["..."]
    }}

    Here are the reviews:
    ---
    {reviews_text}
    ---
    """
    prompt = prompt_template.format(
        business_name=business_name,
        reviews_text=reviews_text,
    )
    raw_text = ""  # Initialize raw_text for error handling
    # 3. Call Gemini API with Google Search Grounding
    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
            config=types.GenerateContentConfig(),
        )

        # 4. Implement robust JSON parsing
        raw_text = response.text.strip()
        distilled_data = json.loads(clean_json_response(raw_text))
        return distilled_data

    except Exception as e:
        print(f"Error distilling reviews for {business_name}: {e}")
        # 5. Error handling: return empty lists and notes
        return {
            "top_complaints": [],
            "top_praises": [],
            "staff_mentions": [],
            "price_perception": [],
            "service": [],
            "location": [],
            "general_themes": [],
            "notes": f"Failed to distill reviews or parse JSON: {e}. Raw response: {raw_text}",
        }


# --- PHASE 1: SUBJECT ENRICHMENT & DISCOVERY ---
def run_scout_and_enrich(subject_place_id):
    print(f"🔍 Fingerprinting Subject: {subject_place_id}...")

    # 1. Basic Maps Data
    details_url = f"https://places.googleapis.com/v1/places/{subject_place_id}"
    headers = {
        "X-Goog-Api-Key": GOOGLE_API_KEY,
        "X-Goog-FieldMask": "displayName,location,priceLevel,primaryType,formattedAddress",
    }
    subject_res = session.get(details_url, headers=headers).json()  # Use global session

    s_name = subject_res.get("displayName", {}).get("text")
    s_type = subject_res.get("primaryType")
    s_location = subject_res.get("formattedAddress")

    # Helper for competitor search.
    def _perform_competitor_search(business_type, location, subject_id):
        vibe_query = f"{business_type} restaurants in {location}"
        text_url = "https://places.googleapis.com/v1/places:searchText"
        payload = {
            "textQuery": vibe_query,
            "maxResultCount": 5,  # Limiting for efficiency
        }
        search_headers = {
            "X-Goog-Api-Key": GOOGLE_API_KEY,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress",
        }

        search_res = session.post(
            text_url, headers=search_headers, json=payload
        ).json()  # Use global session
        competitors = search_res.get("places", [])
        print(f"🔍 Found {len(competitors)} potential competitors.")
        vetted_competitors = []
        for comp in competitors:
            if comp["id"] != subject_id:
                vetted_competitors.append(
                    {
                        "place_id": comp["id"],
                        "name": comp.get("displayName", {}).get("text"),
                        "address": comp.get("formattedAddress"),
                    }
                )
        return vetted_competitors

    # Helper to get raw reviews for the subject.
    def _get_subject_reviews_raw(place_id, name):
        reviews = []
        try:
            os_res = fetch_outscraper_reviews_data(
                place_query=place_id,
                reviews_limit=OUTSCRAPER_REVIEWS_LIMIT,
            )
            reviews = extract_review_texts(os_res)
        except Exception as e:
            print(f"   ❌ Outscraper Error for subject {name} (reviews): {e}")
        return reviews

    # Run enrichment tasks concurrently for the subject.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
        print(
            f"🌐 Grounding Subject, fetching reviews, and searching for competitors for: {s_name}..."
        )

        intel_future = executor.submit(get_grounded_intel, s_name, s_location, s_type)
        competitors_future = executor.submit(
            _perform_competitor_search, s_type, s_location, subject_place_id
        )
        subject_reviews_future = executor.submit(
            _get_subject_reviews_raw, subject_place_id, s_name
        )

        subject_intel = intel_future.result()
        vetted_competitors = competitors_future.result()
        subject_raw_reviews = subject_reviews_future.result()

    # Distill subject reviews
    print(f"   🧠 Distilling subject reviews for {s_name}...")
    subject_sentiment_themes = distill_reviews(s_name, subject_raw_reviews)

    subject_payload = {
        "name": s_name,
        "type": s_type,
        "address": s_location,
        "intel": subject_intel,
        "sentiment_themes": subject_sentiment_themes,
        "raw_details": subject_res,
    }

    return subject_payload, vetted_competitors


def _get_competitor_reviews_raw(competitor):
    """Fetches raw review texts for a single competitor."""
    pid = competitor["place_id"]
    name = competitor["name"]
    reviews = []
    try:
        os_res = fetch_outscraper_reviews_data(
            place_query=pid,
            reviews_limit=OUTSCRAPER_REVIEWS_LIMIT,
        )
        reviews = extract_review_texts(os_res)
    except Exception as e:
        print(f"   ❌ Outscraper Error for {name} (reviews): {e}")
    return reviews


def _get_competitor_intel(competitor, subject_data):
    """Fetches grounded intelligence for a single competitor."""
    name = competitor["name"]
    address = competitor["address"]
    comp_intel = {}
    try:
        comp_intel = get_grounded_intel(name, address, subject_data["type"])
    except Exception as e:
        print(f"   ❌ Gemini Error for {name} (intel): {e}")
        comp_intel = {
            "menu_items": [],
            "signature_items": [],
            "vibe": {"summary": "Error or no information found.", "tags": []},
            "community": [],
            "target_audience": [],
            "recent_changes": [],
            "social_media": {
                "active_ads": "Not found",
                "vibe": {"summary": "Not found", "tags": []},
                "viral_moments_pr_issues": [],
            },
            "notes": f"Failed to get grounded intel: {e}",
        }
    return comp_intel


def _distill_single_competitor_reviews(competitor_name, raw_reviews):
    """Distills reviews for a single competitor."""
    sentiment_themes = {}
    try:
        print(f"   🧠 Distilling reviews for {competitor_name}...")
        sentiment_themes = distill_reviews(competitor_name, raw_reviews)
    except Exception as e:
        print(f"   ❌ Error distilling reviews for {competitor_name}: {e}")
        sentiment_themes = {
            "top_complaints": [],
            "top_praises": [],
            "staff_mentions": [],
            "price_perception": [],
            "service": [],
            "location": [],
            "general_themes": [],
            "notes": f"Failed to distill reviews: {e}",
        }
    return sentiment_themes


def _process_single_competitor(competitor, subject_data):
    """Fetches and processes all data for a single competitor."""
    pid = competitor["place_id"]
    name = competitor["name"]

    # Fetch raw reviews
    raw_reviews = _get_competitor_reviews_raw(competitor)

    # Fetch grounded intelligence
    comp_intel = _get_competitor_intel(competitor, subject_data)

    # Distill reviews
    sentiment_themes = _distill_single_competitor_reviews(name, raw_reviews)

    return {
        "name": name,
        "place_id": pid,
        "grounded_intel": comp_intel,
        "sentiment_themes": sentiment_themes,
    }


def run_deep_competitor_analysis(subject_data, vetted_list):
    final_payload = {"subject": subject_data, "competitors": []}

    # Process each competitor in parallel to speed up I/O-heavy calls.
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        future_to_competitor = {
            executor.submit(_process_single_competitor, comp, subject_data): comp
            for comp in vetted_list
        }

        for future in concurrent.futures.as_completed(future_to_competitor):
            competitor_data = future.result()
            final_payload["competitors"].append(competitor_data)

    return final_payload


def _extract_text_from_content(content_item):
    """Return text from text/thought content blocks."""
    if content_item is None:
        return ""

    content_type = getattr(content_item, "type", None)
    if content_type == "text":
        return getattr(content_item, "text", "") or ""

    if content_type == "thought":
        thought_summaries = getattr(content_item, "summary", []) or []
        summary_lines = []
        for summary in thought_summaries:
            if getattr(summary, "type", None) == "text":
                text_value = getattr(summary, "text", "")
                if text_value:
                    summary_lines.append(text_value)
        return "\n".join(summary_lines)

    return ""


def _stream_event_message(event, event_callback=None):
    """Translate stream events into lightweight console messages."""
    def _emit(message, stream_event_type=None):
        print(message)
        if callable(event_callback):
            event_callback(
                "stream",
                message,
                {"stream_event_type": stream_event_type} if stream_event_type else None,
            )

    event_type = getattr(event, "event_type", None)

    if event_type == "interaction.status_update":
        status = getattr(event, "status", None)
        if status:
            _emit(f"[interaction_status] {status}", stream_event_type=event_type)
        return ""

    if event_type == "error":
        error_obj = getattr(event, "error", None)
        error_message = getattr(error_obj, "message", "Unknown stream error.")
        _emit(f"[interaction_error] {error_message}", stream_event_type=event_type)
        return ""

    if event_type != "content.delta":
        return ""

    delta = getattr(event, "delta", None)
    if delta is None:
        return ""

    delta_type = getattr(delta, "type", None)

    if delta_type == "thought_summary":
        summary_text = _extract_text_from_content(getattr(delta, "content", None)).strip()
        if summary_text:
            _emit(
                f"[thinking_summary] {summary_text}",
                stream_event_type=f"{event_type}:{delta_type}",
            )
        return ""

    if delta_type == "google_search_call":
        arguments = getattr(delta, "arguments", None)
        queries = getattr(arguments, "queries", None) if arguments else None
        if queries:
            _emit(
                f"[research_event] google_search_call: {', '.join(queries)}",
                stream_event_type=f"{event_type}:{delta_type}",
            )
        else:
            _emit(
                "[research_event] google_search_call",
                stream_event_type=f"{event_type}:{delta_type}",
            )
        return ""

    if delta_type == "url_context_call":
        arguments = getattr(delta, "arguments", None)
        urls = getattr(arguments, "urls", None) if arguments else None
        if urls:
            _emit(
                f"[research_event] url_context_call: {urls[0]}",
                stream_event_type=f"{event_type}:{delta_type}",
            )
        else:
            _emit(
                "[research_event] url_context_call",
                stream_event_type=f"{event_type}:{delta_type}",
            )
        return ""

    if delta_type in {
        "google_search_result",
        "url_context_result",
        "file_search_result",
        "code_execution_result",
        "function_result",
        "mcp_server_tool_result",
    }:
        _emit(
            f"[research_event] {delta_type}",
            stream_event_type=f"{event_type}:{delta_type}",
        )
        return ""

    if delta_type in {
        "file_search_call",
        "code_execution_call",
        "function_call",
        "mcp_server_tool_call",
    }:
        _emit(
            f"[research_event] {delta_type}",
            stream_event_type=f"{event_type}:{delta_type}",
        )
        return ""

    if delta_type == "text":
        return getattr(delta, "text", "") or ""

    return ""


def _extract_final_report_text(interaction_obj, streamed_chunks):
    """Build final report text from interaction outputs, with stream fallback."""
    if interaction_obj is not None and getattr(interaction_obj, "outputs", None):
        output_text_chunks = []
        for output in interaction_obj.outputs or []:
            text_value = _extract_text_from_content(output).strip()
            if text_value:
                output_text_chunks.append(text_value)
        if output_text_chunks:
            return "\n\n".join(output_text_chunks).strip()

    return "".join(streamed_chunks).strip()


def _normalize_final_report_engine(report_engine):
    """Normalize supported report-engine aliases to canonical values."""
    raw_engine = report_engine or DEFAULT_FINAL_REPORT_ENGINE
    normalized = (
        str(raw_engine).strip().lower().replace("-", "_").replace(".", "_")
    )
    alias_map = {
        "deep_research": "deep_research",
        "deepresearch": "deep_research",
        "interactions": "deep_research",
        "interactions_create": "deep_research",
        "generate_content": "generate_content",
        "generatecontent": "generate_content",
        "models_generate_content": "generate_content",
    }
    canonical_engine = alias_map.get(normalized, normalized)
    if canonical_engine not in VALID_FINAL_REPORT_ENGINES:
        raise ValueError(
            "Unsupported report engine "
            f"'{report_engine}'. Use one of: deep_research, generate_content."
        )
    return canonical_engine


def _build_final_analysis_prompt(master_payload):
    """Build one canonical prompt so all engines analyze identical inputs."""
    analysis_prompt = """
You are a sharp, empathetic business analyst specializing in independent food & beverage businesses. You have been given a structured JSON intelligence payload containing a **subject** restaurant/brewpub and a list of **competitors**, each with menu data, sentiment themes, vibe profiles, community positioning, audience signals, and operational notes.

Your job is to produce a comprehensive yet readable competitive analysis report for the **subject business owner**. Write as a trusted advisor — honest, specific, and actionable. Avoid generic business advice. Every insight must be grounded in the data provided.

---

## REPORT STRUCTURE

### 1. Executive Summary
2–3 paragraphs. Who is this business right now? What is their strongest asset? What is their most urgent challenge? Set the stage without repeating the full report below.

---

### 2. Competitive Landscape Overview
Briefly characterize each competitor in 2–3 sentences: their positioning, vibe, and primary strength. Then write a 1-paragraph synthesis of the overall market the subject is competing in. What kind of battlefield is this?

---

### 3. Identity & Differentiation Analysis
What makes the subject genuinely distinct from competitors? Examine:
- **Heritage & story** — does it matter, and are they using it?
- **Atmosphere & vibe** — where do they sit in the spectrum vs. competitors?
- **Audience overlap** — which segments are contested vs. owned?
- **Brand coherence** — does the menu, vibe, and messaging tell one consistent story?

Be direct about where differentiation is strong and where differentiation is fuzzy or missing.

---

### 4. Menu Intelligence
Analyze the subject's menu relative to competitors across these dimensions:

- **Coverage gaps** — what categories or item types do competitors offer that the subject doesn't (or vice versa)?
- **Pricing position** — where does the subject land relative to competitors? Are prices justified by the offer?
- **Signature strength** — does the subject have clear "destination items" that competitors can't match?
- **Operational signals** — do menu descriptions suggest strong kitchen identity, or do items feel generic/underdeveloped?
- **Opportunities** — specific, data-grounded item or category suggestions worth exploring

If menu data is sparse for any competitor, note it and reason from what is available.

---

### 5. Sentiment & Reputation Analysis
Using review themes and sentiment data:

- What do guests **love** about the subject? Is this being amplified and protected?
- What do guests **complaint about**? Is this a fixable operational issue or a deeper identity problem?
- How does the subject's sentiment profile compare to competitors — who has the reputation high ground, and why?
- Are there **staff or service patterns** worth noting (positive or negative)?
- Flag any **PR or reputational issues** for the subject or competitors with clear-eyed analysis of the risk and opportunity. Do not moralize — assess impact and suggest a path forward.

---

### 6. Market Positioning Map
Write a narrative "positioning map" (no actual chart — prose only) that places each business on two axes:
- **Beer-forward ↔ Food-forward**
- **Community local ↔ Destination/tourist draw**

Where is the subject? Where is the white space? Is there a position no one currently owns that the subject could credibly claim?

---

### 7. Strategic Opportunities (Ranked)
List 3–5 specific, prioritized opportunities for the subject. Each should include:
- **Opportunity** — what it is
- **Evidence** — what in the data supports this
- **Action** — one concrete first step
- **Risk** — what could go wrong

Rank from highest to lowest impact. Be bold. Vague recommendations are worthless.

---

### 8. Threats to Watch
List 2–3 genuine threats — from competitors, market dynamics, or internal patterns — that the owner should monitor. Be specific about the signal in the data that raises the flag.

---

### 9. The One Thing
If the owner could only act on one insight from this report, what is it and why? Make this the most honest, direct paragraph in the entire report.

---

## STYLE GUIDELINES
- Write for a smart, non-technical business owner — no jargon, no hedging, no filler
- Use **bold** for key terms and section emphasis only — not decoration
- Where data is missing or ambiguous, say so and reason transparently from what exists
- Avoid generic phrases like "consider leveraging synergies" — be specific to this business and this market
- Tone: trusted advisor, not consultant-speak. Direct, warm, occasionally blunt.
- Length: comprehensive but not padded. Cut anything that doesn't serve the owner.

---

## INPUT FORMAT
You will receive a JSON object with this structure:
- `subject` — the business being analyzed, with `intel` (menu, vibe, community, audience, changes, social) and `raw_details`
- `competitors` — array of competitor objects with `grounded_intel` and `sentiment_themes`

Treat all data as a starting point for analysis, not gospel. Use your judgment when signals conflict or data is thin.
"""

    return f"""{analysis_prompt}

Here is the intelligence payload for your analysis:
{json.dumps(master_payload, indent=2)}
"""


def _run_deep_research_interaction(final_analysis_prompt, event_callback=None):
    """Run final report via Gemini interactions deep-research agent."""
    print("🧠 Sending data to Gemini for final analysis (deep_research)...")

    try:
        print("\n--- STARTING DEEP RESEARCH ANALYSIS (This may take 2-5 minutes) ---\n")
        if callable(event_callback):
            event_callback("status", "Deep research started.", {"phase": "deep_research"})

        # Stream interaction events so tool calls/thinking summaries are visible in real-time.
        stream = client.interactions.create(
            agent=DEEP_RESEARCH_AGENT,
            input=final_analysis_prompt,
            stream=True,
            agent_config={
                "type": "deep-research",
                "thinking_summaries": "auto",
            },
        )

        final_interaction = None
        streamed_text_chunks = []

        for event in stream:
            if getattr(event, "event_type", None) == "interaction.complete":
                final_interaction = getattr(event, "interaction", None)

            text_delta = _stream_event_message(event, event_callback=event_callback)
            if text_delta:
                streamed_text_chunks.append(text_delta)

        final_report = _extract_final_report_text(final_interaction, streamed_text_chunks)

        # If stream returned only deltas without final outputs, fetch final interaction once.
        if not final_report and final_interaction and getattr(final_interaction, "id", None):
            completed_interaction = client.interactions.get(final_interaction.id)
            final_report = _extract_final_report_text(
                completed_interaction, streamed_text_chunks
            )

        if not final_report:
            raise Exception("Deep Research completed but no report text was returned.")

        print("\n--- FINAL DEEP RESEARCH COMPETITIVE ANALYSIS ---\n")
        print(final_report)
        if callable(event_callback):
            event_callback("status", "Deep research completed.", {"phase": "deep_research"})
        return final_report

    except Exception as e:
        print(f"\nError during Deep Research: {e}")
        if callable(event_callback):
            event_callback("error", f"Deep research failed: {e}", {"phase": "deep_research"})
        return f"Failed to generate report due to an error: {e}"


def _run_generate_content_report(final_analysis_prompt, event_callback=None):
    """Run final report via Gemini models.generate_content."""
    print("🧠 Sending data to Gemini for final analysis (generate_content)...")

    try:
        print("\n--- STARTING GENERATE CONTENT ANALYSIS ---\n")
        if callable(event_callback):
            event_callback(
                "status",
                "Generate content analysis started.",
                {"phase": "generate_content"},
            )

        response = client.models.generate_content(
            model=GENERATE_CONTENT_MODEL,
            contents=final_analysis_prompt,
            config=types.GenerateContentConfig(),
        )

        final_report = (getattr(response, "text", "") or "").strip()
        if not final_report:
            raise Exception("Generate content completed but no report text was returned.")

        print("\n--- FINAL GENERATE CONTENT COMPETITIVE ANALYSIS ---\n")
        print(final_report)
        if callable(event_callback):
            event_callback(
                "status",
                "Generate content analysis completed.",
                {"phase": "generate_content"},
            )
        return final_report
    except Exception as e:
        print(f"\nError during generate_content analysis: {e}")
        if callable(event_callback):
            event_callback(
                "error",
                f"Generate content analysis failed: {e}",
                {"phase": "generate_content"},
            )
        return f"Failed to generate report due to an error: {e}"


def run_deep_research_report(master_payload, event_callback=None, report_engine=None):
    """Generate final report via selected Gemini engine."""
    final_analysis_prompt = _build_final_analysis_prompt(master_payload)
    engine = _normalize_final_report_engine(report_engine)
    if engine == "generate_content":
        return _run_generate_content_report(
            final_analysis_prompt,
            event_callback=event_callback,
        )
    return _run_deep_research_interaction(
        final_analysis_prompt,
        event_callback=event_callback,
    )


def write_output_file(output_file, subject_place_id, master_payload, final_report):
    """Write one combined output artifact so runs stay self-contained."""
    output_path = Path(output_file).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined_output = {
        "subject_place_id": subject_place_id,
        "master_payload": master_payload,
        "final_report": final_report,
    }
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(combined_output, f, indent=2)
    print(f"\n✅ Wrote analysis output to: {output_path}")


def parse_args():
    parser = argparse.ArgumentParser(
        description="Run grounded restaurant competition analysis end-to-end."
    )
    parser.add_argument(
        "--subject-place-id",
        default="ChIJW01pgKVuhVQRyP57MABxVog",
        help="Google Place ID for the subject business.",
    )
    parser.add_argument(
        "--output-file",
        default=str(Path(__file__).with_name("competition_analysis_output.json")),
        help="Single JSON output file path for payload + final report.",
    )
    parser.add_argument(
        "--report-engine",
        default=DEFAULT_FINAL_REPORT_ENGINE,
        help=(
            "Final report engine: deep_research or generate_content "
            "(aliases like deep-research and models.generate_content are accepted)."
        ),
    )
    return parser.parse_args()


def main():
    args = parse_args()
    initialize_clients()

    subject_info, comp_list = run_scout_and_enrich(args.subject_place_id)
    master_payload = run_deep_competitor_analysis(subject_info, comp_list)

    print("\n🚀 FINAL PAYLOAD READY FOR ANALYSIS\n")
    print(json.dumps(master_payload, indent=2))

    final_report = run_deep_research_report(
        master_payload,
        report_engine=args.report_engine,
    )
    write_output_file(
        output_file=args.output_file,
        subject_place_id=args.subject_place_id,
        master_payload=master_payload,
        final_report=final_report,
    )


if __name__ == "__main__":
    main()
