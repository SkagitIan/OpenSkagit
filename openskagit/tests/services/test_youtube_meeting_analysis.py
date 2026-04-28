import uuid
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase, TestCase
from pydantic import ValidationError as PydanticValidationError

from openskagit.models import SedroWoolleyYoutubeVideo, YoutubeMeetingAnalysisJob
from openskagit.services.youtube_meeting_analysis import (
    ChunkExtractionPayload,
    CouncilMeetingAnalysisPayload,
    YoutubeMeetingAnalysisResult,
    build_analysis_fingerprint,
)


def _base_final_payload() -> dict:
    return {
        "schema_version": "council_meeting_analysis.v1",
        "source": {
            "type": "youtube",
            "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            "video_id": "dQw4w9WgXcQ",
        },
        "meeting": {
            "title": "City Council Meeting",
            "body_name": "Sedro-Woolley City Council",
            "date": "2026-03-17",
            "duration_seconds": 3600.0,
        },
        "participants": [],
        "topics": [],
        "motions": [],
        "decisions": [],
        "speaker_statements": [],
        "action_items": [],
        "timeline": [],
        "quality_notes": {
            "uncertainties": [],
            "missing_sections": [],
            "ambiguities": [],
        },
        "processing": {
            "model": "gemini-2.0-flash",
            "prompt_version": "council-meeting-analysis-v1",
            "prompt_hash": "a" * 64,
            "generated_at": "2026-03-17T00:00:00+00:00",
            "transcript_stats": {"chunk_count": 1},
        },
    }


class YoutubeMeetingAnalysisSchemaTests(SimpleTestCase):
    def test_analysis_fingerprint_is_stable(self):
        one = build_analysis_fingerprint(
            youtube_video_id="dQw4w9WgXcQ",
            model_name="gemini-2.0-flash",
        )
        two = build_analysis_fingerprint(
            youtube_video_id="dQw4w9WgXcQ",
            model_name="gemini-2.0-flash",
        )
        self.assertEqual(one, two)

    def test_chunk_schema_requires_evidence_for_motions(self):
        payload = {
            "participants": [],
            "topics": [],
            "motions": [
                {
                    "motion_id": "m1",
                    "text": "Approve agenda",
                    "moved_by": "councilmember_1",
                    "seconded_by": "councilmember_2",
                    "vote_result": "passed",
                    "vote_breakdown": {"yes": "7", "no": "0"},
                    "evidence": [],
                }
            ],
            "decisions": [],
            "speaker_statements": [],
            "action_items": [],
            "timeline": [],
            "quality_notes": {"uncertainties": [], "missing_sections": [], "ambiguities": []},
        }
        with self.assertRaises(PydanticValidationError):
            ChunkExtractionPayload.model_validate(payload)

    def test_final_schema_requires_evidence_for_decisions(self):
        payload = _base_final_payload()
        payload["decisions"] = [
            {
                "decision_id": "d1",
                "outcome": "Budget approved",
                "impact_summary": "Adopted as presented.",
                "related_motion_id": "m1",
                "evidence": [],
            }
        ]
        with self.assertRaises(PydanticValidationError):
            CouncilMeetingAnalysisPayload.model_validate(payload)

    def test_unknown_speaker_is_allowed_with_evidence(self):
        payload = _base_final_payload()
        payload["speaker_statements"] = [
            {
                "statement_id": "s1",
                "participant_id": "unknown_speaker_1",
                "text": "Public comment regarding traffic safety.",
                "topic_ids": ["topic_public_comment"],
                "start_seconds": 320.0,
                "end_seconds": 341.0,
                "evidence": [
                    {
                        "start_seconds": 320.0,
                        "end_seconds": 341.0,
                        "quote": "I am concerned about traffic speed.",
                        "chunk_index": 2,
                    }
                ],
            }
        ]
        validated = CouncilMeetingAnalysisPayload.model_validate(payload)
        self.assertEqual(validated.speaker_statements[0].participant_id, "unknown_speaker_1")


class YoutubeMeetingJobCommandTests(TestCase):
    def setUp(self):
        super().setUp()
        user_model = get_user_model()
        self.staff_user = user_model.objects.create_user(
            username="yt-worker",
            email="yt-worker@example.com",
            password="password123",
            is_staff=True,
            is_superuser=True,
        )
        self.video = SedroWoolleyYoutubeVideo.objects.create(
            video_id="dQw4w9WgXcQ",
            video_url="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
            title="Test video",
            status=SedroWoolleyYoutubeVideo.STATUS_COMPLETED,
        )
        self.job = YoutubeMeetingAnalysisJob.objects.create(
            requested_by=self.staff_user,
            youtube_url=self.video.video_url,
            youtube_video_id=self.video.video_id,
            status=YoutubeMeetingAnalysisJob.STATUS_PENDING,
            status_detail="Queued",
            progress_stage="queued",
            progress_percent=0,
            analysis_fingerprint=uuid.uuid4().hex,
            model_name="gemini-2.0-flash",
            prompt_version="",
            prompt_hash="",
            result_schema_version="council_meeting_analysis.v1",
            result_json={"_request": {"meeting_context": {"body_name": "Test Council"}}},
            error_message="",
        )

    @patch("openskagit.management.commands.process_youtube_meeting_job.analyze_youtube_meeting")
    def test_command_marks_job_succeeded(self, mock_analyze):
        mock_analyze.return_value = YoutubeMeetingAnalysisResult(
            analysis={
                "schema_version": "council_meeting_analysis.v1",
                "source": {"type": "youtube", "url": self.video.video_url, "video_id": self.video.video_id},
                "meeting": {"title": "Meeting", "body_name": "Test Council", "date": "", "duration_seconds": 0},
                "participants": [],
                "topics": [],
                "motions": [],
                "decisions": [],
                "speaker_statements": [],
                "action_items": [],
                "timeline": [],
                "quality_notes": {"uncertainties": [], "missing_sections": [], "ambiguities": []},
                "processing": {
                    "model": "gemini-2.0-flash",
                    "prompt_version": "council-meeting-analysis-v1",
                    "prompt_hash": "a" * 64,
                    "generated_at": "2026-03-17T00:00:00+00:00",
                    "transcript_stats": {"chunk_count": 1},
                },
            },
            prompt_version="council-meeting-analysis-v1",
            prompt_hash="a" * 64,
            model_name="gemini-2.0-flash",
            result_schema_version="council_meeting_analysis.v1",
            youtube_video=self.video,
        )

        call_command("process_youtube_meeting_job", "--job-id", str(self.job.id))
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, YoutubeMeetingAnalysisJob.STATUS_SUCCEEDED)
        self.assertEqual(self.job.progress_stage, "completed")
        self.assertEqual(self.job.progress_percent, 100)
        self.assertEqual(self.job.prompt_version, "council-meeting-analysis-v1")
        self.assertEqual(self.job.prompt_hash, "a" * 64)

    @patch(
        "openskagit.management.commands.process_youtube_meeting_job.analyze_youtube_meeting",
        side_effect=RuntimeError("boom"),
    )
    def test_command_marks_job_failed(self, _mock_analyze):
        with self.assertRaises(CommandError):
            call_command("process_youtube_meeting_job", "--job-id", str(self.job.id))

        self.job.refresh_from_db()
        self.assertEqual(self.job.status, YoutubeMeetingAnalysisJob.STATUS_FAILED)
        self.assertEqual(self.job.progress_stage, "failed")
        self.assertIn("boom", self.job.error_message)
        self.assertGreaterEqual(self.job.failure_count, 1)
