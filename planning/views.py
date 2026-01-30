import json
import logging
import re
from typing import Optional

import httpx
from django.conf import settings
from django.db import connection, transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST
from pgvector import Vector

from openskagit import llm
from legal_code.models import (
    JurisdictionAlias,
    LawChapter,
    LawDocument,
    LawSection,
    LawSectionChunk,
)
from openskagit.models import CodeSetActivationRule, MasterParcel, ParcelPlanningFacts
from reference_data.models import ParcelZoning

LAW_SECTION_SAMPLE_LIMIT = 10
SPACE_RE = re.compile(r"\s+")
logger = logging.getLogger(__name__)
EMBEDDING_MODEL = getattr(settings, "OPENAI_LAW_EMBEDDING_MODEL", "text-embedding-3-small")
LAW_CHUNK_LIMIT = getattr(settings, "PLANNING_LAW_CHUNK_LIMIT", 4)
PARCEL_INTENT_ENUM = [
    "new_residential_dwelling",
    "add_adu",
    "residential_addition_or_alteration",
    "new_commercial_building",
    "commercial_addition_or_alteration",
    "accessory_structure",
    "land_division_or_site_development",
    "demolition",
    "floodplain_development",
    "land_disturbance",
    "right_of_way_or_access",
    "septic_system",
    "water_source",
    "utility_installation",
    "wireless_facility",
    "fire_code_installation",
    "temporary_or_event_use",
    "transport_or_vehicle",
    "energy_or_financing_program",
]

INTENT_SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["clarify", "classified"]},
        "clarifying_question": {"type": "string"},
        "summary": {
            "type": "string",
            "description": "One-sentence plain-English description of the project.",
        },
        "creates_new_dwelling_unit": {
            "type": ["boolean", "null"],
            "description": "True only if a separate dwelling unit is created (ADU, duplex, etc).",
        },
        "attached_to_existing_structure": {
            "type": ["boolean", "null"],
            "description": "True if physically attached to an existing building.",
        },
        "creates_habitable_space": {
            "type": ["boolean", "null"],
            "description": "True if space is intended for living, sleeping, cooking, or sanitation.",
        },
        "changes_use_or_occupancy": {
            "type": ["boolean", "null"],
            "description": "True if use or occupancy classification changes.",
        },
        "primary_work_type": {
            "type": "string",
            "enum": ["addition", "alteration", "new_structure", "conversion", "demolition", "unknown"],
        },
        "secondary_elements": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "string", "enum": ["low", "medium", "high"]},
        "parcel_intents": {
            "type": "array",
            "items": {
                "type": "string",
                "enum": PARCEL_INTENT_ENUM,
            },
            "description": "One or more canonical parcel intent keys derived from the project description.",
        },
    },
    "required": [
        "status",
        "clarifying_question",
        "summary",
        "creates_new_dwelling_unit",
        "attached_to_existing_structure",
        "creates_habitable_space",
        "changes_use_or_occupancy",
        "primary_work_type",
        "secondary_elements",
        "confidence",
        "parcel_intents",
    ],
    "additionalProperties": False,
}

OVERLAY_FACT_FIELDS = [
    "in_shoreline_jurisdiction",
    "in_sfha",
    "in_wetland",
    "in_stream_buffer",
]

OVERLAY_KEY_TO_FACTS = {
    "shoreline": ["in_shoreline_jurisdiction"],
    "floodplain": ["in_sfha"],
    "critical_area": ["in_wetland", "in_stream_buffer"],
}

PRODUCT_ALLOWED_INTENTS = [
    "add_adu",
    "build_primary_residence",
    "add_accessory_structure",
    "remodel_existing_structure",
    "replace_septic",
    "add_driveway",
    "shoreline_development",
    "floodplain_development",
    "unknown",
]

PRODUCT_INTENT_CLASSIFIER_SCHEMA = {
    "type": "object",
    "properties": {
        "parcel_intent": {
            "type": "string",
            "enum": PRODUCT_ALLOWED_INTENTS,
        },
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
    },
    "required": ["parcel_intent", "confidence"],
    "additionalProperties": False,
}

PRODUCT_INTENT_CLASSIFIER_INSTRUCTIONS = """
SYSTEM:
You are an intent classifier for a parcel-based planning system.
Your job is ONLY to map user intent to a canonical parcel_intent key.
Do not explain. Do not reason about law.

Allowed intents (authoritative):
- add_adu
- build_primary_residence
- add_accessory_structure
- remodel_existing_structure
- replace_septic
- add_driveway
- shoreline_development
- floodplain_development
- unknown

USER INPUT:
"{free_text}"

OUTPUT (JSON ONLY):
{
  "parcel_intent": "<one of the allowed intents>",
  "confidence": 0.0–1.0
}

Rules:
- If unclear, return "unknown"
- Never invent new intents
- Do not include commentary
"""

