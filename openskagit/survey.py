import json
import logging
import uuid
from typing import Any, Dict, List, Tuple

from pydantic import BaseModel, Field, ValidationError

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from . import llm
from .models import SurveyConversation, SurveyInteraction
from .views import _basic_page_context, _get_cached_home_portal_metrics

OPENING_QUESTION = (
    "Hello!  Thanks for taking the time to join the conversaton.  What should I call you?"
)

SURVEY_PUBLIC_HINT = ""

SURVEY_SYSTEM_PROMPT = """
# Specialized Civic Research Assistant: Protocol 2.0

**Objective:** Conduct a structured conversational survey to gather actionable insights for municipal planning.
**Core Directive:** You must fill all 10 Information Slots with high-quality, substantive data. Do not move to the next slot until the current data requirement is met.

### 0.  Pre-survey
** when user lands on the survey they are are asked "What should I call you" so the first message you will get is their name.  acknolweldge and move on.

### 1. The Data Validation Loop (New)

Before moving to the next Information Slot, you must pass a **Data Quality Check**:

* **Check:** Is the response a "Null" or "Thin" response (e.g., "I don't know," "It's okay," "Maybe")?
* **Action:** If yes, you **must** use one (1) DICE Probe. You may not advance to the next slot until the user provides a descriptive answer or explicitly refuses to elaborate.
* **Logging:** Internally track: `[Current Slot: X | Status: Incomplete/Complete]`.

### 2. Context Lock & Drift Control (New)

To prevent context drifting, use the **Acknowledge-Pivot-Return (APR)** method:

* **Acknowledge:** "I have noted your input regarding [Off-Topic Subject]."
* **Pivot:** "To ensure we capture all specific data points for the municipal report..."
* **Return:** "...I’d like to return to [Current Slot Question]."

### 3. Behavioral Principles

* **One Question at a Time:** Never double-ask.
* **Neutrality Protocol:** Use objective language. If a participant is emotional, ask: "What specific experiences informed that perspective?"
* **Context Retention:** Reference previous answers to show the survey is a cohesive dialogue (e.g., "Earlier you mentioned [Culture Word], keeping that in mind, how would you rate...").

---

### 4. Information Slots (Core Questions)

| Slot | Topic | Primary Question |
| --- | --- | --- |
| **1** | **Culture** | "To get us started, if you had to use just one word to describe our community's culture today, what would it be?" |
| **2** | **Livability** | "Overall, how would you rate our city as a place to live?" |
| **3** | **Transparency** | "How satisfied are you with the transparency of our local government's decision-making process?" |
| **4** | **Safety** | "How safe do you feel walking alone in your neighborhood after dark?" |
| **5** | **Fiscal Access** | "Do you feel you can easily access information about how public funds and budgets are being spent?" |
| **6** | **Civic NPS** | "How likely are you to recommend participating in local government initiatives to your friends or family?" |
| **7** | **Barriers** | "What barriers, if any, prevent you from being more active in local civic initiatives?" |
| **8** | **Trust Drivers** | "What would make you trust your local government's decisions more?" |
| **9** | **Primary Concern** | "If you were explaining your primary concern about our community to a friend, how would you describe it?" |
| **10** | **Final Closing** | "Is there anything else you want your community leaders to know about your civic engagement experience?" |

---

### 5. Adaptive Probing Strategy (DICE)

If a response fails the **Data Quality Check**, apply one:

* **Descriptive:** "Could you tell me more about what that looks like in your daily life?"
* **Idiographic:** "Was there a specific recent event that shaped that view?"
* **Clarifying:** "When you say '[user word]', what specifically does that mean to you?"
* **Explanatory:** "What would have to change for you to feel more satisfied with that?"

### 6. Constraints

* **Max Probes:** 2 per slot. If the user remains uncommunicative after 2 probes, move to the next slot to avoid fatigue.
* **Tone:** Formal, objective, and empathetic but professional.

"""
SURVEY_QUESTIONS = [
    {"id": "q1", "topic": "Recent Needs", "text": "What's a specific question about local government you've had recently that was hard to find an answer to?"},
    {"id": "q2", "topic": "Current Experience", "text": "When you need information from the county, city, or other local agencies, what usually happens? Do you find it quickly, give up, call someone, or visit an office?"},
    {"id": "q3", "topic": "Dream Question", "text": "If you could type a question into a search box and get an instant answer using data from all local agencies, what would you ask right now?"},
    {"id": "q4", "topic": "Priority Topics", "text": "Which types of information do you wish were easier to find? For example: permit status, meeting agendas, property information, project timelines, budget details, or something else?"},
    {"id": "q5", "topic": "Problem Validation", "text": "Have you ever needed information that you knew existed somewhere in local government but couldn't figure out where to look?"},
    {"id": "q6", "topic": "Information Sources", "text": "When you have a question about local government, where do you typically look first? What works and what doesn't?"},
    {"id": "q7", "topic": "Barriers", "text": "What's the biggest frustration you've experienced trying to get information from local government?"},
    {"id": "q8", "topic": "Use Cases", "text": "Imagine you could ask any question and get an answer that combines information from multiple agencies (county, city, schools, utilities). What would be most valuable to you?"},
    {"id": "q9", "topic": "Format Preferences", "text": "When you get an answer to a government question, what format is most helpful? A simple text answer, links to official documents, step-by-step instructions, or something else?"},
    {"id": "q10", "topic": "Final Thoughts", "text": "Is there anything else about finding local government information that you'd like to share?"},
]
SURVEY_MAX_QUESTIONS = len(SURVEY_QUESTIONS)

