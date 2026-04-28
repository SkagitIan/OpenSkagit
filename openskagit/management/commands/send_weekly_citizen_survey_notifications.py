from datetime import date
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand

from openskagit.models import CitizenSurveyQuestion, CitizenSurveyReminder, CitizenSurveyReminderSend
from openskagit.services import citizen_survey as survey_service


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


class Command(BaseCommand):
    help = "Send weekly citizen survey launch emails to reminder subscribers."

    def add_arguments(self, parser):
        parser.add_argument(
            "--week-start",
            type=str,
            help="Optional week start date in YYYY-MM-DD format. Defaults to current active week.",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Resend even if a reminder was already logged for this question.",
        )

    def handle(self, *args, **options):
        week_start_raw = (options.get("week_start") or "").strip()
        force = bool(options.get("force"))

        question = self._resolve_question(week_start_raw)
        if question is None:
            self.stdout.write(self.style.WARNING("No published weekly question found for notification send."))
            return

        reminders = list(CitizenSurveyReminder.objects.order_by("id"))
        if not reminders:
            self.stdout.write(self.style.WARNING("No survey reminder subscribers found."))
            return

        sent_reminder_ids = set()
        if not force:
            sent_reminder_ids = set(
                CitizenSurveyReminderSend.objects.filter(question=question).values_list("reminder_id", flat=True)
            )

        created_logs = 0
        sent_count = 0
        skipped_count = 0
        failed_count = 0

        for reminder in reminders:
            if not force and reminder.id in sent_reminder_ids:
                skipped_count += 1
                continue

            delivered = survey_service.send_new_question_notification(reminder=reminder, question=question)
            if not delivered:
                failed_count += 1
                continue

            sent_count += 1
            _, created = CitizenSurveyReminderSend.objects.get_or_create(
                question=question,
                reminder=reminder,
            )
            if created:
                created_logs += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Survey notification run complete "
                f"(question_id={question.id}, sent={sent_count}, skipped={skipped_count}, failed={failed_count}, "
                f"new_logs={created_logs})."
            )
        )

    def _resolve_question(self, week_start_raw: str) -> CitizenSurveyQuestion | None:
        if week_start_raw:
            try:
                week_start = date.fromisoformat(week_start_raw)
            except ValueError:
                self.stdout.write(self.style.ERROR("Invalid --week-start value. Use YYYY-MM-DD."))
                return None
            return CitizenSurveyQuestion.objects.filter(week_start_date=week_start, is_published=True).first()
        return survey_service.get_active_question()