GRAPH_RAG_CHUNK_LIMIT = getattr(settings, "PLANNING_GRAPH_RAG_CHUNK_LIMIT", 6)
GRAPH_RAG_RESPONSE_MODEL = getattr(settings, "PLANNING_GRAPH_RAG_RESPONSE_MODEL", "gpt-4o-mini")
GRAPH_RAG_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "confidence": {
            "type": "number",
            "minimum": 0.0,
            "maximum": 1.0,
        },
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "chunk_index": {"type": "integer"},
                    "law_section_ref": {"type": "string"},
                    "source_url": {"type": "string"},
                    "quote": {"type": "string"},
                },
                "required": ["chunk_index", "law_section_ref", "source_url", "quote"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["answer", "confidence", "citations"],
    "additionalProperties": False,
}
GRAPH_RAG_RESPONSE_INSTRUCTIONS = """
SYSTEM:
You are a legal planning assistant. The user will ask a question about a parcel intent and reference specific legal text chunks.
Use only the provided snippets; do not hallucinate new law or reinterpretations.
Answer concisely and refer to the chunk indexes when citing the law.
Return STRICT JSON matching the schema supplied in the request. Do not add any commentary outside of the JSON.
"""


def _normalize_jurisdiction(value: Optional[str]) -> str:
    if not value:
        return ""
    cleaned = value.strip().lower()
    cleaned = SPACE_RE.sub("_", cleaned)
    return cleaned


def _build_overlay_condition_text(overlay_key: str, overlay_facts: dict) -> tuple[str | None, bool]:
    fields = OVERLAY_KEY_TO_FACTS.get(overlay_key)
    if not fields:
        return f"{overlay_key} (unknown overlay)", False
    condition_parts = [f"{field} = true" for field in fields]
    condition_text = " OR ".join(condition_parts)
    satisfied = any(bool(overlay_facts.get(field)) for field in fields)
    return condition_text, satisfied


def _fetch_primary_zone(parcel_number: str) -> dict | None:
    base_query_with_use_class = """
        SELECT pz.zone_id,
               z.jurisdiction,
               z.zone_code,
               z.zoning_general_class,
               z.zoning_specific_class,
               z.zoning_use_class
        FROM parcel_zoning pz
        JOIN zoning_zone z ON z.id = pz.zone_id
        WHERE pz.parcel_id = (
            SELECT parcel_number
            FROM master_parcel
            WHERE parcel_number = %s
        )
          AND pz.is_primary = true
        LIMIT 1
    """
    base_query_without_use_class = """
        SELECT pz.zone_id,
               z.jurisdiction,
               z.zone_code,
               z.zoning_general_class,
               z.zoning_specific_class
        FROM parcel_zoning pz
        JOIN zoning_zone z ON z.id = pz.zone_id
        WHERE pz.parcel_id = (
            SELECT parcel_number
            FROM master_parcel
            WHERE parcel_number = %s
        )
          AND pz.is_primary = true
        LIMIT 1
    """

    with connection.cursor() as cursor:
        try:
            cursor.execute(base_query_with_use_class, [parcel_number])
        except Exception as exc:  # pragma: no cover - fallback when column is missing
            logger.debug("Primary zoning query without zoning_use_class: %s", exc)
            cursor.execute(base_query_without_use_class, [parcel_number])
            row = cursor.fetchone()
            if not row:
                return None
            zone_id, jurisdiction, zone_code, general_class, specific_class = row
            return {
                "zoning_zone_id": zone_id,
                "jurisdiction": jurisdiction,
                "zone_code": zone_code,
                "zoning_general_class": general_class,
                "zoning_specific_class": specific_class,
                "zoning_use_class": None,
            }
        row = cursor.fetchone()
    if not row:
        return None
    (
        zone_id,
        jurisdiction,
        zone_code,
        general_class,
        specific_class,
        zoning_use_class,
    ) = row
    return {
        "zoning_zone_id": zone_id,
        "jurisdiction": jurisdiction,
        "zone_code": zone_code,
        "zoning_general_class": general_class,
        "zoning_specific_class": specific_class,
        "zoning_use_class": zoning_use_class,
    }


def _fetch_overlay_facts(parcel_number: str) -> dict:
    facts = (
        ParcelPlanningFacts.objects.filter(parcel__parcel_number__iexact=parcel_number)
        .values(*OVERLAY_FACT_FIELDS)
        .first()
    )
    if not facts:
        return {field: None for field in OVERLAY_FACT_FIELDS}
    return {field: facts.get(field) for field in OVERLAY_FACT_FIELDS}