INSIGHT_LABELS = [
    "clarity_gap",
    "fairness_concern",
    "process_friction",
    "trust_gap",
    "access_gap",
    "frustrated",
    "hopeful",
    "curious",
    "resigned",
    "energized",
    "homeowner",
    "renter",
    "business_operator",
    "civic_participant",
    "explorer_resident",
    "short_term_problem",
    "long_term_planning",
    "systemic_issue",
]

LATENT_PROFILE_TEMPLATE: Dict[str, Any] = {
    "primary_pain": None,
    "life_context": None,
    "emotional_tone": None,
    "time_horizon": None,
    "power_distance": None,
}

LATENT_PROFILE_ALLOWED_VALUES: Dict[str, List[str]] = {
    "primary_pain": ["clarity", "fairness", "speed", "trust", "access"],
    "life_context": ["homeowner", "renter", "business_operator", "civic_participant", "explorer_resident"],
    "emotional_tone": ["frustrated", "hopeful", "curious", "skeptical", "resigned", "energized"],
    "time_horizon": ["immediate", "planning", "long_term"],
    "power_distance": ["feels_heard", "feels_ignored", "unsure"],
}

REFLECTION_THEME_LABELS = {
    "clarity": "clarity",
    "fairness": "fairness",
    "speed": "process",
    "trust": "trust",
    "access": "access",
    "clarity_gap": "clarity",
    "fairness_concern": "fairness",
    "process_friction": "process",
    "trust_gap": "trust",
    "access_gap": "access",
}

PAIN_LABEL_TO_PROFILE = {
    "clarity_gap": "clarity",
    "fairness_concern": "fairness",
    "process_friction": "speed",
    "trust_gap": "trust",
    "access_gap": "access",
}

EMOTION_LABELS = {"frustrated", "hopeful", "curious", "resigned", "energized"}

LIFE_CONTEXT_LABELS = {
    "homeowner": "homeowner",
    "renter": "renter",
    "business_operator": "business_operator",
    "civic_participant": "civic_participant",
    "explorer_resident": "explorer_resident",
}

ORIENTATION_TO_TIME = {
    "short_term_problem": "immediate",
    "long_term_planning": "planning",
    "systemic_issue": "long_term",
}

SURVEY_CLOSING_MESSAGE = (
    "That’s it—thank you for the thoughtful answers. "
    "We’ll publish what we learn so the community knows where to turn next."
)

