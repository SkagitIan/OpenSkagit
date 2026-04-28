from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError

from openskagit.models import CoAppraiserRoutePlan
from openskagit.services import coappraiser_routes


load_dotenv(Path(__file__).resolve().parents[4] / ".env")


class Command(BaseCommand):
    help = "Run a queued CoAppraiser route plan by plan id."

    def add_arguments(self, parser):
        parser.add_argument("--plan-id", required=True, help="CoAppraiserRoutePlan UUID")

    def handle(self, *args, **options):
        plan_id = str(options["plan_id"]).strip()
        if not plan_id:
            raise CommandError("--plan-id is required")

        plan = CoAppraiserRoutePlan.objects.filter(id=plan_id).select_related("parcel_set").first()
        if not plan:
            raise CommandError(f"Plan {plan_id} not found")

        if plan.status == CoAppraiserRoutePlan.STATUS_COMPLETED:
            self.stdout.write(self.style.SUCCESS(f"Plan {plan.id} already completed."))
            return

        self.stdout.write(f"Running CoAppraiser plan {plan.id} for parcel_set {plan.parcel_set_id}...")
        try:
            completed = coappraiser_routes.run_route_plan(plan)
        except Exception as exc:
            raise CommandError(f"Plan {plan.id} failed: {exc}") from exc

        self.stdout.write(
            self.style.SUCCESS(
                f"Completed plan {completed.id}: routes={completed.cluster_count}, "
                f"stops={completed.routed_stop_count}, status={completed.status}"
            )
        )
