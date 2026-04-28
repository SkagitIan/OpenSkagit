import json
import os
from datetime import timedelta
from urllib.parse import quote

os.environ.setdefault("USE_SQLITE_FOR_TESTS", "1")

from django.contrib.auth import get_user_model
from django.test import TestCase

from openskagit.models import (
    CitizenSurveyOption,
    CitizenSurveyParticipant,
    CitizenSurveyQuestion,
    CitizenSurveyReminder,
    CitizenSurveyResponse,
)
from openskagit.services import citizen_survey as survey_service


class CitizenSurveyViewTests(TestCase):
    def setUp(self):
        self.question = CitizenSurveyQuestion.objects.create(
            prompt="Should Mount Vernon expand downtown tree canopy this year?",
            week_start_date=survey_service.current_week_start_date(),
            is_published=True,
        )
        self.option_yes = CitizenSurveyOption.objects.create(
            question=self.question,
            label="Yes",
            sort_order=0,
        )
        self.option_maybe = CitizenSurveyOption.objects.create(
            question=self.question,
            label="Maybe",
            sort_order=1,
        )
        self.option_no = CitizenSurveyOption.objects.create(
            question=self.question,
            label="No",
            sort_order=2,
        )
        self.previous_question = CitizenSurveyQuestion.objects.create(
            prompt="Should the city test a seasonal downtown pilot street closure?",
            week_start_date=survey_service.current_week_start_date() - timedelta(weeks=1),
            is_published=True,
        )
        self.previous_yes = CitizenSurveyOption.objects.create(
            question=self.previous_question,
            label="Yes",
            sort_order=0,
        )
        self.previous_maybe = CitizenSurveyOption.objects.create(
            question=self.previous_question,
            label="Maybe",
            sort_order=1,
        )
        self.previous_no = CitizenSurveyOption.objects.create(
            question=self.previous_question,
            label="No",
            sort_order=2,
        )
        for _ in range(5):
            participant = CitizenSurveyParticipant.objects.create()
            CitizenSurveyResponse.objects.create(
                question=self.previous_question,
                option=self.previous_yes,
                participant=participant,
            )
        for _ in range(2):
            participant = CitizenSurveyParticipant.objects.create()
            CitizenSurveyResponse.objects.create(
                question=self.previous_question,
                option=self.previous_maybe,
                participant=participant,
            )
        participant = CitizenSurveyParticipant.objects.create()
        CitizenSurveyResponse.objects.create(
            question=self.previous_question,
            option=self.previous_no,
            participant=participant,
        )
        self.seeded_history_responses = 8

    def test_survey_page_renders_with_seo_metadata(self):
        response = self.client.get("/survey/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Weekly Community Survey")
        self.assertContains(response, 'name="robots" content="index,follow"')
        self.assertContains(response, '<link rel="canonical" href="http://testserver/survey/"')
        self.assertContains(response, "application/ld+json")
        self.assertContains(response, "Previous Questions")
        self.assertContains(response, "Historical survey response pie chart")
        self.assertNotContains(response, "Which Skagit city do you follow most?")
        self.assertIn(survey_service.PARTICIPANT_COOKIE_NAME, response.cookies)

    def test_response_submission_creates_single_response_and_shows_results_text(self):
        self.client.get("/survey/")
        response = self.client.post(
            "/survey/respond/",
            data={
                "step": "finalize",
                "question_id": str(self.question.id),
                "option_id": str(self.option_yes.id),
                "focused_city": "mount-vernon",
                "comment": "Please prioritize safer routes to school.",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers.get("Location"), "/survey/")
        self.assertEqual(CitizenSurveyResponse.objects.count(), self.seeded_history_responses + 1)
        self.assertEqual(CitizenSurveyResponse.objects.get(question=self.question).focused_city, "mount-vernon")

        page = self.client.get("/survey/")
        self.assertContains(page, "Current totals")
        self.assertContains(page, "Yes")
        self.assertContains(page, "100.0%")

    def test_htmx_submission_requires_city_step_then_returns_updated_card(self):
        self.client.get("/survey/")
        city_step = self.client.post(
            "/survey/respond/",
            data={
                "step": "city",
                "question_id": str(self.question.id),
                "option_id": str(self.option_yes.id),
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(city_step.status_code, 200)
        self.assertContains(city_step, "One more step: which city do you live in?")
        self.assertContains(city_step, "Mount Vernon")

        response = self.client.post(
            "/survey/respond/",
            data={
                "step": "finalize",
                "question_id": str(self.question.id),
                "option_id": str(self.option_yes.id),
                "focused_city": "mount-vernon",
            },
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="survey-current-card"')
        self.assertContains(response, "Current totals")
        self.assertContains(response, "data-survey-chart")
        self.assertEqual(CitizenSurveyResponse.objects.count(), self.seeded_history_responses + 1)
        self.assertEqual(CitizenSurveyResponse.objects.get(question=self.question).focused_city, "mount-vernon")

    def test_duplicate_response_is_ignored(self):
        self.client.get("/survey/")
        payload = {
            "step": "finalize",
            "question_id": str(self.question.id),
            "option_id": str(self.option_yes.id),
            "focused_city": "mount-vernon",
        }
        self.client.post("/survey/respond/", data=payload)
        self.client.post(
            "/survey/respond/",
            data={
                "step": "finalize",
                "question_id": str(self.question.id),
                "option_id": str(self.option_no.id),
                "focused_city": "sedro-woolley",
            },
        )
        self.assertEqual(CitizenSurveyResponse.objects.count(), self.seeded_history_responses + 1)
        saved = CitizenSurveyResponse.objects.get(question=self.question)
        self.assertEqual(saved.option_id, self.option_yes.id)
        self.assertEqual(saved.focused_city, "mount-vernon")

    def test_staff_can_submit_same_question_multiple_times_for_debug(self):
        user = get_user_model().objects.create_user(
            username="survey-staff",
            email="staff@example.com",
            password="pass1234",
            is_staff=True,
        )
        self.client.force_login(user)
        self.client.get("/survey/")

        self.client.post(
            "/survey/respond/",
            data={
                "step": "finalize",
                "question_id": str(self.question.id),
                "option_id": str(self.option_yes.id),
                "focused_city": "mount-vernon",
            },
            HTTP_HX_REQUEST="true",
        )
        self.client.post(
            "/survey/respond/",
            data={
                "step": "finalize",
                "question_id": str(self.question.id),
                "option_id": str(self.option_no.id),
                "focused_city": "mount-vernon",
            },
            HTTP_HX_REQUEST="true",
        )

        cookie_value = self.client.cookies.get(survey_service.PARTICIPANT_COOKIE_NAME).value
        participant_id = survey_service.unsign_participant_cookie_value(cookie_value)
        participant = CitizenSurveyParticipant.objects.get(participant_id=participant_id)
        responses = CitizenSurveyResponse.objects.filter(question=self.question, participant=participant)
        self.assertEqual(responses.count(), 2)
        self.assertTrue(all(item.is_staff_debug for item in responses))

    def test_interest_toggle_endpoint_updates_participant(self):
        self.client.get("/survey/")
        response = self.client.post(
            "/survey/interests/",
            data=json.dumps({"type": "topic", "slug": "schools", "selected": True}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertTrue(response.json()["selected"])

        cookie_value = self.client.cookies.get(survey_service.PARTICIPANT_COOKIE_NAME).value
        participant_id = survey_service.unsign_participant_cookie_value(cookie_value)
        participant = CitizenSurveyParticipant.objects.get(participant_id=participant_id)
        self.assertIn("schools", participant.civic_topic_interests)

    def test_reminder_endpoint_rejects_invalid_and_accepts_valid_email(self):
        self.client.get("/survey/")
        invalid = self.client.post(
            "/survey/reminders/",
            data=json.dumps({"email": "bad-email"}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(invalid.status_code, 400)
        self.assertFalse(invalid.json()["ok"])

        valid = self.client.post(
            "/survey/reminders/",
            data=json.dumps({"email": "Resident@Example.com "}),
            content_type="application/json",
            HTTP_ACCEPT="application/json",
        )
        self.assertEqual(valid.status_code, 200)
        self.assertTrue(valid.json()["ok"])
        self.assertEqual(CitizenSurveyReminder.objects.count(), 1)
        self.assertEqual(CitizenSurveyReminder.objects.first().email, "resident@example.com")

    def test_reminder_unsubscribe_endpoint_removes_email_from_list(self):
        reminder = CitizenSurveyReminder.objects.create(email="resident@example.com")
        token = survey_service.sign_reminder_unsubscribe_token(reminder.email)

        response = self.client.get(f"/survey/reminders/unsubscribe/?token={quote(token)}")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CitizenSurveyReminder.objects.filter(email="resident@example.com").exists())

    def test_reminder_unsubscribe_endpoint_rejects_bad_token(self):
        response = self.client.get("/survey/reminders/unsubscribe/?token=bad-token")
        self.assertEqual(response.status_code, 400)
