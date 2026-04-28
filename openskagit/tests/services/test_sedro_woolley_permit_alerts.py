import os
from types import SimpleNamespace

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.core import mail
from django.test import SimpleTestCase, override_settings
from django.utils import timezone

from openskagit.services.sedro_woolley_permit_alerts import (
    PermitAlertPayload,
    build_permit_alert_payload,
    is_alert_permit_type,
    parse_recipients,
    send_permit_alert_email,
)


class SedroWoolleyPermitAlertsServiceTests(SimpleTestCase):
    def test_parse_recipients_dedupes_and_splits(self):
        recipients = parse_recipients(
            [
                "A@example.com, b@example.com",
                "b@example.com ; c@example.com",
                "",
                "not-an-email",
            ]
        )
        self.assertEqual(recipients, ["a@example.com", "b@example.com", "c@example.com"])

    def test_is_alert_permit_type_uses_alert_allowlist(self):
        self.assertTrue(is_alert_permit_type("Demolition"))
        self.assertTrue(is_alert_permit_type("Demolision"))
        self.assertTrue(is_alert_permit_type("Residential Roof"))
        self.assertTrue(is_alert_permit_type("Building-Residential"))
        self.assertTrue(is_alert_permit_type("Building-Commercial"))
        self.assertTrue(is_alert_permit_type("Residential/Commercial"))
        self.assertTrue(is_alert_permit_type("Building-Residential & Commercial"))

        self.assertFalse(is_alert_permit_type("Mechanical & Plumbing"))
        self.assertFalse(is_alert_permit_type("Residential Mechanical & Plumbing"))
        self.assertFalse(is_alert_permit_type("Clear and Grade"))

    @override_settings(SITE_URL="https://openskagit.com")
    def test_build_permit_alert_payload_renders_subject_and_body(self):
        permit = SimpleNamespace(
            external_id="123",
            permit_number="2026001",
            permit_type="Building-Residential",
            permit_date=None,
            site_address="123 Main St",
            parcel_id="P12345678901",
            status="Issued",
            work_description="Deck addition",
            detail_url="https://example.com/permit/123",
        )
        payload = build_permit_alert_payload(
            [permit],
            watermark_from=None,
            watermark_to=timezone.now(),
        )
        self.assertIn("1 new important permit", payload.subject)
        self.assertIn("2026001", payload.text)
        self.assertIn("123 Main St", payload.html)
        self.assertIn("Deck addition", payload.text)
        self.assertIn("P12345678901", payload.html)

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="alerts@test.local",
    )
    def test_send_permit_alert_email_sends_message(self):
        payload = PermitAlertPayload(
            subject="Sedro-Woolley permits: test alert",
            text="Test alert body",
            html="<p>Test alert body</p>",
            permit_count=1,
        )
        sent = send_permit_alert_email(
            recipients=["first@example.com", "second@example.com"],
            payload=payload,
        )

        self.assertEqual(sent, 2)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, payload.subject)
        self.assertEqual(message.to, ["first@example.com", "second@example.com"])
