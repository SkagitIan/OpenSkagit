from django.core.management.base import BaseCommand, CommandError

from gis.models import GISSourceSubmission
from gis.services.discover import inspect_submission


class Command(BaseCommand):
    help = "Run GIS inspection pipeline for a single GISSourceSubmission id."

    def add_arguments(self, parser):
        parser.add_argument("submission_id", type=int)

    def handle(self, *args, **options):
        submission_id = int(options["submission_id"])
        try:
            submission = GISSourceSubmission.objects.get(pk=submission_id)
        except GISSourceSubmission.DoesNotExist as exc:
            raise CommandError(f"Submission {submission_id} does not exist.") from exc

        inspect_submission(submission)
        self.stdout.write(self.style.SUCCESS(f"Inspection completed for submission {submission_id}."))
