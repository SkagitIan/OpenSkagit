import json
import datetime as dt
from io import StringIO
from unittest.mock import patch

from django.core import mail
from django.core.management import call_command
from django.test import SimpleTestCase, TestCase, override_settings

from openskagit import parcelalert as alert_service
from openskagit.models import (
    MasterParcel,
    ParcelHistory,
    PropertyRecordAlertSubscription,
    WeeklyBriefingSubscriber,
)


def _recording_doc(
    recording_number: str,
    recorded_date: str,
    document_type: str = "DEED",
    parcel_id: str = "P90001",
) -> dict:
    return {
        "recording_number": recording_number,
        "recorded_date": recorded_date,
        "document_type": document_type,
        "grantor": "Grantor Name",
        "grantee": "Grantee Name",
        "filer": "Filer Name",
        "comment": "",
        "legal": "Legal",
        "parcel_id": parcel_id,
        "xref_id": "xref",
        "document_url": f"https://example.com/{recording_number}.pdf",
        "source_url": "https://www.skagitcounty.net/Search/Recording/results.aspx?PA=P90001",
        "fetched_at": "2026-03-20T00:00:00+00:00",
    }


class PropertyRecordAlertServiceTests(SimpleTestCase):
    def test_parse_recording_results_html_extracts_normalized_rows(self):
        html = """
        <table class="resultTable">
          <tbody>
            <tr>
              <td></td>
              <td></td>
              <td><a href="/AuditorRecording/Documents/RecordedDocuments/2026/01/30/202601300001.pdf">Doc</a></td>
              <td class="centercell">202601300001<br/>01/30/2026<br/>QUITCLAIM DEED</td>
              <td class="centercell">ALPHA LLC</td>
              <td class="centercell">BETA LLC</td>
              <td class="centercell">TITLE COMPANY</td>
              <td class="centercell">-</td>
              <td>LEGAL TEXT</td>
              <td class="centercell">P90001<br/>1234-000-000-0000</td>
            </tr>
          </tbody>
        </table>
        """

        documents = alert_service.parse_recording_results_html(
            html,
            source_url="https://www.skagitcounty.net/Search/Recording/results.aspx?PA=P90001&SC=DateRecorded&SO=DESC",
            parcel_id="P90001",
        )
        self.assertEqual(len(documents), 1)
        document = documents[0]
        self.assertEqual(document["recording_number"], "202601300001")
        self.assertEqual(document["recorded_date"], "2026-01-30")
        self.assertEqual(document["document_type"], "QUITCLAIM DEED")
        self.assertEqual(document["parcel_id"], "P90001")
        self.assertIn("202601300001.pdf", document["document_url"])

    def test_is_high_signal_document_type(self):
        self.assertTrue(alert_service.is_high_signal_document_type("Deed of Trust"))
        self.assertTrue(alert_service.is_high_signal_document_type("Quitclaim Deed"))
        self.assertTrue(alert_service.is_high_signal_document_type("Construction Lien"))
        self.assertTrue(alert_service.is_high_signal_document_type("Release of Lien"))
        self.assertTrue(alert_service.is_high_signal_document_type("Power of Attorney"))
        self.assertFalse(alert_service.is_high_signal_document_type("Miscellaneous Filing"))

    def test_evaluate_document_risk_detects_fuzzy_and_high_priority(self):
        parcel = MasterParcel(parcel_number="P90001", situs_address="100 Main St")
        subscription = PropertyRecordAlertSubscription(
            email="person@example.com",
            parcel=parcel,
            baseline_owner_name="LARSON FAMILY TRUST",
            monitored_names=["LARSON FAMILY TRUST"],
            baseline_situs_address="100 Main St",
        )
        document = _recording_doc(
            recording_number="202601300099",
            recorded_date="2026-01-30",
            document_type="QUITCLAIM DEED",
            parcel_id="P90001",
        )
        document["grantor"] = "LARSEN FAMILY TRUST"
        risk = alert_service.evaluate_document_risk(
            subscription=subscription,
            document=document,
            recent_documents=[document],
        )
        self.assertTrue(risk["is_high_priority"])
        self.assertGreaterEqual(risk["risk_score"], 60)
        self.assertTrue(alert_service.should_trigger_document_alert(risk))

    @patch(
        "openskagit.parcelalert.fetch_assessor_baseline_fallback",
        return_value={"owner_name": "Fallback Owner", "situs_address": "Fallback Address", "source": "db"},
    )
    @patch(
        "openskagit.parcelalert.fetch_assessor_baseline_live",
        return_value={"owner_name": "Live Owner", "situs_address": "Live Address", "source": "live"},
    )
    def test_resolve_assessor_baseline_prefers_live(self, _live_mock, _fallback_mock):
        baseline = alert_service.resolve_assessor_baseline("P90001")
        self.assertEqual(baseline["owner_name"], "Live Owner")
        self.assertEqual(baseline["situs_address"], "Live Address")
        self.assertEqual(baseline["source"], "live")

    @patch(
        "openskagit.parcelalert.fetch_assessor_baseline_fallback",
        return_value={"owner_name": "Fallback Owner", "situs_address": "Fallback Address", "source": "db"},
    )
    @patch(
        "openskagit.parcelalert.fetch_assessor_baseline_live",
        side_effect=RuntimeError("live failed"),
    )
    def test_resolve_assessor_baseline_uses_fallback_on_live_error(self, _live_mock, _fallback_mock):
        baseline = alert_service.resolve_assessor_baseline("P90001")
        self.assertEqual(baseline["owner_name"], "Fallback Owner")
        self.assertEqual(baseline["situs_address"], "Fallback Address")

    @override_settings(SITE_URL="https://openskagit.com")
    def test_digest_payload_contains_facts_and_unsubscribe_links(self):
        payload = alert_service.build_property_record_alert_digest_payload(
            email="person@example.com",
            parcel_alerts=[
                {
                    "parcel_id": "P90001",
                    "owner_name": "Owner Name",
                    "situs_address": "100 Main St",
                    "unsubscribe_url": "https://openskagit.com/alert/unsubscribe/token/",
                    "manage_url": "https://openskagit.com/alert/manage/token/",
                    "delete_url": "https://openskagit.com/alert/delete/token/",
                    "documents": [
                        _recording_doc(
                            recording_number="202601300001",
                            recorded_date="2026-01-30",
                            document_type="DEED",
                        )
                    ],
                }
            ],
        )
        self.assertIn("202601300001", payload.text)
        self.assertIn("Edit alert details", payload.text)
        self.assertIn("https://openskagit.com/alert/manage/token/", payload.text)
        self.assertIn("https://openskagit.com/alert/delete/token/", payload.text)
        self.assertIn("DEED", payload.html)

    @override_settings(SITE_URL="https://openskagit.com")
    def test_signup_confirmation_payload_contains_manage_and_document_links(self):
        payload = alert_service.build_property_record_alert_signup_payload(
            email="person@example.com",
            parcel_subscriptions=[
                {
                    "parcel_id": "P90001",
                    "owner_name": "Owner Name",
                    "situs_address": "100 Main St",
                    "manage_url": "https://openskagit.com/alert/manage/token/",
                    "delete_url": "https://openskagit.com/alert/delete/token/",
                    "recording_results_url": "https://www.skagitcounty.net/Search/Recording/results.aspx?PA=P90001&SC=DateRecorded&SO=DESC",
                    "latest_document_url": "https://www.skagitcounty.net/AuditorRecording/Documents/RecordedDocuments/2026/01/30/202601300001.pdf",
                    "baseline_recording_number": "202601300001",
                    "is_active": True,
                }
            ],
        )
        self.assertIn("Manage this alert", payload.text)
        self.assertIn("https://openskagit.com/alert/manage/token/", payload.text)
        self.assertIn("Latest recorded document link", payload.text)
        self.assertIn("202601300001.pdf", payload.text)
        self.assertIn("Edit alert details", payload.html)
        self.assertIn("Delete this alert", payload.html)