def _fetch_code_sets_from_view(view_name: str, parcel_number: str, intent: str | None = None) -> list[str]:
    code_sets: list[str] = []
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                if intent:
                    cursor.execute("SET LOCAL app.parcel_intent = %s", [intent])
                cursor.execute(
                    f"SELECT code_set FROM {view_name} WHERE parcel_number = %s",
                    [parcel_number],
                )
                code_sets = [row[0] for row in cursor.fetchall()]
    except Exception:
        logger.exception("Failed to load code sets from %s for %s", view_name, parcel_number)
    return code_sets


def _fetch_base_code_sets(parcel_number: str) -> list[str]:
    return _fetch_code_sets_from_view("v_parcel_code_sets", parcel_number)


def _fetch_final_active_code_sets(parcel_number: str, intent: str) -> list[str]:
    return _fetch_code_sets_from_view("v_parcel_active_code_sets", parcel_number, intent=intent)


def _evaluate_activation_rules(intent: str, zoning_use_class: str | None, overlay_facts: dict) -> list[dict]:
    normalized_intent = intent or ""
    normalized_zone = (zoning_use_class or "").strip().lower()
    matched: dict[str, dict] = {}
    for rule in CodeSetActivationRule.objects.all():
        intent_match = not rule.parcel_intent or rule.parcel_intent == normalized_intent
        zone_match = True
        if rule.zoning_use_class:
            zone_match = (
                normalized_zone
                and rule.zoning_use_class.strip().lower() == normalized_zone
            )
        overlay_condition = None
        overlay_match = True
        if rule.requires_overlay:
            overlay_condition, overlay_match = _build_overlay_condition_text(
                rule.requires_overlay, overlay_facts
            )
        if intent_match and zone_match and overlay_match:
            matched[rule.code_set] = {
                "code_set": rule.code_set,
                "activation_reason": {
                    "intent_match": intent_match,
                    "zoning_use_class_match": zone_match,
                    "overlay_condition": overlay_condition,
                },
            }
    return list(matched.values())


def _fetch_candidate_chapters(code_sets: list[str]) -> list[dict]:
    if not code_sets:
        return []
    chapters = (
        LawChapter.objects.filter(code_set__in=set(code_sets))
        .values("id", "code_set", "chapter_number", "chapter_name")
        .order_by("code_set", "chapter_number")
    )
    return [
        {
            "code_set": chapter["code_set"],
            "chapter_id": chapter["id"],
            "chapter_number": chapter["chapter_number"],
            "chapter_name": chapter["chapter_name"],
        }
        for chapter in chapters
    ]


def _classify_parcel_intent(user_text: str) -> dict:
    if not user_text:
        return {"parcel_intent": "unknown", "confidence": 0.0, "raw": ""}
    try:
        client = llm.get_openai_client()
        model_name = getattr(settings, "OPENAI_RESPONSES_MODEL", "gpt-4o-mini")
        response = client.responses.create(
            model=model_name,
            instructions=PRODUCT_INTENT_CLASSIFIER_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f'USER INPUT:\n"{user_text}"',
                        }
                    ],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "parcel_intent",
                    "schema": PRODUCT_INTENT_CLASSIFIER_SCHEMA,
                    "strict": True,
                }
            },
            temperature=0.0,
        )
        raw_text = getattr(response, "output_text", "") or ""
        payload = json.loads(raw_text)
        intent = payload.get("parcel_intent")
        confidence = float(payload.get("confidence") or 0.0)
        if intent not in PRODUCT_ALLOWED_INTENTS:
            intent = "unknown"
        confidence = max(0.0, min(1.0, confidence))
        return {"parcel_intent": intent, "confidence": confidence, "raw": raw_text}
    except Exception:
        logger.exception("Product intent classification failed.")
        return {"parcel_intent": "unknown", "confidence": 0.0, "raw": ""}


