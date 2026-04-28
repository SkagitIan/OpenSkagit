from __future__ import annotations
import datetime as dt
import uuid
from pathlib import Path

from dotenv import load_dotenv
from django.core.management import BaseCommand, CommandError, call_command
from django.utils import timezone

from openskagit.models import SedroWoolleyPermitAlertRun, SedroWoolleyPermitSyncRun
from openskagit.services.sedro_woolley_permit_alerts import (
    build_permit_alert_payload,
    fetch_new_important_permits,
    last_successful_alert_watermark,
    parse_recipients,
    recipients_from_env,
    send_permit_alert_email,
)


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = "Nightly Sedro-Woolley important permit sync + email alert via configured email backend (Resend/Anymail)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=45,
            help="Rolling sync window passed to sync_sw_permits (default: 45).",
        )
        parser.add_argument(
            "--skip-sync",
            action="store_true",
            help="Skip running sync_sw_permits and only send alerts for already-ingested permits.",
        )
        parser.add_argument(
            "--sync-dry-run",
            action="store_true",
            help="Run sync_sw_permits in dry-run mode (fetch/parse only, no permit writes).",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Build alert payload and print summary without sending email or advancing watermark.",
        )
        parser.add_argument(
            "--to",
            action="append",
            default=[],
            help="Override/add recipients (repeatable, comma-separated allowed).",
        )
        parser.add_argument(
            "--recipient-env",
            default="SW_PERMIT_ALERT_RECIPIENTS",
            help="Environment variable with comma-separated recipient emails (default: SW_PERMIT_ALERT_RECIPIENTS).",
        )
        parser.add_argument(
            "--max-items",
            type=int,
            default=50,
            help="Max permit rows included in the email (default: 50).",
        )
        parser.add_argument(
            "--permit-date",
            help="Single permit_date (YYYY-MM-DD). Defaults to yesterday if no permit-date range is provided.",
        )
        parser.add_argument(
            "--permit-date-start",
            help="permit_date lower bound (YYYY-MM-DD). Defaults to yesterday when omitted.",
        )
        parser.add_argument(
            "--permit-date-end",
            help="permit_date upper bound (YYYY-MM-DD). Defaults to yesterday when omitted.",
        )
        parser.add_argument(
            "--use-watermark",
            action="store_true",
            help="Also filter by created_at > last successful alert watermark (off by default for date-based alerts).",
        )
        parser.add_argument(
            "--job-name",
            default="nightly_sw_permit_alert",
            help="Watermark namespace for alert runs (default: nightly_sw_permit_alert).",
        )

    def handle(self, *args, **options):
        job_name = str(options["job_name"]).strip() or "nightly_sw_permit_alert"
        run_id = f"swalert-{timezone.now().strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}"
        started_at = timezone.now()

        alert_run = SedroWoolleyPermitAlertRun.objects.create(
            run_id=run_id,
            job_name=job_name,
            dry_run=bool(options["dry_run"]),
            sync_attempted=not bool(options["skip_sync"]),
            started_at=started_at,
        )

        try:
            permit_date_single_raw = (options.get("permit_date") or "").strip()
            permit_date_start_raw = (options.get("permit_date_start") or "").strip()
            permit_date_end_raw = (options.get("permit_date_end") or "").strip()
            yesterday = timezone.localdate() - dt.timedelta(days=1)

            if permit_date_single_raw and (permit_date_start_raw or permit_date_end_raw):
                raise CommandError("Use either --permit-date or --permit-date-start/--permit-date-end, not both.")

            if permit_date_single_raw:
                try:
                    permit_date_start = permit_date_end = dt.date.fromisoformat(permit_date_single_raw)
                except ValueError as exc:
                    raise CommandError(f"Invalid --permit-date: {exc}") from exc
            else:
                if permit_date_start_raw:
                    try:
                        permit_date_start = dt.date.fromisoformat(permit_date_start_raw)
                    except ValueError as exc:
                        raise CommandError(f"Invalid --permit-date-start: {exc}") from exc
                else:
                    permit_date_start = yesterday

                if permit_date_end_raw:
                    try:
                        permit_date_end = dt.date.fromisoformat(permit_date_end_raw)
                    except ValueError as exc:
                        raise CommandError(f"Invalid --permit-date-end: {exc}") from exc
                else:
                    permit_date_end = yesterday

            if permit_date_start > permit_date_end:
                raise CommandError("--permit-date-start cannot be after --permit-date-end")

            sync_run = None
            if not options["skip_sync"]:
                sync_before_id = (
                    SedroWoolleyPermitSyncRun.objects.order_by("-started_at")
                    .values_list("id", flat=True)
                    .first()
                )
                sync_kwargs = {"days": int(options["days"])}
                if options["sync_dry_run"]:
                    sync_kwargs["dry_run"] = True
                call_command("sync_sw_permits", **sync_kwargs)

                latest_sync = SedroWoolleyPermitSyncRun.objects.order_by("-started_at").first()
                if latest_sync and latest_sync.id != sync_before_id:
                    sync_run = latest_sync
                    alert_run.sync_run = sync_run

            watermark_from = last_successful_alert_watermark(job_name=job_name)
            watermark_to = timezone.now()
            alert_run.watermark_from = watermark_from

            permits = fetch_new_important_permits(
                since_exclusive=watermark_from if options.get("use_watermark") else None,
                until_inclusive=watermark_to,
                permit_date_start=permit_date_start,
                permit_date_end=permit_date_end,
                max_items=int(options["max_items"]),
            )
            alert_run.permit_count = len(permits)
            alert_run.permit_external_ids = [permit.external_id for permit in permits]

            env_recipients = recipients_from_env(env_var=options["recipient_env"])
            recipients = parse_recipients(list(options["to"]) + env_recipients)
            alert_run.recipients = recipients
            alert_run.recipient_count = len(recipients)

            payload = build_permit_alert_payload(
                permits,
                watermark_from=watermark_from,
                watermark_to=watermark_to,
                permit_date_start=permit_date_start,
                permit_date_end=permit_date_end,
            )
            alert_run.subject = payload.subject

            if options["dry_run"]:
                self.stdout.write(self.style.WARNING("DRY RUN: no email sent, watermark not advanced."))
                self.stdout.write(f"permits_found: {len(permits)}")
                self.stdout.write(
                    f"permit_date_range: {permit_date_start.isoformat()}..{permit_date_end.isoformat()}"
                )
                self.stdout.write(f"recipients: {', '.join(recipients) if recipients else '(none)'}")
                alert_run.success = True
                alert_run.finished_at = timezone.now()
                alert_run.save(
                    update_fields=[
                        "sync_run",
                        "watermark_from",
                        "permit_count",
                        "permit_external_ids",
                        "recipients",
                        "recipient_count",
                        "subject",
                        "success",
                        "finished_at",
                        "updated_at",
                    ]
                )
                return

            if not permits:
                self.stdout.write(self.style.SUCCESS("No new important permits found."))
                self.stdout.write(
                    f"permit_date_range: {permit_date_start.isoformat()}..{permit_date_end.isoformat()}"
                )
                alert_run.success = True
                alert_run.watermark_to = watermark_to
                alert_run.finished_at = timezone.now()
                alert_run.save(
                    update_fields=[
                        "sync_run",
                        "watermark_from",
                        "watermark_to",
                        "permit_count",
                        "permit_external_ids",
                        "recipients",
                        "recipient_count",
                        "subject",
                        "success",
                        "finished_at",
                        "updated_at",
                    ]
                )
                return

            if not recipients:
                raise CommandError(
                    "No recipients configured. Set SW_PERMIT_ALERT_RECIPIENTS or pass --to user@example.com"
                )

            sent_count = send_permit_alert_email(recipients=recipients, payload=payload)
            alert_run.sent_count = sent_count
            alert_run.success = True
            alert_run.watermark_to = watermark_to
            alert_run.finished_at = timezone.now()
            alert_run.save(
                update_fields=[
                    "sync_run",
                    "watermark_from",
                    "watermark_to",
                    "permit_count",
                    "recipient_count",
                    "sent_count",
                    "recipients",
                    "permit_external_ids",
                    "subject",
                    "success",
                    "finished_at",
                    "updated_at",
                ]
            )

            self.stdout.write(self.style.SUCCESS("Sedro-Woolley permit alert sent."))
            self.stdout.write(f"run_id: {alert_run.run_id}")
            self.stdout.write(f"permit_date_range: {permit_date_start.isoformat()}..{permit_date_end.isoformat()}")
            self.stdout.write(f"permits_found: {alert_run.permit_count}")
            self.stdout.write(f"sent_count: {alert_run.sent_count}")
            self.stdout.write(f"watermark_to: {alert_run.watermark_to.isoformat() if alert_run.watermark_to else ''}")
            if sync_run:
                self.stdout.write(f"sync_run: {sync_run.run_id}")

        except Exception as exc:
            alert_run.error_message = str(exc)
            alert_run.finished_at = timezone.now()
            alert_run.success = False
            alert_run.save(
                update_fields=[
                    "sync_run",
                    "watermark_from",
                    "permit_count",
                    "recipient_count",
                    "recipients",
                    "permit_external_ids",
                    "subject",
                    "error_message",
                    "success",
                    "finished_at",
                    "updated_at",
                ]
            )
            if isinstance(exc, CommandError):
                raise
            raise CommandError(str(exc)) from exc
