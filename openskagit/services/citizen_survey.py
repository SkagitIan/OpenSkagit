from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from openskagit.models import (
    CitizenSurveyOption,
    CitizenSurveyParticipant,
    CitizenSurveyQuestion,
    CitizenSurveyReminder,
    CitizenSurveyReminderSend,
    CitizenSurveyResponse,
)


SURVEY_TIMEZONE = ZoneInfo("America/Los_Angeles")
PARTICIPANT_COOKIE_NAME = "os_survey_pid"
PARTICIPANT_COOKIE_MAX_AGE = 60 * 60 * 24 * 365
PARTICIPANT_COOKIE_SALT = "os-citizen-survey-participant"
REMINDER_UNSUBSCRIBE_SALT = "os-citizen-survey-reminder-unsubscribe"
REMINDER_UNSUBSCRIBE_MAX_AGE = 60 * 60 * 24 * 365 * 5

logger = logging.getLogger(__name__)

CIVIC_TOPIC_CHOICES: List[Tuple[str, str]] = [
    ("schools", "Schools"),
    ("budget", "Budget"),
    ("recreation", "Recreation"),
    ("housing", "Housing"),
    ("public-safety", "Public Safety"),
    ("transportation", "Transportation"),
    ("environment", "Environment"),
    ("small-business", "Small Business"),
]

CITY_CHOICES: List[Tuple[str, str]] = [
    ("sedro-woolley", "Sedro-Woolley"),
    ("mount-vernon", "Mount Vernon"),
    ("burlington", "Burlington"),
    ("anacortes", "Anacortes"),
    ("la-conner", "La Conner"),
    ("concrete", "Concrete"),
]
CITY_LABEL_BY_SLUG = {slug: label for slug, label in CITY_CHOICES}

CHART_COLORS = [
    "#0f766e",
    "#0f9a91",
    "#6ea8aa",
    "#94a3b8",
    "#d1d5db",
]


def pacific_now(now: Optional[datetime] = None) -> datetime:
    if now is None:
        now = timezone.now()
    if timezone.is_naive(now):
        now = timezone.make_aware(now, timezone.utc)
    return now.astimezone(SURVEY_TIMEZONE)


def current_week_start_date(now: Optional[datetime] = None) -> date:
    local_now = pacific_now(now)
    days_since_sunday = (local_now.weekday() + 1) % 7
    return local_now.date() - timedelta(days=days_since_sunday)


def get_active_question(now: Optional[datetime] = None) -> Optional[CitizenSurveyQuestion]:
    week_start = current_week_start_date(now)
    return (
        CitizenSurveyQuestion.objects.filter(is_published=True, week_start_date=week_start)
        .prefetch_related("options")
        .first()
    )


def get_recent_closed_questions(
    *,
    active_question: Optional[CitizenSurveyQuestion],
    now: Optional[datetime] = None,
    limit: int = 8,
) -> List[CitizenSurveyQuestion]:
    queryset = CitizenSurveyQuestion.objects.filter(is_published=True)
    if active_question:
        queryset = queryset.filter(week_start_date__lt=active_question.week_start_date)
    else:
        queryset = queryset.filter(week_start_date__lt=current_week_start_date(now))
    return list(queryset.prefetch_related("options").order_by("-week_start_date")[:limit])


def _normalize_interest_list(values: Sequence[str], allowed: Sequence[Tuple[str, str]]) -> List[str]:
    allowed_slugs = {slug for slug, _ in allowed}
    normalized: List[str] = []
    seen = set()
    for value in values or []:
        slug = str(value or "").strip().lower()
        if slug and slug in allowed_slugs and slug not in seen:
            normalized.append(slug)
            seen.add(slug)
    return normalized


def _participant_signer() -> TimestampSigner:
    return TimestampSigner(salt=PARTICIPANT_COOKIE_SALT)


def _normalize_email(value: str) -> str:
    return str(value or "").strip().lower()


def sign_participant_cookie_value(participant_id: uuid.UUID) -> str:
    return _participant_signer().sign(str(participant_id))