SURVEY_FINISH_ACTIONS: List[Dict[str, str]] = [
    {"label": "View current insights", "href": "/#tools"},
    {"label": "Return to OpenSkagit", "href": "/"},
]

AGENT_MOOD_CHOICES = ["Frustrated", "Satisfied", "Confused", "Neutral", "Urgent", "Hesitant"]

class AgentResponse(BaseModel):
    mood: str = Field(description="Detected mood: Frustrated, Satisfied, Confused, Neutral, Urgent, or Hesitant.")
    topic_match: str = Field(description="The primary topic discussed in the user's answer.")
    is_clarification: bool = Field(description="Set to True ONLY if asking a follow-up. False if moving to a new question.")
    acknowledgement: str = Field(description="A short, warm, empathetic acknowledgement of the user's previous answer.")
    message: str = Field(description="The actual next text to show the user (either the follow-up or the next survey question).")

SURVEY_LLM_DEFAULT_MODEL = getattr(settings, "SURVEY_OPENAI_MODEL", "gpt-4o-mini")
SURVEY_EXTRACTION_MODEL = getattr(settings, "SURVEY_EXTRACTION_MODEL", SURVEY_LLM_DEFAULT_MODEL)
logger = logging.getLogger(__name__)


class SurveyManager:
    AGENT_MODEL = SURVEY_LLM_DEFAULT_MODEL
    HISTORY_LIMIT = 10

    @classmethod
    def run_survey_turn(cls, conversation: SurveyConversation, user_input: str, skip_question: bool = False) -> Dict[str, Any]:
        metadata = conversation.metadata or {}
        completed_ids = cls._normalize_completed(metadata.get("completed_questions"))
        current_idx = len(completed_ids)

        if conversation.status == SurveyConversation.STATUS_CLOSED or current_idx >= len(SURVEY_QUESTIONS):
            conversation.status = SurveyConversation.STATUS_CLOSED
            conversation.save(update_fields=["status"])
            return {
                "bot_message": SURVEY_CLOSING_MESSAGE,
                "insights": conversation.implicit_insights or [],
                "profile": metadata.get("profile") if isinstance(metadata.get("profile"), dict) else {},
                "question_count": len(SURVEY_QUESTIONS),
                "done": True,
                "agent_mood": "Neutral",
                "agent_topic": "Survey",
            }

        current_question = SURVEY_QUESTIONS[current_idx]
        follow_up_allowed = cls._is_follow_up_allowed(conversation, current_question["id"])

        SurveyInteraction.objects.create(
            conversation=conversation,
            role=SurveyInteraction.ROLE_USER,
            question_id=current_question["id"],
            question_label=current_question["text"],
            content=user_input,
            metadata={"skipped": skip_question} if skip_question else None,
        )

        if skip_question:
            return cls._handle_skip(conversation, current_question, metadata, completed_ids)

        agent_response = cls._call_agent(current_question, user_input, conversation, follow_up_allowed)

        if not agent_response.is_clarification:
            completed_ids.append(current_question["id"])
            metadata["completed_questions"] = completed_ids
            conversation.question_count = len(completed_ids)
        next_question_number = min(len(completed_ids) + 1, len(SURVEY_QUESTIONS))

        if agent_response.is_clarification:
            final_output = cls._join_message(agent_response.acknowledgement, agent_response.message)
        else:
            if len(completed_ids) >= len(SURVEY_QUESTIONS):
                conversation.status = SurveyConversation.STATUS_CLOSED
                final_output = cls._join_message(agent_response.acknowledgement, SURVEY_CLOSING_MESSAGE)
            else:
                next_question = SURVEY_QUESTIONS[len(completed_ids)]
                final_output = cls._join_message(agent_response.acknowledgement, next_question["text"])

        extracted_insights, profile_updates = _extract_insights_and_profile(user_input)
        merged_insights = _merge_insight_labels(conversation.implicit_insights or [], extracted_insights)
        conversation.implicit_insights = merged_insights

        profile = _merge_profile(_empty_profile(), metadata.get("profile") or {})
        profile = _merge_profile(profile, profile_updates)
        metadata["profile"] = profile

        metadata.setdefault("agent_history", [])
        metadata["agent_history"].append(
            {
                "question_id": current_question["id"],
                "mood": agent_response.mood,
                "topic_match": agent_response.topic_match,
                "is_follow_up": agent_response.is_clarification,
            }
        )
        metadata["agent_history"] = metadata["agent_history"][-25:]
        conversation.metadata = metadata

        SurveyInteraction.objects.create(
            conversation=conversation,
            role=SurveyInteraction.ROLE_BOT,
            question_id=current_question["id"],
            question_label=current_question["text"],
            topic=agent_response.topic_match,
            content=final_output,
            metadata={
                "mood": agent_response.mood,
                "is_follow_up": agent_response.is_clarification,
            },
        )

        conversation.save()

        return {
            "bot_message": final_output,
            "insights": merged_insights,
            "profile": profile,
            "question_count": next_question_number,
            "done": conversation.status == SurveyConversation.STATUS_CLOSED,
            "agent_mood": agent_response.mood,
            "agent_topic": agent_response.topic_match,
        }

    @classmethod
    def _call_agent(cls, question_data: Dict[str, str], user_input: str, conversation: SurveyConversation, follow_up_allowed: bool) -> AgentResponse:
        history = cls._conversation_history(conversation, limit=cls.HISTORY_LIMIT)
        prompt = cls._build_agent_prompt(question_data, user_input, history, follow_up_allowed)
        try:
            client = llm.get_openai_client()
            response = client.responses.create(
                model=cls.AGENT_MODEL,
                temperature=0.4,
                input=[
                    {"role": "system", "content": SURVEY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
            )
        except (llm.MissingCredentials, llm.MissingDependency, llm.OpenAIError) as exc:
            logger.warning("Survey agent call skipped: %s", exc)
            return cls._fallback_response(question_data)

        raw_text = (_response_text(response) or "").strip()
        return cls._parse_agent_output(raw_text, question_data, follow_up_allowed)

    @classmethod
    def _build_agent_prompt(cls, question_data: Dict[str, str], user_input: str, history: str, follow_up_allowed: bool) -> str:
        follow_up_instruction = (
            "You may ask ONE clarifying follow-up question if the resident's answer is vague; set is_clarification=True and keep the follow-up short."
            if follow_up_allowed else
            "Do NOT ask another follow-up question; set is_clarification=False and move on."
        )
        return (
            f"Current survey question ({question_data['id']} – {question_data['topic']}): {question_data['text']}\n"
            f"Most recent resident answer: {user_input}\n"
            f"{follow_up_instruction}\n"
            f"Conversation history (most recent last):\n{history or 'None'}\n\n"
            "Respond with a strict JSON object using the fields: mood, topic_match, is_clarification, acknowledgement, message. "
            f"Choose mood from: {', '.join(AGENT_MOOD_CHOICES)}. "
            "topic_match should surface the primary theme you heard, and acknowledgement should be a brief, warm thank-you. "
            "The message field should contain either the clarifying follow-up or a short closing statement when you are ready to move on."
        )

    @classmethod
    def _parse_agent_output(cls, raw_text: str, question_data: Dict[str, str], follow_up_allowed: bool) -> AgentResponse:
        if not raw_text:
            return cls._fallback_response(question_data)

        candidate = cls._extract_json_block(raw_text)
        if not candidate:
            return cls._fallback_response(question_data)

        try:
            result = AgentResponse.parse_raw(candidate)
        except ValidationError:
            logger.warning("Survey agent returned unparsable JSON: %s", raw_text[:200])
            return cls._fallback_response(question_data)

        normalized = cls._normalize_response(result, question_data)
        if not follow_up_allowed and normalized.is_clarification:
            normalized.is_clarification = False
            normalized.message = ""
        return normalized

    @classmethod
    def _normalize_response(cls, response: AgentResponse, question_data: Dict[str, str]) -> AgentResponse:
        if response.mood not in AGENT_MOOD_CHOICES:
            response.mood = "Neutral"
        if not response.topic_match:
            response.topic_match = question_data["topic"]
        response.acknowledgement = (response.acknowledgement or "").strip()
        response.message = (response.message or "").strip()
        return response

    @classmethod
    def _fallback_response(cls, question_data: Dict[str, str]) -> AgentResponse:
        return AgentResponse(
            mood="Neutral",
            topic_match=question_data["topic"],
            is_clarification=False,
            acknowledgement="Thank you for sharing that.",
            message="",
        )

    @staticmethod
    def _join_message(*parts: str) -> str:
        return " ".join(part.strip() for part in parts if part).strip()

    @staticmethod
    def _conversation_history(conversation: SurveyConversation, limit: int = 8) -> str:
        interactions = list(conversation.interactions.order_by("created_at"))
        if limit:
            interactions = interactions[-limit:]
        lines = []
        for interaction in interactions:
            role = "Host" if interaction.role == SurveyInteraction.ROLE_BOT else "Resident"
            content = (interaction.content or "").strip()
            if not content:
                continue
            label = f" [{interaction.question_label}]" if interaction.question_label else ""
            lines.append(f"{role}{label}: {content}")
        return "\n".join(lines)

    @staticmethod
    def _extract_json_block(text: str) -> str:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return text
        return text[start : end + 1]

    @staticmethod
    def _normalize_completed(value: Any) -> List[str]:
        if isinstance(value, list):
            return [str(item) for item in value if isinstance(item, (str, int))]
        return []

    @staticmethod
    def _is_follow_up_allowed(conversation: SurveyConversation, question_id: str) -> bool:
        last_bot = conversation.interactions.filter(role=SurveyInteraction.ROLE_BOT).last()
        if not last_bot or not last_bot.metadata:
            return True
        return not (
            last_bot.metadata.get("is_follow_up")
            and last_bot.question_id == question_id
        )

    @classmethod
    def _handle_skip(
        cls,
        conversation: SurveyConversation,
        current_question: Dict[str, str],
        metadata: Dict[str, Any],
        completed_ids: List[str],
    ) -> Dict[str, Any]:
        completed_ids.append(current_question["id"])
        metadata["completed_questions"] = completed_ids
        conversation.question_count = len(completed_ids)

        metadata.setdefault("agent_history", [])
        metadata["agent_history"].append(
            {
                "question_id": current_question["id"],
                "mood": "Neutral",
                "topic_match": current_question["topic"],
                "is_follow_up": False,
                "skipped": True,
            }
        )
        metadata["agent_history"] = metadata["agent_history"][-25:]
        conversation.metadata = metadata

        if len(completed_ids) >= len(SURVEY_QUESTIONS):
            conversation.status = SurveyConversation.STATUS_CLOSED
            final_output = SURVEY_CLOSING_MESSAGE
        else:
            next_question = SURVEY_QUESTIONS[len(completed_ids)]
            final_output = f"Thanks for letting us move on. {next_question['text']}"

        SurveyInteraction.objects.create(
            conversation=conversation,
            role=SurveyInteraction.ROLE_BOT,
            question_id=current_question["id"],
            question_label=current_question["text"],
            topic=current_question["topic"],
            content=final_output,
            metadata={"skipped": True},
        )


        conversation.save()

        profile = metadata.get("profile") if isinstance(metadata.get("profile"), dict) else {}
        next_question_number = min(len(completed_ids) + 1, len(SURVEY_QUESTIONS))

        return {
            "bot_message": final_output,
            "insights": conversation.implicit_insights or [],
            "profile": profile,
            "question_count": next_question_number,
            "done": conversation.status == SurveyConversation.STATUS_CLOSED,
            "agent_mood": "Neutral",
            "agent_topic": current_question["topic"],
        }


@require_GET
def citizen_survey(request):
    """Render the conversational citizen survey experience."""

    context = _basic_page_context(
        "Citizen Survey · OpenSkagit",
        "Help shape OpenSkagit by sharing what data, tools, and civic insights matter most.",
    )
    context.update(
        {
            "survey_flow": {
                "opening_question": OPENING_QUESTION,
                "intro_hint": SURVEY_PUBLIC_HINT,
                "closing": SURVEY_CLOSING_MESSAGE,
                "finish_actions": SURVEY_FINISH_ACTIONS,
                "max_questions": SURVEY_MAX_QUESTIONS,
            },
            "conversation_id": str(uuid.uuid4()),
        }
    )
    metrics = _get_cached_home_portal_metrics()
    context.update(
        {
            "stats_cards": metrics.get("stats_cards", []),
            "total_parcels": metrics.get("total_parcels", 0),
            "restaurant_count": metrics.get("restaurant_count", 0),
            "menu_items_count": metrics.get("menu_items_count", 0),
        }
    )
    context["canonical_url"] = request.build_absolute_uri()
    context["og_url"] = context["canonical_url"]
    return render(request, "openskagit/citizen_survey.html", context)


@require_POST
def survey_response(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"error": "invalid JSON payload"}, status=400)

    conversation_id = payload.get("conversation_id")
    user_answer = (payload.get("user_answer") or "").strip()
    skip_question = payload.get("skip_question") is True

    if not conversation_id:
        return JsonResponse({"error": "conversation_id is required"}, status=400)

    try:
        conv_uuid = uuid.UUID(conversation_id)
    except (ValueError, TypeError):
        return JsonResponse({"error": "invalid conversation_id"}, status=400)

    conversation, _ = SurveyConversation.objects.get_or_create(conversation_id=conv_uuid)

    _ensure_opening_turn(conversation)

    if conversation.status == SurveyConversation.STATUS_CLOSED:
        return JsonResponse(
            {
                "bot_message": SURVEY_CLOSING_MESSAGE,
                "insights": conversation.implicit_insights or [],
                "profile": conversation.metadata.get("profile") if isinstance(conversation.metadata, dict) else {},
                "question_count": SURVEY_MAX_QUESTIONS,
                "done": True,
                "agent_mood": "Neutral",
                "agent_topic": "Survey",
            }
        )

    if not skip_question and not user_answer:
        return JsonResponse({"error": "user_answer is required"}, status=400)

    metadata = conversation.metadata or {}
    if not skip_question and not metadata.get("intro_done"):
        metadata["intro_done"] = True
        metadata["display_name"] = user_answer
        conversation.metadata = metadata
        conversation.save(update_fields=["metadata"])

        SurveyInteraction.objects.create(
            conversation=conversation,
            role=SurveyInteraction.ROLE_USER,
            content=user_answer,
            metadata={"intro": True},
        )

        first_question = SURVEY_QUESTIONS[0]
        name_label = user_answer.strip().split()[0] if user_answer.strip() else ""
        greeting = f"Nice to meet you, {name_label}." if name_label else "Nice to meet you."
        bot_message = f"{greeting} {first_question['text']}"

        SurveyInteraction.objects.create(
            conversation=conversation,
            role=SurveyInteraction.ROLE_BOT,
            question_id=first_question["id"],
            question_label=first_question["text"],
            content=bot_message,
            metadata={"intro_question": True},
        )

        return JsonResponse(
            {
                "bot_message": bot_message,
                "insights": conversation.implicit_insights or [],
                "profile": metadata.get("profile") if isinstance(metadata.get("profile"), dict) else {},
                "question_count": 1,
                "done": False,
                "agent_mood": "Neutral",
                "agent_topic": first_question["topic"],
            }
        )

    response_payload = SurveyManager.run_survey_turn(conversation, user_answer, skip_question=skip_question)
    return JsonResponse(response_payload)


def _empty_profile() -> Dict[str, Any]:
    return dict(LATENT_PROFILE_TEMPLATE)


def _merge_profile(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base or {})
    if not isinstance(updates, dict):
        return merged
    for field, allowed in LATENT_PROFILE_ALLOWED_VALUES.items():
        value = updates.get(field)
        if isinstance(value, str) and value in allowed:
            merged[field] = value
    return merged


def _sanitize_insight_list(values: Any) -> List[str]:
    sanitized: List[str] = []
    seen = set()
    if not isinstance(values, list):
        return sanitized
    for label in values:
        if not isinstance(label, str):
            continue
        norm = label.strip()
        if norm in INSIGHT_LABELS and norm not in seen:
            sanitized.append(norm)
            seen.add(norm)
    return sanitized


def _merge_insight_labels(existing: List[str], new_labels: List[str]) -> List[str]:
    ordered: List[str] = []
    seen = set()
    for label in (existing or []) + (new_labels or []):
        if isinstance(label, str) and label in INSIGHT_LABELS and label not in seen:
            ordered.append(label)
            seen.add(label)
    return ordered


def _profile_updates_from_labels(labels: List[str]) -> Dict[str, Any]:
    updates: Dict[str, Any] = {}
    for label in labels:
        if label in PAIN_LABEL_TO_PROFILE and "primary_pain" not in updates:
            updates["primary_pain"] = PAIN_LABEL_TO_PROFILE[label]
        if label in EMOTION_LABELS and "emotional_tone" not in updates:
            updates["emotional_tone"] = label
        if label in LIFE_CONTEXT_LABELS and "life_context" not in updates:
            updates["life_context"] = LIFE_CONTEXT_LABELS[label]
        if label in ORIENTATION_TO_TIME and "time_horizon" not in updates:
            updates["time_horizon"] = ORIENTATION_TO_TIME[label]
    return updates


def _extract_insights_and_profile(answer: str) -> Tuple[List[str], Dict[str, Any]]:
    if not answer:
        return [], {}

    instruction = (
        "You are the OpenSkagit Insight Extractor. Read the user's answer and extract up to three labels from "
        "the allowed list: clarity_gap, fairness_concern, process_friction, trust_gap, access_gap, frustrated, "
        "hopeful, curious, resigned, energized, homeowner, renter, business_operator, civic_participant, "
        "explorer_resident, short_term_problem, long_term_planning, systemic_issue. Choose only what is clearly "
        "implied. Return a strict JSON array of labels (e.g. [\"clarity_gap\", \"homeowner\"])."
    )
    payload = f"{instruction}\n\nAnswer:\n{answer}"

    try:
        client = llm.get_openai_client()
        response = client.responses.create(
            model=SURVEY_EXTRACTION_MODEL,
            temperature=0.1,
            input=[
                {"role": "system", "content": "OpenSkagit Insight Extractor"},
                {"role": "user", "content": payload},
            ],
        )
    except (llm.MissingCredentials, llm.MissingDependency, llm.OpenAIError) as exc:
        logger.debug("Survey insight extraction skipped: %s", exc)
        return [], {}

    raw_text = _response_text(response)
    if not raw_text:
        return [], {}
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        logger.warning("Survey insight extraction returned non-JSON payload: %s", raw_text[:200])
        return [], {}

    if isinstance(parsed, list):
        labels = parsed
    elif isinstance(parsed, dict) and "insights" in parsed:
        labels = parsed.get("insights")
    else:
        labels = []

    insights = _sanitize_insight_list(labels)
    profile_updates = _profile_updates_from_labels(insights)
    return insights, profile_updates


def _response_text(response: Any) -> str:
    raw_text = getattr(response, "output_text", None)
    if raw_text:
        return raw_text
    try:
        return response.output[0].content[0].text
    except Exception:
        return ""


def _ensure_opening_turn(conversation: SurveyConversation) -> None:
    if conversation.question_count > 0 or conversation.interactions.exists():
        return
    SurveyInteraction.objects.create(
        conversation=conversation,
        role=SurveyInteraction.ROLE_BOT,
        content=OPENING_QUESTION,
        question_label="Opening",
    )
