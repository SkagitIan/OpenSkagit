import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.core import mail
from django.test import TestCase

from openskagit.models import (
    CitizenSurveyOption,
    CitizenSurveyParticipant,
    CitizenSurveyQuestion,
    CitizenSurveyReminder,
    CitizenSurveyResponse,
)
from openskagit.services import citizen_survey as survey_service


class CitizenSurveyServiceTests(TestCase):
    def setUp(self):
        self.week_start = date(2026, 3, 22)
        self.question = CitizenSurveyQuestion.objects.create(
            prompt="Should this be the weekly prompt?",
            week_start_date=self.week_start,
            is_published=True,
        )
        self.yes_option = CitizenSurveyOption.objects.create(
            question=self.question,
            label="Yes",
            sort_order=0,
        )
        self.no_option = CitizenSurveyOption.objects.create(
            question=self.question,
            label="No",
            sort_order=1,
        )
        self.participant = CitizenSurveyParticipant.objects.create()

    def test_current_week_start_uses_sunday_week_start_pt(self):
        pacific = ZoneInfo("America/Los_Angeles")
        sunday_night = datetime(2026, 3, 29, 23, 59, tzinfo=pacific)
        monday_start = datetime(2026, 3, 30, 0, 0, tzinfo=pacific)

        self.assertEqual(survey_service.current_week_start_date(sunday_night), date(2026, 3, 29))
        self.assertEqual(survey_service.current_week_start_date(monday_start), date(2026, 3, 29))

    def test_record_response_blocks_second_answer_for_same_question(self):
        _, created_first = survey_service.record_response(
            question=self.question,
            option=self.yes_option,
            participant=self.participant,
            comment="first answer",
            focused_city="mount-vernon",
        )
        _, created_second = survey_service.record_response(
            question=self.question,
            option=self.no_option,
            participant=self.participant,
            comment="second answer should be ignored",
            focused_city="mount-vernon",
        )

        self.assertTrue(created_first)
        self.assertFalse(created_second)
        self.assertEqual(
            CitizenSurveyResponse.objects.filter(question=self.question, participant=self.participant).count(),
            1,
        )

    def test_record_response_allows_same_participant_on_next_week(self):
        next_week_question = CitizenSurveyQuestion.objects.create(
            prompt="Next week prompt",
            week_start_date=self.week_start + timedelta(weeks=1),
            is_published=True,
        )
        next_week_option = CitizenSurveyOption.objects.create(
            question=next_week_question,
            label="Yes",
            sort_order=0,
        )

        _, created_current = survey_service.record_response(
            question=self.question,
            option=self.yes_option,
            participant=self.participant,
            focused_city="mount-vernon",
        )
        _, created_next = survey_service.record_response(
            question=next_week_question,
            option=next_week_option,
            participant=self.participant,
            focused_city="sedro-woolley",
        )

        self.assertTrue(created_current)
        self.assertTrue(created_next)
        self.assertEqual(
            CitizenSurveyResponse.objects.filter(participant=self.participant).count(),
            2,
        )

    def test_staff_debug_mode_allows_repeat_answers_same_question(self):
        _, created_first = survey_service.record_response(
            question=self.question,
            option=self.yes_option,
            participant=self.participant,
            focused_city="mount-vernon",
            allow_repeat_submission=True,
        )
        _, created_second = survey_service.record_response(
            question=self.question,
            option=self.no_option,
            participant=self.participant,
            focused_city="mount-vernon",
            allow_repeat_submission=True,
        )
        self.assertTrue(created_first)
        self.assertTrue(created_second)
        self.assertEqual(
            CitizenSurveyResponse.objects.filter(question=self.question, participant=self.participant).count(),
            2,
        )

    def test_upsert_reminder_normalizes_email(self):
        reminder, created = survey_service.upsert_reminder("Resident@Example.com ")
        self.assertTrue(created)
        self.assertEqual(reminder.email, "resident@example.com")

        second_reminder, created_again = survey_service.upsert_reminder("resident@example.com")
        self.assertFalse(created_again)
        self.assertEqual(reminder.id, second_reminder.id)
        self.assertEqual(CitizenSurveyReminder.objects.count(), 1)

    def test_interest_updates_persist_on_participant(self):
        selected = survey_service.update_participant_interest(
            participant=self.participant,
            interest_type="topic",
            slug="schools",
            selected=True,
        )
        self.assertTrue(selected)

        selected_city = survey_service.update_participant_interest(
            participant=self.participant,
            interest_type="city",
            slug="mount-vernon",
            selected=True,
        )
        self.assertTrue(selected_city)

        self.participant.refresh_from_db()
        self.assertIn("schools", self.participant.civic_topic_interests)
        self.assertIn("mount-vernon", self.participant.city_interests)

    def test_reminder_unsubscribe_token_round_trip(self):
        token = survey_service.sign_reminder_unsubscribe_token("Resident@Example.com ")
        self.assertTrue(token)
        self.assertEqual(survey_service.unsign_reminder_unsubscribe_token(token), "resident@example.com")

    def test_new_question_notification_email_contains_survey_and_unsubscribe_links(self):
        reminder = CitizenSurveyReminder.objects.create(email="resident@example.com")
        sent = survey_service.send_new_question_notification(
            reminder=reminder,
            question=self.question,
        )
        self.assertTrue(sent)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertIn("/survey/", message.body)
        self.assertIn("/survey/reminders/unsubscribe/", message.body)
