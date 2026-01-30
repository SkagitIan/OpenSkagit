import json
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover
    genai = None
    types = None

try:
    import outscraper
except ImportError:  # pragma: no cover
    outscraper = None


def _strip_code_markers(raw_text: str) -> str:
    """Remove markdown code fences that often wrap Gemini responses."""
    text = raw_text.strip()
    if not text:
        return text
    if text.startswith("```json"):
        text = text[len("```json") :]
    elif text.startswith("```"):
        text = text[len("```") :]
    if text.endswith("```"):
        text = text[: -len("```")]
    return text.strip()


def _normalize_location_for_query(location: Optional[str]) -> str:
    """Reduce a Google address down to the most useful city/state hint."""
    if not location:
        return ""

    ignore = {"usa", "united states", "united states of america", "canada"}
    parts = [part.strip() for part in location.split(",") if part.strip()]
    normalized: List[str] = []
    for part in parts:
        clean = part.strip()
        lower = clean.lower()
        if lower in ignore:
            continue

        if any(char.isdigit() for char in clean):
            tokens = clean.split()
            for token in tokens:
                if token.isalpha() and 1 < len(token) <= 3:
                    normalized.append(token.upper())
                    break
            continue

        normalized.append(clean)

    while len(normalized) > 2:
        normalized.pop(0)

    return ", ".join(normalized)


def _normalize_location_for_query(location: Optional[str]) -> str:
    """Try to reduce a Google formatted address down to the city + state."""
    if not location:
        return ""

    ignore = {"usa", "united states", "united states of america", "canada"}
    parts = [part.strip() for part in location.split(",") if part.strip()]
    normalized: List[str] = []
    for part in parts:
        clean = part.strip()
        lower = clean.lower()
        if lower in ignore:
            continue

        if any(char.isdigit() for char in clean):
            tokens = clean.split()
            for token in tokens:
                if token.isalpha() and 1 < len(token) <= 3:
                    normalized.append(token.upper())
                    break
            continue

        normalized.append(clean)

    while len(normalized) > 2:
        normalized.pop(0)

    return ", ".join(normalized)