def _resolve_context_for_parcel(parcel: MasterParcel, intent: str) -> dict:
    primary_zone = _fetch_primary_zone(parcel.parcel_number)
    jurisdiction_raw = primary_zone.get("jurisdiction") if primary_zone else ""
    if not jurisdiction_raw:
        zoning_jurisdiction = (
            ParcelPlanningFacts.objects.filter(parcel__parcel_number__iexact=parcel.parcel_number)
            .values_list("zoning_jurisdiction", flat=True)
            .first()
        )
        jurisdiction_raw = zoning_jurisdiction or ""

    normalized_jurisdiction_id = None
    normalized_jurisdiction = _normalize_jurisdiction(jurisdiction_raw)
    if normalized_jurisdiction:
        alias = JurisdictionAlias.objects.filter(alias_normalized=normalized_jurisdiction).first()
        if alias:
            normalized_jurisdiction_id = alias.jurisdiction_id

    overlay_facts = _fetch_overlay_facts(parcel.parcel_number)
    base_code_sets = _fetch_base_code_sets(parcel.parcel_number)
    final_code_sets = _fetch_final_active_code_sets(parcel.parcel_number, intent)
    activated_code_sets = _evaluate_activation_rules(
        intent,
        primary_zone.get("zoning_use_class") if primary_zone else None,
        overlay_facts,
    )
    candidate_chapters = _fetch_candidate_chapters(final_code_sets)

    return {
        "parcel_number": parcel.parcel_number,
        "jurisdiction": {
            "raw": jurisdiction_raw,
            "normalized_jurisdiction_id": normalized_jurisdiction_id,
        },
        "zoning": {
            "zoning_zone_id": primary_zone.get("zoning_zone_id") if primary_zone else None,
            "zone_code": primary_zone.get("zone_code") if primary_zone else None,
            "zoning_use_class": primary_zone.get("zoning_use_class") if primary_zone else None,
            "zoning_general_class": primary_zone.get("zoning_general_class") if primary_zone else None,
            "zoning_specific_class": primary_zone.get("zoning_specific_class") if primary_zone else None,
        },
        "intent": intent,
        "overlay_facts_used": overlay_facts,
        "base_code_sets": [
            {"code_set": code_set, "source": "v_parcel_code_sets"} for code_set in base_code_sets
        ],
        "activated_code_sets": activated_code_sets,
        "final_active_code_sets": final_code_sets,
        "candidate_chapters": candidate_chapters,
    }


@require_GET
def planning_home(request) -> HttpResponse:
    canonical_url = request.build_absolute_uri()
    return render(
        request,
        "planning/planning_home.html",
        {
            "step": 1,
            "portal_badge": "OpenSkagit Planning",
            "show_stepper": True,
            "page_title": "Parcel Planning",
            "meta_description": "Locate a parcel and review zoning zone details.",
            "og_title": "Parcel Planning",
            "og_url": canonical_url,
            "canonical_url": canonical_url,
            "planning_detail_url": reverse("planning-parcel-detail", args=["PARCEL_ID"]),
            "scope_resolve_url": reverse("planning-scope-resolve-product"),
            "planning_debug_url": reverse("planning-home-debug"),
        },
    )


@require_GET
def planning_scope_debug(request) -> HttpResponse:
    canonical_url = request.build_absolute_uri()
    intent_options = [
        {"key": value, "label": value.replace("_", " ").title()}
        for value in CodeSetActivationRule.objects.filter(parcel_intent__isnull=False)
        .order_by("parcel_intent")
        .values_list("parcel_intent", flat=True)
        .distinct()
    ]
    return render(
        request,
        "planning/planning_scope_debug.html",
        {
            "step": 1,
            "portal_badge": "OpenSkagit Planning",
            "show_stepper": True,
            "page_title": "Parcel Planning Debug",
            "meta_description": "Resolve scope with explicit intent selection.",
            "og_title": "Parcel Planning Debug",
            "og_url": canonical_url,
            "canonical_url": canonical_url,
            "planning_detail_url": reverse("planning-parcel-detail", args=["PARCEL_ID"]),
            "scope_resolve_url": reverse("planning-scope-resolve-debug"),
        },
    )


@require_GET
def planning_parcel_search(request) -> HttpResponse:
    from openskagit import views as openskagit_views

    return openskagit_views.appeal_parcel_search(request)


