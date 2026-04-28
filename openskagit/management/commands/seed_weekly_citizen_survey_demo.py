import json
from datetime import date, timedelta
from pathlib import Path

from dotenv import load_dotenv
from django.core.management.base import BaseCommand, CommandError

from openskagit.models import (
    CitizenSurveyOption,
    CitizenSurveyParticipant,
    CitizenSurveyQuestion,
    CitizenSurveyReminderSend,
    CitizenSurveyResponse,
)


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


class Command(BaseCommand):
    help = (
        "Replace current survey question/option/response demo data with questions from a JSON file. "
        "Week 1 starts at the provided start date."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--questions-file",
            type=str,
            default="data/questions.json",
            help="Path to JSON file containing {'questions': [...]} payload.",
        )
        parser.add_argument(
            "--start-date",
            type=str,
            default="2026-03-22",
            help="Start date for week 1 in YYYY-MM-DD format.",
        )

    def handle(self, *args, **options):
        questions_file = Path(str(options.get("questions_file") or "data/questions.json")).resolve()
        if not questions_file.exists():
            raise CommandError(f"Questions file not found: {questions_file}")

        start_date_raw = str(options.get("start_date") or "").strip()
        try:
            week_one_start = date.fromisoformat(start_date_raw)
        except ValueError as exc:
            raise CommandError("Invalid --start-date value. Use YYYY-MM-DD.") from exc

        with questions_file.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
        questions = payload.get("questions")
        if not isinstance(questions, list) or not questions:
            raise CommandError("Questions payload must include a non-empty 'questions' array.")

        deleted_sends, _ = CitizenSurveyReminderSend.objects.all().delete()
        deleted_responses, _ = CitizenSurveyResponse.objects.all().delete()
        deleted_options, _ = CitizenSurveyOption.objects.all().delete()
        deleted_questions, _ = CitizenSurveyQuestion.objects.all().delete()
        deleted_participants, _ = CitizenSurveyParticipant.objects.all().delete()

        created_questions = 0
        created_options = 0

        for index, item in enumerate(questions):
            prompt = str(item.get("question") or "").strip()
            responses = item.get("responses") or []
            if not prompt:
                raise CommandError(f"Question at position {index + 1} is missing 'question' text.")
            if not isinstance(responses, list) or not responses:
                raise CommandError(f"Question at position {index + 1} is missing response options.")

            week_start = week_one_start + timedelta(weeks=index)
            metadata = {
                "source_id": item.get("id"),
                "question_type": item.get("question_type"),
                "analytic_role": item.get("analytic_role"),
                "topic_bucket": item.get("topic_bucket"),
                "geography_scope": item.get("geography_scope"),
                "marketing_sentence": item.get("marketing_sentence"),
            }

            question = CitizenSurveyQuestion.objects.create(
                prompt=prompt,
                week_start_date=week_start,
                is_published=True,
                metadata=metadata,
            )
            created_questions += 1

            for option_index, label in enumerate(responses):
                option_label = str(label or "").strip()
                if not option_label:
                    raise CommandError(
                        f"Question '{prompt[:40]}...' has an empty response label at index {option_index}."
                    )
                CitizenSurveyOption.objects.create(
                    question=question,
                    label=option_label,
                    sort_order=option_index,
                )
                created_options += 1

        self.stdout.write(
            self.style.SUCCESS(
                "Citizen survey question import complete "
                f"(deleted: sends={deleted_sends}, responses={deleted_responses}, options={deleted_options}, "
                f"questions={deleted_questions}, participants={deleted_participants}; "
                f"created: questions={created_questions}, options={created_options}; "
                f"week1={week_one_start.isoformat()})."
            )
        )
