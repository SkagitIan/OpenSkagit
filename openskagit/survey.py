from __future__ import annotations

import json
from typing import Any, Dict, Optional

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from openskagit.services import citizen_survey as survey_service
from openskagit.views import _basic_page_context


SURVEY_PAGE_TITLE = "Weekly Citizen Survey | OpenSkagit"
SURVEY_META_DESCRIPTION = (
    "Take one weekly civic question for Skagit communities, view live response totals, "
    "and share what topics and cities you care about most."
)


def _bool_from_payload(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _parse_json_body(request: HttpRequest) -> Dict[str, Any]:
    try:
        return json.loads(request.body.decode("utf-8"))
    except (ValueError, TypeError, UnicodeDecodeError):
        return {}


def _wants_json_response(request: HttpRequest) -> bool:
    content_type = str(request.headers.get("Content-Type", "")).lower()
    accept = str(request.headers.get("Accept", "")).lower()
    return (
        "application/json" in content_type
        or "application/json" in accept
        or str(request.headers.get("X-Requested-With", "")).lower() == "xmlhttprequest"
        or str(request.headers.get("HX-Request", "")).lower() == "true"
    )


def _is_htmx_request(request: HttpRequest) -> bool:
    return str(request.headers.get("HX-Request", "")).lower() == "true"


def _set_participant_cookie(request: HttpRequest, response: HttpResponse, signed_cookie_value: str) -> None:
    response.set_cookie(
        survey_service.PARTICIPANT_COOKIE_NAME,
        signed_cookie_value,
        max_age=survey_service.PARTICIPANT_COOKIE_MAX_AGE,
        httponly=True,
        samesite="Lax",
        secure=request.is_secure(),
    )


def _question_json_ld(request: HttpRequest) -> Dict[str, Any]:
    survey_url = request.build_absolute_uri(reverse("citizen-survey"))
    return {
        "@context": "https://schema.org",
        "@type": "WebPage",
        "name": "Weekly Citizen Survey",
        "description": SURVEY_META_DESCRIPTION,
        "url": survey_url,
        "isPartOf": {
            "@type": "WebSite",
            "name": "OpenSkagit",
            "url": request.build_absolute_uri("/"),
        },
    }


def _breadcrumb_json_ld(request: HttpRequest) -> Dict[str, Any]:
    survey_url = request.build_absolute_uri(reverse("citizen-survey"))
    home_url = request.build_absolute_uri("/")
    return {
        "@context": "https://schema.org",
        "@type": "BreadcrumbList",
        "itemListElement": [
            {
                "@type": "ListItem",
                "position": 1,
                "name": "Home",
                "item": home_url,
            },
            {
                "@type": "ListItem",
                "position": 2,
                "name": "Weekly Survey",
                "item": survey_url,
            },
        ],
    }


def _build_active_card_context(
    participant,
    *,
    active_question: Optional[Any] = None,
    allow_repeat_submission: bool = False,
    force_show_results: bool = False,
) -> Dict[str, Any]:
    if active_question is None:
        active_question = survey_service.get_active_question()
    participant_response = None
    active_results = None
    if active_question:
        participant_response = survey_service.get_participant_response(
            question=active_question,
            participant=participant,
        )
        if participant_response or force_show_results:
            active_results = survey_service.summarize_question_results(active_question)
            active_results["chart_json"] = json.dumps(active_results["chart"])
    show_active_results = bool(active_results) and (not allow_repeat_submission or force_show_results)
    show_question_form = bool(active_question) and (
        participant_response is None or (allow_repeat_submission and not force_show_results)
    )
    return {
        "active_question": active_question,
        "participant_response": participant_response,
        "show_question_form": show_question_form,
        "show_active_results": show_active_results,
        "active_results": active_results,
        "allow_repeat_submission": allow_repeat_submission,
        "survey_step": "question",
        "city_choices": [{"slug": slug, "label": label} for slug, label in survey_service.CITY_CHOICES],
    }


@require_GET
def citizen_survey(request: HttpRequest) -> HttpResponse:
    participant, signed_cookie_value, _ = survey_service.resolve_or_create_participant(
        request.COOKIES.get(survey_service.PARTICIPANT_COOKIE_NAME, "")
    )
    allow_repeat_submission = bool(getattr(request.user, "is_staff", False))

    active_card_context = _build_active_card_context(
        participant,
        allow_repeat_submission=allow_repeat_submission,
    )
    active_question = active_card_context["active_question"]

    history_questions = survey_service.get_recent_closed_questions(active_question=active_question, limit=8)
    history_results = [survey_service.summarize_question_results(question) for question in history_questions]
    for history_result in history_results:
        history_result["chart_json"] = json.dumps(history_result["chart"])

    topic_choices = [{"slug": slug, "label": label} for slug, label in survey_service.CIVIC_TOPIC_CHOICES]

    context = _basic_page_context(SURVEY_PAGE_TITLE, SURVEY_META_DESCRIPTION)
    canonical_url = request.build_absolute_uri(reverse("citizen-survey"))
    context.update(
        {
            "canonical_url": canonical_url,
            "og_url": canonical_url,
            "og_title": "Weekly Citizen Survey · OpenSkagit",
            "twitter_title": "Weekly Citizen Survey · OpenSkagit",
            "meta_robots": "index,follow",
            "survey_json_ld": json.dumps(_question_json_ld(request)),
            "survey_breadcrumb_json_ld": json.dumps(_breadcrumb_json_ld(request)),
            "history_results": history_results,
            "topic_choices": topic_choices,
            "selected_topic_interests": set(participant.civic_topic_interests or []),
            "has_reminder_popup": True,
        }
    )
    context.update(active_card_context)
    response = render(request, "openskagit/citizen_survey.html", context)
    _set_participant_cookie(request, response, signed_cookie_value)
    return response


@require_POST
def survey_response(request: HttpRequest) -> HttpResponse:
    participant, signed_cookie_value, _ = survey_service.resolve_or_create_participant(
        request.COOKIES.get(survey_service.PARTICIPANT_COOKIE_NAME, "")
    )
    is_htmx = _is_htmx_request(request)
    allow_repeat_submission = bool(getattr(request.user, "is_staff", False))
    active_question = survey_service.get_active_question()
    if not active_question:
        if is_htmx:
            card_context = _build_active_card_context(
                participant,
                active_question=active_question,
                allow_repeat_submission=allow_repeat_submission,
            )
            card_context["survey_error_message"] = "No active weekly survey question is available right now."
            response = render(request, "openskagit/partials/citizen_survey_current_card.html", card_context)
            _set_participant_cookie(request, response, signed_cookie_value)
            return response
        messages.error(request, "No active weekly survey question is available right now.")
        response = redirect("citizen-survey")
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    question_id = (request.POST.get("question_id") or "").strip()
    option_id = (request.POST.get("option_id") or "").strip()
    comment = (request.POST.get("comment") or "").strip()
    step = (request.POST.get("step") or "question").strip().lower()

    if str(active_question.id) != question_id:
        if is_htmx:
            card_context = _build_active_card_context(
                participant,
                active_question=active_question,
                allow_repeat_submission=allow_repeat_submission,
            )
            card_context["survey_error_message"] = "That question is no longer active. Please submit again."
            response = render(request, "openskagit/partials/citizen_survey_current_card.html", card_context)
            _set_participant_cookie(request, response, signed_cookie_value)
            return response
        messages.error(request, "That question is no longer active. Please submit again.")
        response = redirect("citizen-survey")
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    option = survey_service.get_option_for_question(question=active_question, option_id=option_id)
    if option is None:
        if is_htmx:
            card_context = _build_active_card_context(
                participant,
                active_question=active_question,
                allow_repeat_submission=allow_repeat_submission,
            )
            card_context["survey_error_message"] = "Please select one response option."
            response = render(request, "openskagit/partials/citizen_survey_current_card.html", card_context)
            _set_participant_cookie(request, response, signed_cookie_value)
            return response
        messages.error(request, "Please select one response option.")
        response = redirect("citizen-survey")
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    if step != "finalize":
        if is_htmx:
            card_context = _build_active_card_context(
                participant,
                active_question=active_question,
                allow_repeat_submission=allow_repeat_submission,
            )
            card_context.update(
                {
                    "survey_step": "city",
                    "pending_option_id": option.id,
                    "pending_option_label": option.label,
                    "pending_comment": comment,
                    "show_question_form": False,
                    "show_active_results": False,
                }
            )
            response = render(request, "openskagit/partials/citizen_survey_current_card.html", card_context)
            _set_participant_cookie(request, response, signed_cookie_value)
            return response
        messages.error(request, "Please choose your city to finish submitting your response.")
        response = redirect("citizen-survey")
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    focused_city = survey_service.normalize_city_slug(request.POST.get("focused_city") or "")
    if not survey_service.is_valid_city_slug(focused_city):
        if is_htmx:
            card_context = _build_active_card_context(
                participant,
                active_question=active_question,
                allow_repeat_submission=allow_repeat_submission,
            )
            card_context.update(
                {
                    "survey_step": "city",
                    "pending_option_id": option.id,
                    "pending_option_label": option.label,
                    "pending_comment": comment,
                    "show_question_form": False,
                    "show_active_results": False,
                    "survey_error_message": "Please choose a city to finish submitting your response.",
                }
            )
            response = render(request, "openskagit/partials/citizen_survey_current_card.html", card_context)
            _set_participant_cookie(request, response, signed_cookie_value)
            return response
        messages.error(request, "Please choose a city to finish submitting your response.")
        response = redirect("citizen-survey")
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    _, created = survey_service.record_response(
        question=active_question,
        option=option,
        participant=participant,
        comment=comment,
        focused_city=focused_city,
        allow_repeat_submission=allow_repeat_submission,
    )
    if not created and not allow_repeat_submission and not is_htmx:
        messages.info(request, "You already submitted a response for this week’s question.")

    if is_htmx:
        card_context = _build_active_card_context(
            participant,
            active_question=active_question,
            allow_repeat_submission=allow_repeat_submission,
            force_show_results=True,
        )
        response = render(request, "openskagit/partials/citizen_survey_current_card.html", card_context)
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    response = redirect("citizen-survey")
    _set_participant_cookie(request, response, signed_cookie_value)
    return response


@require_POST
def survey_interest_toggle(request: HttpRequest) -> JsonResponse:
    participant, signed_cookie_value, _ = survey_service.resolve_or_create_participant(
        request.COOKIES.get(survey_service.PARTICIPANT_COOKIE_NAME, "")
    )
    payload = _parse_json_body(request)
    source = payload if payload else request.POST

    interest_type = source.get("type")
    slug = source.get("slug")
    selected = _bool_from_payload(source.get("selected"))

    try:
        is_selected = survey_service.update_participant_interest(
            participant=participant,
            interest_type=interest_type,
            slug=slug,
            selected=selected,
        )
    except ValueError as exc:
        response = JsonResponse({"ok": False, "error": str(exc)}, status=400)
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    response = JsonResponse(
        {
            "ok": True,
            "type": str(interest_type or "").strip().lower(),
            "slug": str(slug or "").strip().lower(),
            "selected": is_selected,
        }
    )
    _set_participant_cookie(request, response, signed_cookie_value)
    return response


@require_POST
def survey_reminder_subscribe(request: HttpRequest) -> HttpResponse:
    _participant, signed_cookie_value, _ = survey_service.resolve_or_create_participant(
        request.COOKIES.get(survey_service.PARTICIPANT_COOKIE_NAME, "")
    )
    payload = _parse_json_body(request)
    source = payload if payload else request.POST
    email = (source.get("email") or "").strip()

    if not email:
        if _wants_json_response(request):
            response = JsonResponse({"ok": False, "error": "Email is required."}, status=400)
            _set_participant_cookie(request, response, signed_cookie_value)
            return response
        messages.error(request, "Please enter an email address for reminders.")
        response = redirect("citizen-survey")
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    try:
        validate_email(email)
    except ValidationError:
        if _wants_json_response(request):
            response = JsonResponse({"ok": False, "error": "Please provide a valid email address."}, status=400)
            _set_participant_cookie(request, response, signed_cookie_value)
            return response
        messages.error(request, "Please provide a valid email address.")
        response = redirect("citizen-survey")
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    _, created = survey_service.upsert_reminder(email)
    if _wants_json_response(request):
        response = JsonResponse({"ok": True, "created": created})
        _set_participant_cookie(request, response, signed_cookie_value)
        return response

    if created:
        messages.success(request, "Reminder saved. We’ll send you new weekly survey alerts.")
    else:
        messages.success(request, "You are already subscribed. Reminder details were refreshed.")
    response = redirect("citizen-survey")
    _set_participant_cookie(request, response, signed_cookie_value)
    return response


@require_GET
def survey_reminder_unsubscribe(request: HttpRequest) -> HttpResponse:
    token = (request.GET.get("token") or "").strip()
    unsubscribed, email = survey_service.unsubscribe_reminder_by_token(token)

    context = _basic_page_context(
        "Survey Reminder Unsubscribe | OpenSkagit",
        "Manage your OpenSkagit weekly survey reminder subscription.",
    )
    context.update(
        {
            "unsubscribe_success": unsubscribed,
            "unsubscribe_email": email,
        }
    )
    return render(
        request,
        "openskagit/citizen_survey_unsubscribe.html",
        context,
        status=200 if unsubscribed else 400,
    )