class PropertyRecordAlertViewTests(TestCase):
    def setUp(self):
        self.parcel = MasterParcel.objects.create(parcel_number="P90001", situs_address="100 Main St")
        self.second_parcel = MasterParcel.objects.create(parcel_number="P90002", situs_address="200 Main St")
        ParcelHistory.objects.create(
            parcel_number="P90001",
            rows=[],
            taxes={},
            recording_documents=[_recording_doc("202601300001", "2026-01-30", "DEED", "P90001")],
            recording_latest_number="202601300001",
            recording_latest_recorded_date=dt.date(2026, 1, 30),
        )

    def test_alert_page_has_core_seo_markup(self):
        response = self.client.get("/alert/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "<title>Skagit County Parcel Alerts | Recorded Document Email Notifications | OpenSkagit</title>",
            html=True,
        )
        self.assertContains(response, "Skagit County Parcel Recorded Document Alerts")
        self.assertContains(response, "Find your parcel and start monitoring")
        self.assertContains(response, "Frequently asked questions")
        self.assertContains(response, '<meta name="keywords"', html=False)
        self.assertContains(response, '"@type": "FAQPage"', html=False)

    def test_subscribe_creates_subscription(self):
        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "Person@Example.com",
                    "parcel_id": "P90001",
                    "parcel_contexts": [
                        {
                            "parcel_id": "P90001",
                            "owner_name": "Owner Name",
                            "situs_address": "100 Main St",
                        }
                    ],
                    "subscribe_weekly_briefing": True,
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["created"])
        self.assertFalse(payload["reactivated"])

        subscription = PropertyRecordAlertSubscription.objects.get(
            email="person@example.com",
            parcel_id="P90001",
        )
        self.assertTrue(subscription.is_active)
        self.assertEqual(subscription.baseline_owner_name, "Owner Name")
        self.assertEqual(subscription.baseline_recording_number, "202601300001")
        self.assertEqual(subscription.last_notified_recording_number, "202601300001")
        self.assertTrue(
            WeeklyBriefingSubscriber.objects.filter(email="person@example.com").exists()
        )

    def test_subscribe_skips_weekly_briefing_when_opted_out(self):
        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "person@example.com",
                    "parcel_id": "P90001",
                    "subscribe_weekly_briefing": False,
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(
            WeeklyBriefingSubscriber.objects.filter(email="person@example.com").exists()
        )

    def test_subscribe_duplicate_and_reactivate(self):
        first_response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "person@example.com",
                    "parcel_id": "P90001",
                    "subscribe_weekly_briefing": False,
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(first_response.status_code, 200)

        duplicate_response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "person@example.com",
                    "parcel_id": "P90001",
                    "subscribe_weekly_briefing": True,
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(duplicate_response.status_code, 200)
        duplicate_payload = duplicate_response.json()
        self.assertTrue(duplicate_payload["already_exists"])
        self.assertIn("/alert/manage/", duplicate_payload["manage_url"])
        self.assertFalse(duplicate_payload["created"])
        self.assertFalse(duplicate_payload["reactivated"])
        self.assertTrue(
            WeeklyBriefingSubscriber.objects.filter(email="person@example.com").exists()
        )

        subscription = PropertyRecordAlertSubscription.objects.get(
            email="person@example.com",
            parcel_id="P90001",
        )
        subscription.is_active = False
        subscription.save(update_fields=["is_active", "updated_at"])

        reactivate_response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "person@example.com",
                    "parcel_id": "P90001",
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(reactivate_response.status_code, 200)
        reactivate_payload = reactivate_response.json()
        self.assertFalse(reactivate_payload["created"])
        self.assertTrue(reactivate_payload["reactivated"])

        subscription.refresh_from_db()
        self.assertTrue(subscription.is_active)

    @patch(
        "openskagit.parcelalert.fetch_assessor_baseline_fallback",
        return_value={"owner_name": "Fallback Owner", "situs_address": "Fallback Address", "source": "db"},
    )
    def test_subscribe_uses_fallback_when_preview_context_is_placeholder(self, _fallback_mock):
        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "person@example.com",
                    "parcel_id": "P90001",
                    "parcel_contexts": [
                        {
                            "parcel_id": "P90001",
                            "owner_name": "Owner unavailable",
                            "situs_address": "Address unavailable",
                        }
                    ],
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        subscription = PropertyRecordAlertSubscription.objects.get(
            email="person@example.com",
            parcel_id="P90001",
        )
        self.assertEqual(subscription.baseline_owner_name, "Fallback Owner")
        self.assertEqual(subscription.baseline_situs_address, "Fallback Address")

    def test_subscribe_rejects_invalid_email(self):
        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps({"email": "bad-email", "parcel_id": "P90001", "accept_terms": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"], "Invalid request.")
        self.assertIn("email", payload["details"])

    @patch("openskagit.parcelalert.logger.warning")
    def test_subscribe_invalid_request_logs_warning(self, warning_mock):
        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps({"email": "bad-email", "parcel_id": "P90001", "accept_terms": True}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        warning_mock.assert_called_once()
        args, kwargs = warning_mock.call_args
        self.assertEqual(args[0], "property_record_alert.subscribe_invalid_request")
        self.assertIn("email", kwargs["extra"]["detail_keys"])

    def test_subscribe_rejects_unknown_parcel(self):
        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "person@example.com",
                    "parcel_id": "P99999",
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"], "Parcel not found.")

    def test_subscribe_enforces_watch_limit(self):
        for index in range(1, 12):
            parcel_number = f"P91{index:03d}"
            MasterParcel.objects.create(parcel_number=parcel_number, situs_address=f"{index} Main St")
            if index <= 10:
                PropertyRecordAlertSubscription.objects.create(
                    email="limit@example.com",
                    parcel_id=parcel_number,
                    is_active=True,
                )

        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "limit@example.com",
                    "parcel_id": "P91011",
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"], "Watch limit reached.")
        self.assertIn("email", payload["details"])

    def test_subscribe_multiple_parcels_in_one_request(self):
        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "person@example.com",
                    "parcel_ids": ["P90001", "P90002"],
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["processed_count"], 2)
        self.assertEqual(payload["created_count"], 2)
        self.assertEqual(payload["reactivated_count"], 0)
        self.assertEqual(
            PropertyRecordAlertSubscription.objects.filter(email="person@example.com", is_active=True).count(),
            2,
        )

    def test_subscribe_stores_monitored_names(self):
        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps(
                {
                    "email": "person@example.com",
                    "parcel_id": "P90001",
                    "monitored_names": "Owner Name\nOwner LLC, Spouse Name",
                    "accept_terms": True,
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        subscription = PropertyRecordAlertSubscription.objects.get(
            email="person@example.com",
            parcel_id="P90001",
        )
        self.assertIn("Owner Name", subscription.monitored_names)
        self.assertIn("Owner LLC", subscription.monitored_names)
        self.assertIn("Spouse Name", subscription.monitored_names)

    def test_subscribe_requires_terms_acceptance(self):
        response = self.client.post(
            "/alert/subscribe/",
            data=json.dumps({"email": "person@example.com", "parcel_id": "P90001"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"], "Invalid request.")
        self.assertIn("accept_terms", payload["details"])

    @patch(
        "openskagit.parcelalert.resolve_assessor_baseline",
        return_value={"owner_name": "Owner Name", "situs_address": "100 Main St", "source": "db"},
    )
    @patch("openskagit.parcelalert.logger.info")
    def test_parcel_preview_returns_context_and_logs_success(self, info_mock, _baseline_mock):
        response = self.client.post(
            "/alert/parcel-preview/",
            data=json.dumps({"parcel_id": "p90001"}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["parcel"]["parcel_id"], "P90001")
        self.assertEqual(payload["parcel"]["owner_name"], "Owner Name")
        self.assertEqual(payload["parcel"]["source"], "db")
        messages = [call.args[0] for call in info_mock.call_args_list]
        self.assertIn("property_record_alert.parcel_preview_succeeded", messages)

    @patch("openskagit.parcelalert.logger.warning")
    def test_parcel_preview_invalid_request_logs_warning(self, warning_mock):
        response = self.client.post(
            "/alert/parcel-preview/",
            data=json.dumps({}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertEqual(payload["error"], "Invalid request.")
        warning_mock.assert_called_once()
        self.assertEqual(
            warning_mock.call_args.args[0],
            "property_record_alert.parcel_preview_invalid_request",
        )

    def test_unsubscribe_endpoint_deactivates_single_subscription(self):
        subscription = PropertyRecordAlertSubscription.objects.create(
            email="person@example.com",
            parcel=self.parcel,
            is_active=True,
        )
        token = subscription.unsubscribe_token()

        confirm_response = self.client.get(f"/alert/unsubscribe/{token}/")
        self.assertEqual(confirm_response.status_code, 200)
        self.assertContains(confirm_response, "Confirm unsubscribe")

        post_response = self.client.post(f"/alert/unsubscribe/{token}/")
        self.assertEqual(post_response.status_code, 200)

        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)

    def test_unsubscribe_invalid_token(self):
        response = self.client.get("/alert/unsubscribe/not-a-valid-token/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Link expired or invalid")

    def test_manage_alert_page_and_save(self):
        subscription = PropertyRecordAlertSubscription.objects.create(
            email="person@example.com",
            parcel=self.parcel,
            is_active=True,
        )
        token = subscription.manage_token()

        get_response = self.client.get(f"/alert/manage/{token}/")
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, "Edit alert")
        self.assertContains(get_response, "person@example.com")

        post_response = self.client.post(
            f"/alert/manage/{token}/",
            data={"email": "updated@example.com"},
        )
        self.assertEqual(post_response.status_code, 200)
        self.assertContains(post_response, "Alert details saved.")

        subscription.refresh_from_db()
        self.assertEqual(subscription.email, "updated@example.com")
        self.assertFalse(subscription.is_active)

    def test_manage_alert_api_updates_subscription(self):
        subscription = PropertyRecordAlertSubscription.objects.create(
            email="person@example.com",
            parcel=self.parcel,
            is_active=False,
        )
        token = subscription.manage_token()

        response = self.client.post(
            f"/alert/manage/{token}/api/",
            data=json.dumps(
                {
                    "email": "updated@example.com",
                    "is_active": True,
                    "monitored_names": ["Alias One", "Alias Two"],
                }
            ),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["subscription"]["email"], "updated@example.com")
        self.assertTrue(payload["subscription"]["is_active"])
        self.assertIn("Alias One", payload["subscription"]["monitored_names"])

    def test_manage_alert_invalid_token(self):
        response = self.client.get("/alert/manage/not-a-valid-token/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Link expired or invalid")

        api_response = self.client.post(
            "/alert/manage/not-a-valid-token/api/",
            data=json.dumps({"email": "updated@example.com", "is_active": True}),
            content_type="application/json",
        )
        self.assertEqual(api_response.status_code, 400)
        payload = api_response.json()
        self.assertEqual(payload["error"], "Invalid link.")

    def test_delete_alert_one_click(self):
        subscription = PropertyRecordAlertSubscription.objects.create(
            email="person@example.com",
            parcel=self.parcel,
            is_active=True,
        )
        token = subscription.manage_token()

        response = self.client.get(f"/alert/delete/{token}/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alert deleted")

        subscription.refresh_from_db()
        self.assertFalse(subscription.is_active)


class PropertyRecordAlertCommandTests(TestCase):
    def setUp(self):
        self.parcel = MasterParcel.objects.create(parcel_number="P90001", situs_address="100 Main St")
        self.subscription = PropertyRecordAlertSubscription.objects.create(
            email="person@example.com",
            parcel=self.parcel,
            baseline_recording_number="202601300000",
            last_notified_recording_number="202601300000",
            is_active=True,
        )

    @patch("openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest")
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents",
        return_value=[
            _recording_doc("202601300001", "2026-01-30", "QUITCLAIM DEED", "P90001"),
            _recording_doc("202601300000", "2026-01-29", "QUITCLAIM DEED", "P90001"),
        ],
    )
    def test_command_dry_run_does_not_advance_cursor(self, _fetch_mock, send_mock):
        out = StringIO()
        call_command("nightly_property_record_alert", "--dry-run", stdout=out)
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.last_notified_recording_number, "202601300000")
        send_mock.assert_not_called()

    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest",
        return_value=1,
    )
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents",
        return_value=[
            _recording_doc("202601300001", "2026-01-30", "QUITCLAIM DEED", "P90001"),
            _recording_doc("202601300000", "2026-01-29", "QUITCLAIM DEED", "P90001"),
        ],
    )
    def test_command_send_path_advances_cursor(self, _fetch_mock, _send_mock):
        call_command("nightly_property_record_alert")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.last_notified_recording_number, "202601300001")
        self.assertIsNotNone(self.subscription.last_alert_sent_at)

    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest",
        side_effect=RuntimeError("mail failed"),
    )
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents",
        return_value=[
            _recording_doc("202601300001", "2026-01-30", "QUITCLAIM DEED", "P90001"),
            _recording_doc("202601300000", "2026-01-29", "QUITCLAIM DEED", "P90001"),
        ],
    )
    def test_command_send_failure_keeps_cursor(self, _fetch_mock, _send_mock):
        call_command("nightly_property_record_alert")
        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.last_notified_recording_number, "202601300000")

    @patch("openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest")
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents",
        return_value=[_recording_doc("202601300001", "2026-01-30", "QUITCLAIM DEED", "P90001")],
    )
    def test_command_bootstraps_empty_cursor_without_back_alert(self, _fetch_mock, send_mock):
        self.subscription.baseline_recording_number = ""
        self.subscription.last_notified_recording_number = ""
        self.subscription.baseline_recorded_date = None
        self.subscription.save(
            update_fields=[
                "baseline_recording_number",
                "last_notified_recording_number",
                "baseline_recorded_date",
                "updated_at",
            ]
        )

        call_command("nightly_property_record_alert")

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.baseline_recording_number, "202601300001")
        self.assertEqual(self.subscription.last_notified_recording_number, "202601300001")
        send_mock.assert_not_called()

    @patch("openskagit.management.commands.nightly_property_record_alert.logger.warning")
    def test_command_logs_when_no_active_subscriptions(self, warning_mock):
        self.subscription.is_active = False
        self.subscription.save(update_fields=["is_active", "updated_at"])

        out = StringIO()
        call_command("nightly_property_record_alert", stdout=out)

        self.assertIn("No active property record alert subscriptions found.", out.getvalue())
        warning_messages = [call.args[0] for call in warning_mock.call_args_list]
        self.assertIn("property_record_alert.no_active_subscriptions", warning_messages)

    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest",
        return_value=1,
    )
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents",
        return_value=[
            _recording_doc("202601300001", "2026-01-30", "QUITCLAIM DEED", "P90001"),
            _recording_doc("202601300000", "2026-01-29", "QUITCLAIM DEED", "P90001"),
        ],
    )
    def test_command_respects_email_and_parcel_filters(self, fetch_mock, _send_mock):
        other_parcel = MasterParcel.objects.create(parcel_number="P90002", situs_address="200 Main St")
        PropertyRecordAlertSubscription.objects.create(
            email="other@example.com",
            parcel=other_parcel,
            baseline_recording_number="202601300000",
            last_notified_recording_number="202601300000",
            is_active=True,
        )

        call_command(
            "nightly_property_record_alert",
            "--email",
            "person@example.com",
            "--parcel",
            "P90001",
        )
        fetch_mock.assert_called_once_with("P90001")

    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest",
        return_value=1,
    )
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents",
        return_value=[
            _recording_doc("202601300001", "2026-01-30", "QUITCLAIM DEED", "P90001"),
            _recording_doc("202601300000", "2026-01-29", "QUITCLAIM DEED", "P90001"),
        ],
    )
    def test_command_respects_max_parcels_limit(self, fetch_mock, _send_mock):
        second = MasterParcel.objects.create(parcel_number="P90002", situs_address="200 Main St")
        PropertyRecordAlertSubscription.objects.create(
            email="person@example.com",
            parcel=second,
            baseline_recording_number="202601300000",
            last_notified_recording_number="202601300000",
            is_active=True,
        )

        call_command("nightly_property_record_alert", "--max-parcels", "1")
        fetch_mock.assert_called_once_with("P90001")

    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest",
        return_value=1,
    )
    @patch("openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents")
    def test_command_groups_multiple_parcels_into_one_email_digest(self, fetch_mock, send_mock):
        second = MasterParcel.objects.create(parcel_number="P90002", situs_address="200 Main St")
        second_subscription = PropertyRecordAlertSubscription.objects.create(
            email="person@example.com",
            parcel=second,
            baseline_recording_number="202601300100",
            last_notified_recording_number="202601300100",
            is_active=True,
        )

        def _fetch(parcel_id):
            if parcel_id == "P90001":
                return [
                    _recording_doc("202601300001", "2026-01-30", "QUITCLAIM DEED", "P90001"),
                    _recording_doc("202601300000", "2026-01-29", "QUITCLAIM DEED", "P90001"),
                ]
            return [
                _recording_doc("202601300101", "2026-01-30", "QUITCLAIM DEED", "P90002"),
                _recording_doc("202601300100", "2026-01-29", "QUITCLAIM DEED", "P90002"),
            ]

        fetch_mock.side_effect = _fetch

        call_command("nightly_property_record_alert")

        send_mock.assert_called_once()
        payload = send_mock.call_args.kwargs
        self.assertEqual(payload["email"], "person@example.com")
        self.assertEqual(len(payload["parcel_alerts"]), 2)

        self.subscription.refresh_from_db()
        second_subscription.refresh_from_db()
        self.assertEqual(self.subscription.last_notified_recording_number, "202601300001")
        self.assertEqual(second_subscription.last_notified_recording_number, "202601300101")

    @patch("openskagit.management.commands.nightly_property_record_alert.logger.exception")
    @patch("openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest")
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents",
        side_effect=RuntimeError("recorder timeout"),
    )
    def test_command_recorder_failure_updates_state_and_logs(self, _fetch_mock, send_mock, exception_mock):
        call_command("nightly_property_record_alert")

        history = ParcelHistory.objects.get(parcel_number="P90001")
        self.assertEqual(history.recording_last_error, "recorder timeout")
        self.assertIsNotNone(history.recording_checked_at)

        self.subscription.refresh_from_db()
        self.assertIsNotNone(self.subscription.last_checked_at)
        send_mock.assert_not_called()

        exception_mock.assert_called_once()
        args, kwargs = exception_mock.call_args
        self.assertEqual(args[0], "property_record_alert.recorder_fetch_failed")
        self.assertEqual(kwargs["extra"]["parcel_id"], "P90001")

    @patch("openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest")
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents",
        return_value=[
            _recording_doc("202601300001", "2026-01-30", "MISCELLANEOUS FILING", "P90001"),
            _recording_doc("202601300000", "2026-01-29", "MISCELLANEOUS FILING", "P90001"),
        ],
    )
    def test_command_skips_non_triggering_documents(self, _fetch_mock, send_mock):
        call_command("nightly_property_record_alert")

        self.subscription.refresh_from_db()
        self.assertEqual(self.subscription.last_notified_recording_number, "202601300000")
        self.assertIsNotNone(self.subscription.last_checked_at)
        send_mock.assert_not_called()

    @patch("openskagit.management.commands.nightly_property_record_alert.logger.info")
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.send_property_record_alert_digest",
        return_value=1,
    )
    @patch(
        "openskagit.management.commands.nightly_property_record_alert.alert_service.fetch_recording_documents",
        return_value=[
            _recording_doc("202601300001", "2026-01-30", "QUITCLAIM DEED", "P90001"),
            _recording_doc("202601300000", "2026-01-29", "QUITCLAIM DEED", "P90001"),
        ],
    )
    def test_command_emits_diagnostic_lifecycle_logs(self, _fetch_mock, _send_mock, info_mock):
        call_command("nightly_property_record_alert")
        messages = {call.args[0] for call in info_mock.call_args_list}
        self.assertIn("property_record_alert.run_started", messages)
        self.assertIn("property_record_alert.run_scope", messages)
        self.assertIn("property_record_alert.parcel_fetch_succeeded", messages)
        self.assertIn("property_record_alert.subscription_scan_summary", messages)
        self.assertIn("property_record_alert.pending_digest_summary", messages)
        self.assertIn("property_record_alert.email_send_attempt", messages)
        self.assertIn("property_record_alert.email_send_succeeded", messages)
        self.assertIn("property_record_alert.run_completed", messages)