@require_POST
def planning_intent_classify(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)

    user_input = (payload.get("user_input") or "").strip()
    if not user_input:
        return JsonResponse({"ok": False, "error": "user_input is required."}, status=400)

    is_followup = payload.get("is_followup") is True
    previous_input = (payload.get("previous_input") or "").strip()
    clarifying_question = (payload.get("clarifying_question") or "").strip()

    if is_followup and not previous_input:
        is_followup = False

    if is_followup:
        user_prompt = (
            "Initial user description:\n"
            f"{previous_input}\n\n"
            "Clarifying question you asked:\n"
            f"{clarifying_question}\n\n"
            "User follow-up answer:\n"
            f"{user_input}"
        )
    else:
        user_prompt = f"User project description:\n{user_input}"

    instructions = (
        "You are a land-use project intent classifier for a parcel planning tool. "
        "Goal: answer the decisive questions about whether this project adds a dwelling unit, "
        "what is attached or detached, whether it creates habitable space, and whether it changes use or occupancy. "
        "These answers determine the correct rule path rather than a single project label. "
        "If the user has not provided enough detail to respond to those questions, ask exactly one clarifying question. "
        "If clarification is needed, set status to 'clarify', include the question in clarifying_question, and set "
        "all classification fields (summary, creates_new_dwelling_unit, attached_to_existing_structure, "
        "creates_habitable_space, changes_use_or_occupancy, primary_work_type, secondary_elements, confidence) "
        "to reasonable defaults or null values, with confidence as 'low'. "
        "If classification is possible, set status to 'classified', set clarifying_question to an empty string, "
        "and answer each field according to the schema."
    )
    instructions += (
        " After determining the project characteristics, you must assign one or more `parcel_intents` from the allowed enum list.\n"
        "Derive parcel_intents strictly from the classification fields you produced.\n"
        "Do not invent new intents.\n"
        "If insufficient information exists to choose an intent with confidence, set status to `clarify` and ask one question instead."
    )
    if is_followup:
        instructions += (
            " You already asked your one clarifying question. "
            "Now you must classify and set status to 'classified' with an empty clarifying_question."
        )

    try:
        client = llm.get_openai_client()
        model_name = getattr(settings, "OPENAI_RESPONSES_MODEL", "gpt-4o-mini")
        response = client.responses.create(
            model=model_name,
            instructions=instructions,
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "parcel_intent",
                    "schema": INTENT_SCHEMA,
                    "strict": True,
                }
            },
            temperature=0.2,
        )
    except httpx.HTTPStatusError as exc:
        response_obj = getattr(exc, "response", None)
        status_code = getattr(response_obj, "status_code", "unknown")
        logger.error("Intent classification OpenAI HTTP error: %s", status_code)
        return JsonResponse({"ok": False, "error": "Intent classification failed."}, status=502)
    except llm.OpenAIError as exc:
        logger.error("Intent classification OpenAI client error: %s", exc)
        return JsonResponse({"ok": False, "error": "Intent classification failed."}, status=502)
    except Exception:  # pragma: no cover - defensive
        logger.exception("Intent classification failed unexpectedly.")
        return JsonResponse({"ok": False, "error": "Intent classification failed."}, status=502)

    if getattr(response, "refusal", None):
        return JsonResponse({"ok": False, "error": "Intent classification refused."}, status=502)

    raw_text = getattr(response, "output_text", "") or ""
    if not raw_text:
        return JsonResponse({"ok": False, "error": "Empty intent response."}, status=502)

    try:
        intent_payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid intent response."}, status=502)

    intents = intent_payload.get("parcel_intents", [])
    unknown = set(intents) - set(PARCEL_INTENT_ENUM)

    if unknown:
        logger.error("Unknown parcel_intents returned: %s", unknown)
        return JsonResponse(
            {"ok": False, "error": "Invalid intent classification."},
            status=502,
        )

    status = intent_payload.get("status") or "classified"
    law_chunks = []

    if status == "classified":
        jurisdiction_id_raw = payload.get("jurisdiction_id")
        try:
            jurisdiction_id = int(jurisdiction_id_raw) if jurisdiction_id_raw else None
        except (TypeError, ValueError):
            jurisdiction_id = None

        if jurisdiction_id:
            summary = (intent_payload.get("summary") or "").strip()
            project_secondary = intent_payload.get("secondary_elements") or []
            creates_new = intent_payload.get("creates_new_dwelling_unit")
            attached = intent_payload.get("attached_to_existing_structure")
            habitable = intent_payload.get("creates_habitable_space")
            change_use = intent_payload.get("changes_use_or_occupancy")
            primary_work = intent_payload.get("primary_work_type") or ""
            query_parts = [summary] if summary else []
            if creates_new is not None:
                query_parts.append(f"Creates new dwelling unit: {creates_new}")
            if attached is not None:
                query_parts.append(f"Attached to existing structure: {attached}")
            if habitable is not None:
                query_parts.append(f"Creates habitable space: {habitable}")
            if change_use is not None:
                query_parts.append(f"Changes use/occupancy: {change_use}")
            if primary_work:
                query_parts.append(f"Primary work type: {primary_work}")
            if project_secondary:
                query_parts.append("Secondaries: " + ", ".join(project_secondary))
            if user_input:
                query_parts.append("Description: " + user_input)
            query_text = " | ".join(query_parts) or summary or user_input

            if query_text:
                try:
                    embedding_resp = client.embeddings.create(
                        model=EMBEDDING_MODEL,
                        input=[query_text],
                    )
                    vector_values = embedding_resp.data[0].embedding
                    vector_literal = "[" + ",".join(str(value) for value in vector_values) + "]"

                    with connection.cursor() as cursor:
                        cursor.execute(
                        """
                        SELECT law_section_ref, heading, content, source_url
                        FROM legal_code_lawsectionchunk
                        WHERE jurisdiction_id = %s AND embedding IS NOT NULL
                        ORDER BY embedding <=> %s
                        LIMIT %s;
                        """,
                        [jurisdiction_id, vector_literal, LAW_CHUNK_LIMIT],
                    )
                        rows = cursor.fetchall()

                    for law_section_ref, heading, content, source_url in rows:
                        law_chunks.append(
                            {
                                "law_section_ref": law_section_ref,
                                "heading": heading or "",
                                "content": content,
                                "source_url": source_url,
                            }
                        )
                except Exception:
                    logger.exception("Failed to load law chunks from pgvector search.")

    return JsonResponse(
        {
            "ok": True,
            "status": status,
            "payload": intent_payload,
            "law_chunks": law_chunks,
        }
    )


