from __future__ import annotations

from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from openskagit.models import YoutubeMeetingAnalysisJob
from openskagit.services.youtube_meeting_analysis import build_analysis_fingerprint


class YoutubeMeetingJobsApiTests(TestCase):
    def setUp(self) -> None:
        super().setUp()
        self.client = APIClient()
        user_model = get_user_model()
        self.admin_user = user_model.objects.create_user(
            username="yt-admin",
            email="yt-admin@example.com",
            password="password123",
            is_staff=True,
            is_superuser=True,
        )
        self.regular_user = user_model.objects.create_user(
            username="yt-user",
            email="yt-user@example.com",
            password="password123",
            is_staff=False,
            is_superuser=False,
        )
        self.endpoint = reverse("youtube-meeting-jobs")
        self.youtube_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
        self.video_id = "dQw4w9WgXcQ"
        self.model_name = "gemini-2.0-flash"
        self.fingerprint = build_analysis_fingerprint(
            youtube_video_id=self.video_id,
            model_name=self.model_name,
        )

    def _create_job(self, *, status: str, result_json: dict | None = None) -> YoutubeMeetingAnalysisJob:
        return YoutubeMeetingAnalysisJob.objects.create(
            requested_by=self.admin_user,
            youtube_url=self.youtube_url,
            youtube_video_id=self.video_id,
            status=status,
            status_detail="seeded for tests",
            progress_stage="queued",
            progress_percent=0,
            analysis_fingerprint=self.fingerprint,
            model_name=self.model_name,
            prompt_version="",
            prompt_hash="",
            result_schema_version="council_meeting_analysis.v1",
            result_json=result_json or {},
            error_message="",
        )

    def test_invalid_youtube_url_returns_400_shape(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            self.endpoint,
            {"youtube_url": "not-a-youtube-url"},
            format="json",
        )
        self.assertEqual(response.status_code, 400)
        payload = response.json()
        self.assertIn("error", payload)
        self.assertIn("details", payload)
        self.assertIn("youtube_url", payload["details"])

    @patch("openskagit.api.views.subprocess.Popen")
    def test_new_url_creates_job_and_spawns_process(self, mock_popen):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            self.endpoint,
            {
                "youtube_url": self.youtube_url,
                "meeting_context": {
                    "body_name": "Sedro-Woolley City Council",
                    "roll_call_hint": "Roll call happens in first 2-5 minutes",
                },
            },
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["reused"])
        self.assertIn("job_id", payload)
        self.assertIn("status_url", payload)
        job = YoutubeMeetingAnalysisJob.objects.get(id=payload["job_id"])
        self.assertEqual(job.status, YoutubeMeetingAnalysisJob.STATUS_PENDING)
        self.assertEqual(job.youtube_video_id, self.video_id)
        self.assertEqual(job.analysis_fingerprint, self.fingerprint)
        mock_popen.assert_called_once()

    @patch("openskagit.api.views.subprocess.Popen")
    def test_running_job_dedupe_returns_same_job_id(self, mock_popen):
        running = self._create_job(status=YoutubeMeetingAnalysisJob.STATUS_RUNNING)
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            self.endpoint,
            {"youtube_url": self.youtube_url},
            format="json",
        )
        self.assertEqual(response.status_code, 202)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["reused"])
        self.assertEqual(payload["job_id"], str(running.id))
        self.assertEqual(payload["status"], YoutubeMeetingAnalysisJob.STATUS_RUNNING)
        mock_popen.assert_not_called()

    @patch("openskagit.api.views.subprocess.Popen")
    def test_successful_job_dedupe_returns_existing_result(self, mock_popen):
        succeeded = self._create_job(
            status=YoutubeMeetingAnalysisJob.STATUS_SUCCEEDED,
            result_json={"schema_version": "council_meeting_analysis.v1", "topics": []},
        )
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            self.endpoint,
            {"youtube_url": self.youtube_url},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertTrue(payload["reused"])
        self.assertEqual(payload["job_id"], str(succeeded.id))
        self.assertEqual(payload["status"], YoutubeMeetingAnalysisJob.STATUS_SUCCEEDED)
        self.assertEqual(payload["result"]["schema_version"], "council_meeting_analysis.v1")
        mock_popen.assert_not_called()

    def test_non_staff_access_blocked(self):
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.post(
            self.endpoint,
            {"youtube_url": self.youtube_url},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_get_job_detail_returns_stable_shape(self):
        job = self._create_job(
            status=YoutubeMeetingAnalysisJob.STATUS_SUCCEEDED,
            result_json={"schema_version": "council_meeting_analysis.v1", "topics": []},
        )
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get(reverse("youtube-meeting-job-detail", kwargs={"job_id": job.id}))
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertIn("job", payload)
        job_payload = payload["job"]
        self.assertEqual(job_payload["id"], str(job.id))
        self.assertEqual(job_payload["status"], YoutubeMeetingAnalysisJob.STATUS_SUCCEEDED)
        self.assertEqual(job_payload["result_schema_version"], "council_meeting_analysis.v1")
        self.assertEqual(job_payload["result"]["schema_version"], "council_meeting_analysis.v1")

    def test_get_job_detail_non_staff_blocked(self):
        job = self._create_job(status=YoutubeMeetingAnalysisJob.STATUS_PENDING)
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get(reverse("youtube-meeting-job-detail", kwargs={"job_id": job.id}))
        self.assertEqual(response.status_code, 403)