class PropertyRecordAlertTestEmailCommandTests(SimpleTestCase):
    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="alerts@openskagit.com",
        SITE_URL="https://openskagit.com",
    )
    def test_send_property_record_alert_test_command_sends_email(self):
        out = StringIO()
        call_command(
            "send_property_record_alert_test",
            "--email",
            "tester@example.com",
            "--parcel",
            "P90001",
            "--owner",
            "Owner Name",
            "--address",
            "100 Main St",
            "--recording-number",
            "TEST-12345",
            "--recorded-date",
            "2026-03-20",
            "--document-type",
            "QUITCLAIM DEED",
            "--document-url",
            "https://example.com/recording/TEST-12345",
            stdout=out,
        )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("OpenSkagit parcel record alert test", message.subject)
        self.assertEqual(message.to, ["tester@example.com"])
        self.assertEqual(message.from_email, "alerts@openskagit.com")
        self.assertIn("Parcel: P90001", message.body)
        self.assertIn("Owner: Owner Name", message.body)
        self.assertIn("Recording number: TEST-12345", message.body)
        self.assertEqual(len(message.alternatives), 1)
        self.assertIn("Parcel P90001", message.alternatives[0][0])
        self.assertIn("TEST-12345", message.alternatives[0][0])
        self.assertIn("Sent test property record alert email to tester@example.com.", out.getvalue())

    @override_settings(
        EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
        DEFAULT_FROM_EMAIL="alerts@openskagit.com",
        SITE_URL="https://openskagit.com",
    )
    def test_send_property_record_alert_test_command_live_template_mode(self):
        out = StringIO()
        call_command(
            "send_property_record_alert_test",
            "--email",
            "tester@example.com",
            "--parcel",
            "P90001",
            "--recording-number",
            "TEST-67890",
            "--recorded-date",
            "2026-03-20",
            "--live-template",
            stdout=out,
        )

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("OpenSkagit parcel record alert", message.subject)
        self.assertIn("Edit alert details", message.body)
        self.assertIn("Delete this alert", message.body)
        self.assertIn("TEST-67890", message.body)