@require_POST
def planning_scope_resolve_debug(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)

    parcel_number = (payload.get("parcel_number") or "").strip()
    intent = (payload.get("intent") or "").strip()
    if not parcel_number:
        return JsonResponse({"ok": False, "error": "parcel_number is required."}, status=400)
    if not intent:
        return JsonResponse({"ok": False, "error": "intent is required."}, status=400)

    parcel = MasterParcel.objects.filter(parcel_number__iexact=parcel_number).first()
    if not parcel:
        return JsonResponse({"ok": False, "error": "Parcel not found."}, status=404)

    resolved_context = _resolve_context_for_parcel(parcel, intent)
    resolved_context["intent_source"] = "manual"
    resolved_context["provided_intent"] = intent

    return JsonResponse({"ok": True, "resolved_context": resolved_context})


@require_POST
def planning_scope_resolve_product(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({"ok": False, "error": "Invalid JSON payload."}, status=400)

    parcel_number = (payload.get("parcel_number") or "").strip()
    description = (payload.get("description") or "").strip()
    if not parcel_number:
        return JsonResponse({"ok": False, "error": "parcel_number is required."}, status=400)
    if not description:
        return JsonResponse({"ok": False, "error": "description is required."}, status=400)

    parcel = MasterParcel.objects.filter(parcel_number__iexact=parcel_number).first()
    if not parcel:
        return JsonResponse({"ok": False, "error": "Parcel not found."}, status=404)

    classification = _classify_parcel_intent(description)
    intent = classification.get("parcel_intent") or "unknown"
    logger.info(
        "Derived intent %s (confidence=%.2f) for parcel %s",
        intent,
        classification.get("confidence", 0.0),
        parcel.parcel_number,
    )

    resolved_context = _resolve_context_for_parcel(parcel, intent)
    resolved_context["intent_source"] = "classified"
    resolved_context["derived_intent"] = classification
    resolved_context["user_description"] = description

    return JsonResponse({"ok": True, "resolved_context": resolved_context})


@require_GET
def planning_parcel_detail(request, parcel_number: str) -> HttpResponse:
    parcel = (
        MasterParcel.objects.filter(parcel_number__iexact=parcel_number).first()
    )
    if not parcel:
        return render(
            request,
            "planning/partials/planning_parcel_results.html",
            {"error_message": "Parcel not found."},
            status=404,
        )

    primary_zoning = (
        ParcelZoning.objects.filter(parcel=parcel, is_primary=True)
        .select_related("zone")
        .first()
    )
    primary_zone = None
    jurisdiction_alias = None
    governing_jurisdiction = None
    jurisdiction_normalized = None
    law_documents_total = 0
    law_sections_total = 0
    law_sections = []

    if primary_zoning and primary_zoning.zone:
        zone = primary_zoning.zone
        pct = None
        if primary_zoning.pct_of_parcel is not None:
            pct = round(primary_zoning.pct_of_parcel * 100, 2)
        primary_zone = {
            "zone_code": zone.zone_code,
            "jurisdiction": zone.jurisdiction,
            "zoning_general_class": zone.zoning_general_class,
            "zoning_specific_class": zone.zoning_specific_class,
            "source": zone.source,
            "reference_url": zone.reference_url,
            "pct_of_parcel": pct,
        }
        jurisdiction_normalized = _normalize_jurisdiction(zone.jurisdiction)
        if jurisdiction_normalized:
            jurisdiction_alias = (
                JurisdictionAlias.objects.select_related("jurisdiction")
                .filter(alias_normalized=jurisdiction_normalized)
                .first()
            )
            if jurisdiction_alias:
                governing_jurisdiction = jurisdiction_alias.jurisdiction
                law_documents_total = LawDocument.objects.filter(
                    jurisdiction=governing_jurisdiction
                ).count()
                sections_base = LawSection.objects.filter(
                    chapter__document__jurisdiction=governing_jurisdiction
                ).select_related("chapter__document")
                law_sections_total = sections_base.count()
                law_sections = list(
                    sections_base.order_by("section_id")[
                        :LAW_SECTION_SAMPLE_LIMIT
                    ]
                )

    return render(
        request,
        "planning/partials/planning_parcel_results.html",
        {
            "parcel": parcel,
            "primary_zone": primary_zone,
            "jurisdiction_alias": jurisdiction_alias,
            "governing_jurisdiction": governing_jurisdiction,
            "jurisdiction_normalized": jurisdiction_normalized,
            "law_documents_total": law_documents_total,
            "law_sections_total": law_sections_total,
            "law_sections": law_sections,
            "law_section_limit": LAW_SECTION_SAMPLE_LIMIT,
        },
    )


@require_GET
def planning_parcel_detail_json(request) -> JsonResponse:
    parcel_number = (request.GET.get("parcel_number") or "").strip()
    if not parcel_number:
        return _json_error("parcel_number is required.")

    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT
                mp.parcel_number,
                mp.situs_address,
                z.jurisdiction,
                z.zone_code,
                z.zoning_use_class,
                pf.in_shoreline_jurisdiction,
                pf.in_sfha,
                pf.in_wetland,
                pf.in_stream_buffer
            FROM master_parcel mp
            LEFT JOIN parcel_planning_facts pf
              ON pf.parcel_id = mp.parcel_number
            LEFT JOIN parcel_zoning pz
              ON pz.parcel_id = mp.parcel_number
              AND pz.is_primary = true
            LEFT JOIN zoning_zone z
              ON z.id = pz.zone_id
            WHERE mp.parcel_number ILIKE %s
            LIMIT 1;
            """,
            [parcel_number],
        )
        row = cursor.fetchone()

    if not row:
        return _json_error("Parcel not found.", status=404)

    (
        parcel_number,
        situs_address,
        jurisdiction,
        zone_code,
        zoning_use_class,
        in_shoreline_jurisdiction,
        in_sfha,
        in_wetland,
        in_stream_buffer,
    ) = row

    return JsonResponse(
        {
            "parcel_number": parcel_number,
            "situs_address": situs_address,
            "zoning_jurisdiction": jurisdiction,
            "zone_code": zone_code,
            "zoning_use_class": zoning_use_class,
            "overlays": {
                "in_shoreline_jurisdiction": in_shoreline_jurisdiction,
                "in_sfha": in_sfha,
                "in_wetland": in_wetland,
                "in_stream_buffer": in_stream_buffer,
            },
        }
    )


def _json_error(message: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"ok": False, "error": message}, status=status)


def _format_graph_rag_chunks(chunks: list[dict]) -> tuple[str, list[dict]]:
    entries = []
    citations = []
    for index, chunk in enumerate(chunks, start=1):
        law_section_ref = chunk.get("law_section_ref") or ""
        heading = chunk.get("heading") or ""
        content = chunk.get("content") or ""
        source_url = chunk.get("source_url") or ""
        entries.append(
            f"Chunk {index} | {law_section_ref}\nHeading: {heading}\n{content}\nSource: {source_url}"
        )
        citations.append(
            {
                "chunk_index": index,
                "law_section_ref": law_section_ref,
                "source_url": source_url,
                "quote": content[:512],
            }
        )
    return "\n\n".join(entries), citations


@require_POST
def planning_intent_graph(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error("Invalid JSON payload.")

    parcel_number = (payload.get("parcel_number") or "").strip()
    description = (payload.get("description") or "").strip()

    if not parcel_number or not description:
        return _json_error("parcel_number and description are required.")

    parcel = MasterParcel.objects.filter(parcel_number__iexact=parcel_number).first()
    if not parcel:
        return _json_error("Parcel not found.", status=404)

    classification = _classify_parcel_intent(description)
    intent = classification.get("parcel_intent") or "unknown"
    confidence = float(classification.get("confidence") or 0.0)

    return JsonResponse(
        {
            "ok": True,
            "parcel_number": parcel.parcel_number,
            "intent": intent,
            "confidence": confidence,
            "candidates": [
                {"label": intent, "score": confidence},
            ],
            "raw_response": classification.get("raw") or "",
        }
    )


@require_GET
def planning_active_code_sets(request):
    parcel_number = (request.GET.get("parcel_number") or "").strip()
    intent = (request.GET.get("intent") or "").strip() or "unknown"

    if not parcel_number:
        return _json_error("parcel_number is required.")
    if not intent:
        return _json_error("intent is required.")

    parcel = MasterParcel.objects.filter(parcel_number__iexact=parcel_number).first()
    if not parcel:
        return _json_error("Parcel not found.", status=404)

    resolved_context = _resolve_context_for_parcel(parcel, intent)

    code_sets_payload = [
        {
            "name": code_set,
            "jurisdiction": resolved_context["jurisdiction"].get("raw"),
            "metadata": {"source": "v_parcel_active_code_sets"},
        }
        for code_set in resolved_context.get("final_active_code_sets") or []
    ]

    return JsonResponse(
        {
            "ok": True,
            "parcel_number": parcel.parcel_number,
            "intent": intent,
            "jurisdiction": resolved_context.get("jurisdiction", {}),
            "overlay_facts": resolved_context.get("overlay_facts_used", {}),
            "base_code_sets": resolved_context.get("base_code_sets", []),
            "final_code_sets": code_sets_payload,
            "activated_code_sets": resolved_context.get("activated_code_sets", []),
        }
    )


@require_POST
def planning_chunks(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error("Invalid JSON payload.")

    parcel_number = (payload.get("parcel_number") or "").strip()
    code_sets = payload.get("code_sets") or []
    intent = (payload.get("intent") or "unknown").strip() or "unknown"
    limit_value = payload.get("limit")
    try:
        limit = max(1, min(50, int(limit_value))) if limit_value is not None else GRAPH_RAG_CHUNK_LIMIT
    except (TypeError, ValueError):
        limit = GRAPH_RAG_CHUNK_LIMIT

    if not parcel_number:
        return _json_error("parcel_number is required.")
    if not code_sets:
        return _json_error("code_sets are required.")

    normalized_code_sets = [str(value).strip() for value in code_sets if value]
    if not normalized_code_sets:
        return _json_error("code_sets must contain at least one valid entry.")

    parcel = MasterParcel.objects.filter(parcel_number__iexact=parcel_number).first()
    if not parcel:
        return _json_error("Parcel not found.", status=404)

    resolved_context = _resolve_context_for_parcel(parcel, intent)
    jurisdiction_id = resolved_context["jurisdiction"].get("normalized_jurisdiction_id")

    chunk_query = LawSectionChunk.objects.filter(
        section__chapter__code_set__in=set(normalized_code_sets)
    )
    if jurisdiction_id:
        chunk_query = chunk_query.filter(jurisdiction_id=jurisdiction_id)

    chunk_rows = list(
        chunk_query.order_by("section_id", "chunk_index")
        .values(
            "law_section_ref",
            "heading",
            "content",
            "source_url",
            "chunk_index",
        )[:limit]
    )

    return JsonResponse(
        {
            "ok": True,
            "parcel_number": parcel.parcel_number,
            "intent": intent,
            "jurisdiction_id": jurisdiction_id,
            "code_sets": normalized_code_sets,
            "chunks": chunk_rows,
        }
    )


@require_POST
def planning_answer(request):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return _json_error("Invalid JSON payload.")

    parcel_number = (payload.get("parcel_number") or "").strip()
    intent = (payload.get("intent") or "unknown").strip() or "unknown"
    query_text = (payload.get("query") or "").strip()
    chunks = payload.get("chunks") or []

    if not parcel_number:
        return _json_error("parcel_number is required.")
    if not query_text:
        return _json_error("query is required.")
    if not chunks:
        return _json_error("chunks are required.")

    context_text, chunk_citations = _format_graph_rag_chunks(chunks)

    user_prompt = (
        f"Parcel: {parcel_number}\n"
        f"Intent: {intent}\n"
        f"Question: {query_text}\n\n"
        f"Referenced snippets:\n{context_text}"
    )

    raw_text = ""
    try:
        client = llm.get_openai_client()
        response = client.responses.create(
            model=GRAPH_RAG_RESPONSE_MODEL,
            instructions=GRAPH_RAG_RESPONSE_INSTRUCTIONS,
            input=[
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                }
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": "planning_answer",
                    "schema": GRAPH_RAG_ANSWER_SCHEMA,
                    "strict": False,
                }
            },
            temperature=0.2,
        )
        raw_text = getattr(response, "output_text", "") or ""
        parsed = json.loads(raw_text)
        answer_text = parsed.get("answer", "").strip()
        confidence = float(parsed.get("confidence", 0.0))
        citations = parsed.get("citations", [])
    except (llm.OpenAIError, ValueError) as exc:
        logger.exception("LLM answer generation failed for %s", parcel_number)
        return JsonResponse(
            {
                "ok": False,
                "error": "LLM answer generation failed.",
                "raw_response": getattr(exc, "args", [""])[0],
            },
            status=502,
        )
    except json.JSONDecodeError:
        logger.exception("Failed to parse LLM answer for %s", parcel_number)
        return JsonResponse(
            {
                "ok": False,
                "error": "LLM returned invalid answer payload.",
                "raw_response": raw_text,
            },
            status=502,
        )

    return JsonResponse(
        {
            "ok": True,
            "parcel_number": parcel_number,
            "intent": intent,
            "answer": answer_text,
            "confidence": max(0.0, min(1.0, confidence)),
            "citations": citations,
            "raw_response": raw_text,
            "chunks": chunk_citations,
        }
    )
