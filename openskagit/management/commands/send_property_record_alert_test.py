from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.core.mail import EmailMultiAlternatives
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.template.loader import render_to_string
from django.utils import timezone

from openskagit.services import property_record_alerts as alert_service


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = "Send a one-off property recorded-document alert test email."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="Recipient email address.")
        parser.add_argument("--parcel", default="P90623", help="Parcel ID shown in the test message.")
        parser.add_argument("--owner", default="Sample Owner", help="Owner name shown in the test message.")
        parser.add_argument("--address", default="123 Main St", help="Address shown in the test message.")
        parser.add_argument(
            "--document-type",
            default="QUITCLAIM DEED",
            help="Document type shown in the test message.",
        )
        parser.add_argument(
            "--recording-number",
            default="",
            help="Recording number shown in the test message. Auto-generated if omitted.",
        )
        parser.add_argument(
            "--recorded-date",
            default="",
            help="Recorded date in YYYY-MM-DD format. Defaults to today.",
        )
        parser.add_argument(
            "--document-url",
            default="",
            help="Document/source URL used in the test message.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Render/log payload but do not send email.",
        )
        parser.add_argument(
            "--live-template",
            action="store_true",
            help="Send using the real triggered-alert email template.",
        )

    def handle(self, *args, **options):
        recipient_raw = str(options.get("email") or "").strip()
        recipient = alert_service.normalize_email(recipient_raw)
        if not recipient:
            raise CommandError("--email is required.")
        try:
            validate_email(recipient)
        except ValidationError as exc:
            raise CommandError(f"Invalid recipient email: {recipient}") from exc

        now = timezone.now()
        parcel_id = alert_service.normalize_parcel_id(options.get("parcel") or "") or "P90623"
        owner_name = str(options.get("owner") or "").strip() or "Sample Owner"
        situs_address = str(options.get("address") or "").strip() or "123 Main St"
        document_type = str(options.get("document_type") or "").strip() or "QUITCLAIM DEED"

        recording_number = str(options.get("recording_number") or "").strip()
        if not recording_number:
            recording_number = f"TEST-{now:%Y%m%d%H%M%S}"

        recorded_date = str(options.get("recorded_date") or "").strip() or now.date().isoformat()
        default_doc_url = f"{settings.SITE_URL.rstrip('/')}/alert/"
        document_url = str(options.get("document_url") or "").strip() or default_doc_url

        context = {
            "recipient_email": recipient,
            "parcel_id": parcel_id,
            "owner_name": owner_name,
            "situs_address": situs_address,
            "document_type": document_type,
            "recording_number": recording_number,
            "recorded_date": recorded_date,
            "document_url": document_url,
            "generated_at": now,
        }

        use_live_template = bool(options.get("live_template"))
        if use_live_template:
            parcel_alerts = [
                {
                    "parcel_id": parcel_id,
                    "owner_name": owner_name,
                    "situs_address": situs_address,
                    "manage_url": f"{settings.SITE_URL.rstrip('/')}/alert/",
                    "delete_url": f"{settings.SITE_URL.rstrip('/')}/alert/",
                    "unsubscribe_url": f"{settings.SITE_URL.rstrip('/')}/alert/",
                    "documents": [
                        {
                            "document_type": document_type,
                            "recording_number": recording_number,
                            "recorded_date": recorded_date,
                            "grantor": "Sample Grantor",
                            "grantee": "Sample Grantee",
                            "filer": "Sample Filer",
                            "comment": "",
                            "document_url": document_url,
                            "source_url": document_url,
                            "parcel_id": parcel_id,
                        }
                    ],
                }
            ]
            subject = f"OpenSkagit parcel record alert test: {parcel_id}"
            text_body = ""
            html_body = ""
        else:
            subject = f"OpenSkagit parcel record alert test: {parcel_id}"
            text_body = render_to_string("openskagit/emails/property_record_alert_test.txt", context)
            html_body = render_to_string("openskagit/emails/property_record_alert_test.html", context)

        if options.get("dry_run"):
            self.stdout.write(self.style.WARNING("DRY RUN: test email was not sent."))
            self.stdout.write(f"Recipient: {recipient}")
            self.stdout.write(f"Subject: {subject}")
            self.stdout.write(f"Parcel: {parcel_id}")
            self.stdout.write(f"Recording #: {recording_number}")
            if use_live_template:
                self.stdout.write("Template: live triggered-alert template")
            else:
                self.stdout.write("Template: dedicated test template")
            return

        if use_live_template:
            sent_count = alert_service.send_property_record_alert_digest(
                email=recipient,
                parcel_alerts=parcel_alerts,
                from_email=settings.DEFAULT_FROM_EMAIL,
            )
        else:
            message = EmailMultiAlternatives(
                subject=subject,
                body=text_body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[recipient],
            )
            message.attach_alternative(html_body, "text/html")
            sent_count = message.send()
        if sent_count <= 0:
            raise CommandError("Email backend did not send a message.")

        self.stdout.write(self.style.SUCCESS(f"Sent test property record alert email to {recipient}."))
