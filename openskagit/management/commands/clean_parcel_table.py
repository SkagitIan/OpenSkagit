from django.core.management.base import BaseCommand
from django.db.models import Q

from openskagit.models import Parcel


JUNK_ADDRESSES = {
    "-", "nan", "nan nan", "nan, nan",
    "nan nan nan", "nan, nan, nan"
}


class Command(BaseCommand):
    help = "Delete Parcel records with missing or junk addresses."

    def handle(self, *args, **options):
        qs = Parcel.objects.filter(
            Q(address__isnull=True) |
            Q(address__exact="") |
            Q(address__in=JUNK_ADDRESSES)
        )

        # extra protection: normalized stripping
        # deletes rows where stripped text is empty or 'nan'
        extra_qs = Parcel.objects.exclude(id__in=qs.values("id")).filter(
            Q(address__regex=r"^\s*$") |
            Q(address__iregex=r"^nan[ ,nan]*$")
        )

        total = qs.count() + extra_qs.count()

        # delete both sets together
        ids = list(qs.values_list("id", flat=True)) + \
              list(extra_qs.values_list("id", flat=True))
        Parcel.objects.filter(id__in=ids).delete()

        self.stdout.write(self.style.SUCCESS(f"Deleted {total} junk Parcel records."))
