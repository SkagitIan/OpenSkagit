# openskagit/management/commands/report_comparable_coverage.py

from django.core.management.base import BaseCommand
from django.db.models import Q

from openskagit.models import Assessor


class Command(BaseCommand):
    """
    Report how many Assessor records are missing key comparable metrics.

    By default, it looks only at residential (property_type='R'), since that's
    what your CMA/comparable engine uses most heavily. You can override that.
    """

    help = "Report coverage of key comparable metrics on Assessor records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--property-type",
            type=str,
            default="R",
            help="Filter by property_type (e.g. R, C, I). Use 'ALL' to skip filter.",
        )

    def handle(self, *args, **options):
        property_type = options["property_type"]

        qs = Assessor.objects.all()
        if property_type and property_type.upper() != "ALL":
            qs = qs.filter(property_type=property_type.upper())

        total = qs.count()
        if total == 0:
            self.stdout.write(self.style.WARNING("No Assessor rows match filter."))
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Analyzing {total} Assessor records "
                f"(property_type={property_type}) for comparable coverage…"
            )
        )

        # (label, field_name, treat_zero_as_missing)
        metrics = [
            ("living_area", "living_area", True),
            ("bedrooms", "bedrooms", True),
            ("bathrooms", "bathrooms", True),
            ("acres", "acres", True),
            ("quality_score", "quality_score", True),
            ("condition_score", "condition_score", True),
            ("year_built", "year_built", True),
            ("eff_year_built", "eff_year_built", True),
            ("latitude", "latitude", True),
            ("longitude", "longitude", True),
            ("neighborhood_code", "neighborhood_code", False),
            ("land_use_code", "land_use_code", False),
        ]

        self.stdout.write("")
        self.stdout.write(f"{'Metric':20} {'Missing':>10} {'Percent':>10}")
        self.stdout.write("-" * 42)

        core_q = Q()

        for label, field, zero_missing in metrics:
            cond = Q(**{f"{field}__isnull": True})
            if zero_missing:
                cond |= Q(**{f"{field}__lte": 0})
            else:
                cond |= Q(**{f"{field}__exact": ""})

            missing = qs.filter(cond).count()
            percent = (missing / total * 100.0) if total else 0.0

            self.stdout.write(
                f"{label:20} {missing:10d} {percent:9.2f}%"
            )

            # Build "missing any core metric" condition
            core_q |= cond

        # Parcels missing ANY of the above metrics
        missing_any = qs.filter(core_q).distinct().count()
        percent_any = (missing_any / total * 100.0) if total else 0.0

        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                f"Parcels missing at least one comparable metric: "
                f"{missing_any} ({percent_any:.2f}%)"
            )
        )
