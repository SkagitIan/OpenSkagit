import logging
from typing import Iterable, List, Optional, Sequence, Union

from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.core.signing import TimestampSigner
from django.template.loader import render_to_string
from django.urls import reverse

from .models import (
    WeeklyBriefingSection,
    WeeklyBriefingSendLog,
    WeeklyBriefingSubscriber,
    WeeklyBriefingTemplate,
)

logger = logging.getLogger(__name__)

PREVIEW_UNSUBSCRIBE_TOKEN = "preview-dummy-token"


def _build_sections(template: WeeklyBriefingTemplate) -> List[WeeklyBriefingSection]:
    sections = list(template.sections.all())
    return sections


def build_briefing_context(
    template: WeeklyBriefingTemplate,
    sections: List[WeeklyBriefingSection],
    unsubscribe_url: str,
) -> dict:
    base_url = settings.SITE_URL.rstrip("/")
    return {
        "template": template,
        "sections": sections,
        "cta_url": template.cta_url or f"{base_url}/",
        "site_url": base_url,
        "unsubscribe_url": unsubscribe_url,
    }


def render_weekly_briefing(template: WeeklyBriefingTemplate, unsubscribe_url: str) -> dict:
    sections = _build_sections(template)
    context = build_briefing_context(template, sections, unsubscribe_url)
    return {
        "context": context,
        "html": render_to_string("openskagit/emails/weekly_briefing.html", context),
        "text": render_to_string("openskagit/emails/weekly_briefing.txt", context),
    }


def _sign_email(email: str, signer: TimestampSigner) -> str:
    return signer.sign(email.lower())


def _recipient_email(recipient: Union[str, WeeklyBriefingSubscriber]) -> str:
    if isinstance(recipient, WeeklyBriefingSubscriber):
        return recipient.email
    return str(recipient)


def _recipient_token(recipient: Union[str, WeeklyBriefingSubscriber], signer: TimestampSigner) -> str:
    if isinstance(recipient, WeeklyBriefingSubscriber):
        return recipient.unsubscribe_token()
    return _sign_email(str(recipient), signer)


def send_weekly_briefing(
    recipients: Optional[Iterable[Union[str, WeeklyBriefingSubscriber]]] = None,
) -> WeeklyBriefingSendLog:
    template = WeeklyBriefingTemplate.objects.order_by("-updated_at").first()
    if not template:
        raise ValueError("No weekly briefing template exists yet.")
    sections = _build_sections(template)
    if not sections:
        raise ValueError("The weekly briefing needs at least one section.")

    if recipients is None:
        subscribers = list(WeeklyBriefingSubscriber.objects.all())
    else:
        subscribers = list(recipients)
    if not subscribers:
        raise ValueError("No subscribers found for the weekly briefing.")

    sent_count = 0
    errors = []
    signer = TimestampSigner()

    logger.info(
        "Dispatching weekly briefing '%s' to %d recipients", template.subject, len(subscribers)
    )

    for subscriber in subscribers:
        email = _recipient_email(subscriber)
        unsubscribe_url = (
            f"{settings.SITE_URL.rstrip('/')}{reverse('newsletter-unsubscribe', args=[_recipient_token(subscriber, signer)])}"
        )
        payload = render_weekly_briefing(template, unsubscribe_url)
        message = EmailMultiAlternatives(
            subject=template.subject,
            body=payload["text"],
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[email],
        )
        message.attach_alternative(payload["html"], "text/html")
        try:
            message.send()
            sent_count += 1
        except Exception as exc:  # pragma: no cover - difficulty reproducing send failure
            errors.append(f"{subscriber.email}: {exc}")
            logger.exception("Failed to send weekly briefing to %s", subscriber.email)

    log = WeeklyBriefingSendLog.objects.create(
        subject=template.subject,
        sent_count=sent_count,
        error_count=len(errors),
        error_snapshot="\n".join(errors[:20]),
    )

    if errors:
        logger.warning("Weekly briefing had %d send errors", len(errors))

    return log


def preview_briefing_context(template: WeeklyBriefingTemplate) -> dict:
    preview_url = f"{settings.SITE_URL.rstrip('/')}{reverse('newsletter-unsubscribe', args=[PREVIEW_UNSUBSCRIBE_TOKEN])}"
    return render_weekly_briefing(template, preview_url)["context"]