def unsign_participant_cookie_value(cookie_value: str) -> Optional[uuid.UUID]:
    if not cookie_value:
        return None
    signer = _participant_signer()
    try:
        raw_value = signer.unsign(cookie_value, max_age=PARTICIPANT_COOKIE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    try:
        return uuid.UUID(str(raw_value))
    except (TypeError, ValueError, AttributeError):
        return None


def resolve_or_create_participant(
    cookie_value: str,
) -> Tuple[CitizenSurveyParticipant, str, bool]:
    participant_id = unsign_participant_cookie_value(cookie_value)
    if participant_id is not None:
        participant, _ = CitizenSurveyParticipant.objects.get_or_create(participant_id=participant_id)
        return participant, sign_participant_cookie_value(participant.participant_id), False

    participant = CitizenSurveyParticipant.objects.create()
    return participant, sign_participant_cookie_value(participant.participant_id), True


def get_participant_response(
    *,
    question: CitizenSurveyQuestion,
    participant: CitizenSurveyParticipant,
) -> Optional[CitizenSurveyResponse]:
    return (
        CitizenSurveyResponse.objects.filter(question=question, participant=participant)
        .select_related("option")
        .first()
    )


def get_option_for_question(*, question: CitizenSurveyQuestion, option_id: Any) -> Optional[CitizenSurveyOption]:
    try:
        option_pk = int(option_id)
    except (TypeError, ValueError):
        return None
    return CitizenSurveyOption.objects.filter(question=question, id=option_pk).first()


def normalize_city_slug(value: str) -> str:
    return str(value or "").strip().lower()


def is_valid_city_slug(value: str) -> bool:
    return normalize_city_slug(value) in CITY_LABEL_BY_SLUG


def city_label_from_slug(value: str) -> str:
    return CITY_LABEL_BY_SLUG.get(normalize_city_slug(value), "")


def record_response(
    *,
    question: CitizenSurveyQuestion,
    option: CitizenSurveyOption,
    participant: CitizenSurveyParticipant,
    comment: str = "",
    focused_city: str = "",
    allow_repeat_submission: bool = False,
) -> Tuple[CitizenSurveyResponse, bool]:
    trimmed_comment = (comment or "").strip()
    normalized_city = normalize_city_slug(focused_city)
    if not is_valid_city_slug(normalized_city):
        raise ValueError("Please choose a valid city.")

    if allow_repeat_submission:
        response = CitizenSurveyResponse.objects.create(
            question=question,
            option=option,
            participant=participant,
            comment=trimmed_comment,
            focused_city=normalized_city,
            is_staff_debug=True,
        )
        return response, True

    try:
        with transaction.atomic():
            response, created = CitizenSurveyResponse.objects.get_or_create(
                question=question,
                participant=participant,
                defaults={
                    "option": option,
                    "comment": trimmed_comment,
                    "focused_city": normalized_city,
                    "is_staff_debug": False,
                },
            )
    except IntegrityError:
        response = get_participant_response(question=question, participant=participant)
        if response is None:
            raise
        return response, False
    return response, created


def summarize_question_results(question: CitizenSurveyQuestion) -> Dict[str, Any]:
    options = list(question.options.order_by("sort_order", "id"))
    counts_by_option = {
        row["option_id"]: row["count"]
        for row in CitizenSurveyResponse.objects.filter(question=question)
        .values("option_id")
        .annotate(count=Count("id"))
    }
    total = sum(counts_by_option.values())

    rows: List[Dict[str, Any]] = []
    labels: List[str] = []
    values: List[int] = []
    for index, option in enumerate(options):
        count = int(counts_by_option.get(option.id, 0))
        percentage = round((count / total) * 100, 1) if total else 0.0
        labels.append(option.label)
        values.append(count)
        rows.append(
            {
                "option_id": option.id,
                "label": option.label,
                "count": count,
                "percentage": percentage,
                "color": CHART_COLORS[index % len(CHART_COLORS)],
            }
        )

    return {
        "question_id": question.id,
        "week_start_date": question.week_start_date,
        "prompt": question.prompt,
        "total_responses": total,
        "rows": rows,
        "chart": {
            "labels": labels,
            "values": values,
            "colors": [row["color"] for row in rows],
            "option_ids": [row["option_id"] for row in rows],
        },
    }


def update_participant_interest(
    *,
    participant: CitizenSurveyParticipant,
    interest_type: str,
    slug: str,
    selected: bool,
) -> bool:
    normalized_type = str(interest_type or "").strip().lower()
    normalized_slug = str(slug or "").strip().lower()

    if normalized_type == "topic":
        allowed = CIVIC_TOPIC_CHOICES
        existing_values = _normalize_interest_list(participant.civic_topic_interests or [], allowed)
        field_name = "civic_topic_interests"
    elif normalized_type == "city":
        allowed = CITY_CHOICES
        existing_values = _normalize_interest_list(participant.city_interests or [], allowed)
        field_name = "city_interests"
    else:
        raise ValueError("Invalid interest type.")

    allowed_slugs = {item_slug for item_slug, _ in allowed}
    if normalized_slug not in allowed_slugs:
        raise ValueError("Invalid interest slug.")

    values_set = set(existing_values)
    if selected:
        values_set.add(normalized_slug)
    else:
        values_set.discard(normalized_slug)
    updated_values = sorted(values_set)

    setattr(participant, field_name, updated_values)
    participant.save(update_fields=[field_name, "updated_at"])
    return normalized_slug in updated_values


def upsert_reminder(email: str) -> Tuple[CitizenSurveyReminder, bool]:
    normalized = _normalize_email(email)
    reminder, created = CitizenSurveyReminder.objects.get_or_create(email=normalized)
    if not created:
        reminder.save(update_fields=["updated_at"])
    return reminder, created


def _reminder_unsubscribe_signer() -> TimestampSigner:
    return TimestampSigner(salt=REMINDER_UNSUBSCRIBE_SALT)


def sign_reminder_unsubscribe_token(email: str) -> str:
    normalized = _normalize_email(email)
    if not normalized:
        return ""
    return _reminder_unsubscribe_signer().sign(normalized)


def unsign_reminder_unsubscribe_token(token: str) -> Optional[str]:
    if not token:
        return None
    try:
        raw_value = _reminder_unsubscribe_signer().unsign(token, max_age=REMINDER_UNSUBSCRIBE_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    normalized = _normalize_email(str(raw_value))
    return normalized or None


def site_base_url() -> str:
    return str(getattr(settings, "SITE_URL", "") or "").strip().rstrip("/")


def survey_page_url() -> str:
    path = reverse("citizen-survey")
    base = site_base_url()
    return f"{base}{path}" if base else path


def reminder_unsubscribe_url(email: str) -> str:
    token = sign_reminder_unsubscribe_token(email)
    if not token:
        return ""
    path = reverse("citizen-survey-reminder-unsubscribe")
    query = f"?token={quote(token)}"
    base = site_base_url()
    return f"{base}{path}{query}" if base else f"{path}{query}"


def unsubscribe_reminder_by_token(token: str) -> Tuple[bool, Optional[str]]:
    email = unsign_reminder_unsubscribe_token(token)
    if not email:
        return False, None
    CitizenSurveyReminder.objects.filter(email=email).delete()
    return True, email


def send_new_question_notification(
    *,
    reminder: CitizenSurveyReminder,
    question: CitizenSurveyQuestion,
    from_email: Optional[str] = None,
) -> bool:
    recipient = _normalize_email(reminder.email)
    if not recipient:
        return False

    survey_url = survey_page_url()
    unsubscribe_url = reminder_unsubscribe_url(recipient)
    context = {
        "recipient_email": recipient,
        "question_prompt": question.prompt,
        "week_start_date": question.week_start_date,
        "survey_url": survey_url,
        "unsubscribe_url": unsubscribe_url,
        "site_url": site_base_url() or survey_url,
    }
    subject = f"New weekly survey is live: Week of {question.week_start_date:%b %d}"
    text_body = render_to_string("openskagit/emails/citizen_survey_new_question_notification.txt", context)
    html_body = render_to_string("openskagit/emails/citizen_survey_new_question_notification.html", context)

    headers = {"Auto-Submitted": "auto-generated"}
    if unsubscribe_url:
        headers["List-Unsubscribe"] = f"<{unsubscribe_url}>"
    message = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=from_email or settings.DEFAULT_FROM_EMAIL,
        to=[recipient],
        headers=headers,
    )
    message.attach_alternative(html_body, "text/html")
    try:
        message.send()
    except Exception:
        logger.exception(
            "Citizen survey reminder email failed for question_id=%s recipient=%s",
            question.id,
            recipient,
        )
        return False
    return True