class CompetitionAnalysisService:
    def __init__(
        self,
        *,
        google_api_key: str,
        genai_api_key: str,
        outscraper_api_key: Optional[str] = None,
    ):
        if not google_api_key:
            raise ValueError("GOOGLE_PLACES_API_KEY is required for competition analysis.")
        if not genai_api_key:
            raise ValueError("GENAI_API_KEY is required for competition analysis.")
        if not genai or not types:
            raise ValueError("google-genai package is required for grounded intel requests.")
        if outscraper_api_key and not outscraper:
            raise ValueError("OUTSCRAPER_API_KEY is set but the outscraper package is not installed.")

        self.google_api_key = google_api_key
        self.genai_client = genai.Client(api_key=genai_api_key)
        self.outscraper_client = (
            outscraper.ApiClient(api_key=outscraper_api_key)
            if outscraper_api_key
            else None
        )

    def get_grounded_intel(self, business_name: str, location: str, business_type: str) -> Dict[str, Any]:
        """Ask Gemini for grounded intel about a business."""
        prompt = f"""
        Research the restaurant '{business_name}' ({business_type}) in {location}.
        Provide a structured summary including:
        0. All Menu Items
        1. Signature Menu Items: (The 3-5 things they are famous for)
        2. Vibe & Atmosphere
        3. Community Involvement
        4. Target Audience
        5. Recent Operational Changes
        6. Social media presence

        Return only JSON matching the schema specified earlier.
        """

        try:
            response = self.genai_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
            )
            body = _strip_code_markers(response.text)
            return json.loads(body)
        except Exception as exc:
            return {
                "menu_items": [],
                "signature_items": [],
                "vibe": {"summary": "Unable to fetch intel.", "tags": []},
                "community": [],
                "target_audience": [],
                "recent_changes": [],
                "social_media": {
                    "active_ads": "Unavailable",
                    "vibe": {"summary": "Unavailable", "tags": []},
                    "viral_moments_pr_issues": [],
                },
                "notes": f"Failed: {exc}",
            }

    def distill_reviews(self, business_name: str, reviews: List[str]) -> Dict[str, Any]:
        """Ask Gemini to summarize sentiment themes from reviews."""
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

        reviews_text = "\n---\n".join(reviews)
        prompt = f"""
        Analyze the following reviews for '{business_name}' and return JSON with fixed schema.
        ---
        {reviews_text}
        """
        try:
            response = self.genai_client.models.generate_content(
                model="gemini-2.0-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())]
                ),
            )
            body = _strip_code_markers(response.text)
            return json.loads(body)
        except Exception as exc:
            return {
                "top_complaints": [],
                "top_praises": [],
                "staff_mentions": [],
                "price_perception": [],
                "service": [],
                "location": [],
                "general_themes": [],
                "notes": f"Failed distillation: {exc}",
            }

    def _get_place_details(self, place_id: str) -> Dict[str, Any]:
        """Fetch raw Google Places details for later reuse."""
        details_url = f"https://places.googleapis.com/v1/places/{place_id}"
        headers = {
            "X-Goog-Api-Key": self.google_api_key,
            "X-Goog-FieldMask": "displayName,location,priceLevel,primaryType,formattedAddress",
        }
        response = requests.get(details_url, headers=headers, timeout=10)
        response.raise_for_status()
        return response.json()

    def fetch_place_summary(self, place_id: str) -> Dict[str, Any]:
        """Return a structured result that mirrors /places:searchText output."""
        subject_res = self._get_place_details(place_id)
        return {
            "id": place_id,
            "displayName": {"text": subject_res.get("displayName", {}).get("text")},
            "formattedAddress": subject_res.get("formattedAddress"),
            "primaryType": subject_res.get("primaryType"),
            "raw_details": subject_res,
        }

    def run_scout_and_enrich(self, subject_place_id: str) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
        """Fetch subject details from Google and gather grounded intel."""
        subject_res = self._get_place_details(subject_place_id)

        name = subject_res.get("displayName", {}).get("text")
        location = subject_res.get("formattedAddress")
        business_type = subject_res.get("primaryType") or "restaurant"

        intel_payload = self.get_grounded_intel(
            name or "Unknown business",
            location or "Unknown location",
            business_type,
        )

        subject_payload = {
            "name": name,
            "type": business_type,
            "address": location,
            "intel": intel_payload,
            "raw_details": subject_res,
        }

        location_hint = _normalize_location_for_query(location)
        vibe_query = (
            f"{business_type} restaurants in {location_hint}"
            if location_hint
            else f"{business_type} restaurants"
        )
        subject_payload["vibe_query"] = vibe_query
        subject_payload["query_location_hint"] = location_hint
        search_url = "https://places.googleapis.com/v1/places:searchText"
        payload = {"textQuery": vibe_query, "maxResultCount": 10}
        search_headers = {
            "X-Goog-Api-Key": self.google_api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress",
        }
        search_response = requests.post(search_url, headers=search_headers, json=payload, timeout=10)
        search_response.raise_for_status()
        search_data = search_response.json()

        competitors = []
        for comp in search_data.get("places", []):
            if comp.get("id") == subject_place_id:
                continue
            competitors.append(
                {
                    "place_id": comp.get("id"),
                    "name": comp.get("displayName", {}).get("text"),
                    "address": comp.get("formattedAddress"),
                }
            )

        return subject_payload, competitors

    def run_deep_competitor_analysis(
        self, subject_data: Dict[str, Any], vetted_list: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Enrich vetted competitors with reviews and grounded intel."""
        final_payload = {"subject": subject_data, "competitors": []}
        if not vetted_list:
            return final_payload

        for comp in vetted_list:
            reviews = []
            if self.outscraper_client:
                try:
                    os_res = self.outscraper_client.google_maps_reviews(
                        comp["place_id"],
                        reviews_limit=5,
                        ignore_empty=True,
                        language="en",
                        fields=["reviews_data", "google_id"],
                    )
                    if os_res:
                        reviews = [
                            r.get("review_text")
                            for r in os_res[0].get("reviews_data", [])
                            if r.get("review_text")
                        ]
                except Exception:
                    reviews = []

            grounded = self.get_grounded_intel(
                comp["name"],
                comp.get("address") or "Unknown location",
                subject_data.get("type") or "restaurant",
            )
            sentiment = self.distill_reviews(comp["name"], reviews)

            final_payload["competitors"].append(
                {
                    "name": comp["name"],
                    "place_id": comp["place_id"],
                    "grounded_intel": grounded,
                    "sentiment_themes": sentiment,
                }
            )
            time.sleep(1)
        return final_payload
