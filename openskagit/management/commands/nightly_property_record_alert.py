from __future__ import annotations

import datetime as dt
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from django.core.management import BaseCommand
from django.utils import timezone

from openskagit.models import ParcelHistory, PropertyRecordAlertSubscription
from openskagit.services import property_record_alerts as alert_service


load_dotenv(Path(__file__).resolve().parents[4] / ".env")

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Nightly parcel recorded-document alert digest sender."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Process and log pending alerts but do not send email or advance cursors.",
        )
        parser.add_argument(
            "--email",
            help="Process subscriptions for one email only.",
        )
        parser.add_argument(
            "--parcel",
            help="Process subscriptions for one parcel only (example: P90623).",
        )
        parser.add_argument(
            "--max-parcels",
            type=int,
            default=None,
            help="Cap the number of unique parcels processed in this run.",
        )

    def handle(self, *args, **options):
        started_at = timezone.now()
        dry_run = bool(options.get("dry_run"))
        email_filter = alert_service.normalize_email(options.get("email") or "")
        parcel_filter = alert_service.normalize_parcel_id(options.get("parcel") or "")
        max_parcels = options.get("max_parcels")
        total_parcels_scanned = 0
        total_subscriptions_scanned = 0
        total_unsent_documents = 0
        total_triggered_documents = 0
        cursor_bootstrap_count = 0
        fetch_failure_count = 0

        subscriptions_qs = PropertyRecordAlertSubscription.objects.select_related("parcel").filter(
            is_active=True
        )
        if email_filter:
            subscriptions_qs = subscriptions_qs.filter(email=email_filter)
        if parcel_filter:
            subscriptions_qs = subscriptions_qs.filter(parcel_id=parcel_filter)

        subscriptions = list(subscriptions_qs.order_by("parcel_id", "email"))
        logger.info(
            "property_record_alert.run_started",
            extra={
                "dry_run": dry_run,
                "email_filter": email_filter,
                "parcel_filter": parcel_filter,
                "max_parcels": max_parcels,
                "active_subscription_count": len(subscriptions),
            },
        )

        def _log_run_completed(
            *,
            pending_email_count: int,
            pending_subscription_count: int,
            sent_email_count: int = 0,
            failed_email_count: int = 0,
        ) -> None:
            duration_seconds = max(0.0, (timezone.now() - started_at).total_seconds())
            logger.info(
                "property_record_alert.run_completed",
                extra={
                    "dry_run": dry_run,
                    "email_filter": email_filter,
                    "parcel_filter": parcel_filter,
                    "max_parcels": max_parcels,
                    "parcels_scanned": total_parcels_scanned,
                    "subscriptions_scanned": total_subscriptions_scanned,
                    "unsent_documents_seen": total_unsent_documents,
                    "triggered_documents": total_triggered_documents,
                    "cursor_bootstraps": cursor_bootstrap_count,
                    "fetch_failures": fetch_failure_count,
                    "pending_email_count": pending_email_count,
                    "pending_subscription_count": pending_subscription_count,
                    "sent_email_count": sent_email_count,
                    "failed_email_count": failed_email_count,
                    "duration_seconds": round(duration_seconds, 3),
                },
            )

        if not subscriptions:
            logger.warning(
                "property_record_alert.no_active_subscriptions",
                extra={
                    "dry_run": dry_run,
                    "email_filter": email_filter,
                    "parcel_filter": parcel_filter,
                },
            )
            self.stdout.write(self.style.WARNING("No active property record alert subscriptions found."))
            _log_run_completed(pending_email_count=0, pending_subscription_count=0)
            return

        subscriptions_by_parcel: dict[str, list[PropertyRecordAlertSubscription]] = defaultdict(list)
        for subscription in subscriptions:
            subscriptions_by_parcel[subscription.parcel_id].append(subscription)

        available_parcel_ids = sorted(subscriptions_by_parcel.keys())
        parcel_ids = list(available_parcel_ids)
        if isinstance(max_parcels, int) and max_parcels > 0:
            parcel_ids = parcel_ids[:max_parcels]
        skipped_parcel_count = max(0, len(available_parcel_ids) - len(parcel_ids))
        logger.info(
            "property_record_alert.run_scope",
            extra={
                "parcel_count": len(parcel_ids),
                "available_parcel_count": len(available_parcel_ids),
                "skipped_parcel_count": skipped_parcel_count,
                "subscription_count": len(subscriptions),
            },
        )

        self.stdout.write(
            f"Processing {len(parcel_ids)} parcel(s) across {len(subscriptions)} active subscription(s)."
        )
        if dry_run:
            self.stdout.write(self.style.WARNING("DRY RUN: no email sends and no cursor updates."))

        pending_by_email: dict[str, list[dict[str, Any]]] = defaultdict(list)
        parcels_with_pending = 0

        for parcel_id in parcel_ids:
            parcel_subscriptions = subscriptions_by_parcel[parcel_id]
            total_parcels_scanned += 1
            total_subscriptions_scanned += len(parcel_subscriptions)
            checked_at = timezone.now()
            parcel_history, _created = ParcelHistory.objects.get_or_create(
                parcel_number=parcel_id,
                defaults={"rows": [], "taxes": {}},
            )
            cached_documents = (
                parcel_history.recording_documents
                if isinstance(parcel_history.recording_documents, list)
                else []
            )
            previous_latest = (parcel_history.recording_latest_number or "").strip()

            try:
                current_documents = alert_service.fetch_recording_documents(parcel_id)
                merged_documents = alert_service.merge_recording_documents(
                    current_documents,
                    cached_documents,
                    max_items=alert_service.MAX_CACHED_RECORDING_DOCUMENTS,
                )
                parcel_history.recording_documents = merged_documents
                parcel_history.recording_latest_number = (
                    str(current_documents[0].get("recording_number") or "").strip()
                    if current_documents
                    else previous_latest
                )
                latest_recorded_date = (
                    str(current_documents[0].get("recorded_date") or "").strip()
                    if current_documents
                    else ""
                )
                parsed_latest_date = None
                if latest_recorded_date:
                    try:
                        parsed_latest_date = dt.date.fromisoformat(latest_recorded_date)
                    except ValueError:
                        parsed_latest_date = None
                parcel_history.recording_latest_recorded_date = (
                    parsed_latest_date
                )
                parcel_history.recording_checked_at = checked_at
                parcel_history.recording_last_error = ""
                parcel_history.save(
                    update_fields=[
                        "recording_documents",
                        "recording_latest_number",
                        "recording_latest_recorded_date",
                        "recording_checked_at",
                        "recording_last_error",
                        "scraped_at",
                    ]
                )
                logger.info(
                    "property_record_alert.parcel_fetch_succeeded",
                    extra={
                        "parcel_id": parcel_id,
                        "subscription_count": len(parcel_subscriptions),
                        "current_document_count": len(current_documents),
                        "merged_document_count": len(merged_documents),
                        "previous_latest_recording_number": previous_latest,
                        "latest_recording_number": parcel_history.recording_latest_number,
                    },
                )
            except Exception as exc:
                fetch_failure_count += 1
                parcel_history.recording_checked_at = checked_at
                parcel_history.recording_last_error = str(exc)
                parcel_history.save(
                    update_fields=[
                        "recording_checked_at",
                        "recording_last_error",
                        "scraped_at",
                    ]
                )
                logger.exception(
                    "property_record_alert.recorder_fetch_failed",
                    extra={"parcel_id": parcel_id, "subscription_count": len(parcel_subscriptions)},
                )
                self.stdout.write(
                    self.style.WARNING(f"Skipping parcel {parcel_id}: recorder fetch failed ({exc}).")
                )
                for subscription in parcel_subscriptions:
                    subscription.last_checked_at = checked_at
                    subscription.save(update_fields=["last_checked_at", "updated_at"])
                continue

            parcel_has_pending = False
            for subscription in parcel_subscriptions:
                anchor = (
                    subscription.last_notified_recording_number
                    or subscription.baseline_recording_number
                )
                latest_number = (parcel_history.recording_latest_number or "").strip()
                if not latest_number and current_documents:
                    latest_number = str(current_documents[0].get("recording_number") or "").strip()
                if not anchor:
                    # Start from "now" when a subscription has no cursor yet.
                    cursor_bootstrap_count += 1
                    update_fields = ["last_checked_at", "updated_at"]
                    subscription.last_checked_at = checked_at
                    if latest_number:
                        subscription.baseline_recording_number = latest_number
                        subscription.last_notified_recording_number = latest_number
                        if parsed_latest_date and not subscription.baseline_recorded_date:
                            subscription.baseline_recorded_date = parsed_latest_date
                            update_fields.append("baseline_recorded_date")
                        update_fields.extend(
                            [
                                "baseline_recording_number",
                                "last_notified_recording_number",
                            ]
                        )
                    subscription.save(update_fields=update_fields)
                    logger.info(
                        "property_record_alert.subscription_cursor_bootstrapped",
                        extra={
                            "subscription_id": subscription.pk,
                            "parcel_id": subscription.parcel_id,
                            "email": subscription.email,
                            "latest_recording_number": latest_number,
                        },
                    )
                    continue

                unsent_documents = alert_service.compute_unsent_documents(
                    merged_documents=merged_documents,
                    current_documents=current_documents,
                    anchor_recording_number=anchor,
                    previous_latest_recording_number=previous_latest,
                )
                scored_documents: list[dict[str, Any]] = []
                for document in unsent_documents:
                    risk_payload = alert_service.evaluate_document_risk(
                        subscription=subscription,
                        document=document,
                        recent_documents=merged_documents,
                    )
                    if not alert_service.should_trigger_document_alert(risk_payload):
                        continue
                    enriched = dict(document)
                    enriched.update(risk_payload)
                    scored_documents.append(enriched)

                unsent_count = len(unsent_documents)
                triggered_count = len(scored_documents)
                filtered_count = max(0, unsent_count - triggered_count)
                total_unsent_documents += unsent_count
                total_triggered_documents += triggered_count
                subscription.last_checked_at = checked_at
                subscription.save(update_fields=["last_checked_at", "updated_at"])
                logger.info(
                    "property_record_alert.subscription_scan_summary",
                    extra={
                        "subscription_id": subscription.pk,
                        "parcel_id": subscription.parcel_id,
                        "email": subscription.email,
                        "anchor_recording_number": anchor,
                        "unsent_document_count": unsent_count,
                        "triggered_document_count": triggered_count,
                        "filtered_document_count": filtered_count,
                    },
                )

                if not scored_documents:
                    continue

                parcel_has_pending = True
                pending_by_email[subscription.email].append(
                    {
                        "subscription": subscription,
                        "parcel_id": subscription.parcel_id,
                        "owner_name": subscription.baseline_owner_name,
                        "situs_address": subscription.baseline_situs_address,
                        "unsubscribe_url": alert_service.build_subscription_unsubscribe_url(subscription),
                        "manage_url": alert_service.build_subscription_manage_url(subscription),
                        "delete_url": alert_service.build_subscription_delete_url(subscription),
                        "documents": scored_documents,
                    }
                )

            if parcel_has_pending:
                parcels_with_pending += 1

        pending_email_count = len(pending_by_email)
        pending_subscription_count = sum(len(items) for items in pending_by_email.values())
        self.stdout.write(
            f"Pending digests: {pending_email_count} email(s), {pending_subscription_count} parcel section(s)."
        )
        self.stdout.write(f"Parcels with pending high-signal alerts: {parcels_with_pending}")
        logger.info(
            "property_record_alert.pending_digest_summary",
            extra={
                "pending_email_count": pending_email_count,
                "pending_subscription_count": pending_subscription_count,
                "parcels_with_pending": parcels_with_pending,
            },
        )

        if not pending_by_email:
            _log_run_completed(
                pending_email_count=pending_email_count,
                pending_subscription_count=pending_subscription_count,
            )
            return

        sent_email_count = 0
        failed_email_count = 0

        for recipient_email, parcel_alerts in pending_by_email.items():
            doc_count = sum(len(item.get("documents", [])) for item in parcel_alerts)
            logger.info(
                "property_record_alert.email_send_attempt",
                extra={
                    "email": recipient_email,
                    "parcel_sections": len(parcel_alerts),
                    "document_count": doc_count,
                    "dry_run": dry_run,
                },
            )
            if dry_run:
                self.stdout.write(
                    f"[dry-run] would send {doc_count} document alert(s) to {recipient_email}"
                )
                logger.info(
                    "property_record_alert.email_send_skipped_dry_run",
                    extra={
                        "email": recipient_email,
                        "parcel_sections": len(parcel_alerts),
                        "document_count": doc_count,
                    },
                )
                continue

            try:
                sent = alert_service.send_property_record_alert_digest(
                    email=recipient_email,
                    parcel_alerts=parcel_alerts,
                )
            except Exception:
                failed_email_count += 1
                logger.exception(
                    "property_record_alert.email_send_failed",
                    extra={
                        "email": recipient_email,
                        "parcel_sections": len(parcel_alerts),
                    },
                )
                continue

            if sent <= 0:
                logger.warning(
                    "property_record_alert.email_send_noop",
                    extra={
                        "email": recipient_email,
                        "parcel_sections": len(parcel_alerts),
                        "document_count": doc_count,
                        "sent_result": sent,
                    },
                )
                continue

            sent_email_count += 1
            sent_at = timezone.now()
            for parcel_alert in parcel_alerts:
                subscription = parcel_alert["subscription"]
                documents = parcel_alert.get("documents", [])
                if not documents:
                    continue
                latest_number = str(documents[0].get("recording_number") or "").strip()
                if not latest_number:
                    continue
                subscription.last_notified_recording_number = latest_number
                subscription.last_alert_sent_at = sent_at
                subscription.last_checked_at = sent_at
                subscription.save(
                    update_fields=[
                        "last_notified_recording_number",
                        "last_alert_sent_at",
                        "last_checked_at",
                        "updated_at",
                    ]
                )
            logger.info(
                "property_record_alert.email_send_succeeded",
                extra={
                    "email": recipient_email,
                    "parcel_sections": len(parcel_alerts),
                    "document_count": doc_count,
                    "sent_result": sent,
                },
            )

        if dry_run:
            _log_run_completed(
                pending_email_count=pending_email_count,
                pending_subscription_count=pending_subscription_count,
                sent_email_count=sent_email_count,
                failed_email_count=failed_email_count,
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Sent {sent_email_count} digest email(s); {failed_email_count} email(s) failed."
            )
        )
        _log_run_completed(
            pending_email_count=pending_email_count,
            pending_subscription_count=pending_subscription_count,
            sent_email_count=sent_email_count,
            failed_email_count=failed_email_count,
        )
