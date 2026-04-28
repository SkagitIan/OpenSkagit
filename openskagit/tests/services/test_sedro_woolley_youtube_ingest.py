from pathlib import Path

from django.test import SimpleTestCase

from openskagit.services.sedro_woolley_youtube_ingest import (
    SedroWoolleyYoutubeIngestor,
    _extract_video_id,
    chunk_transcript_segments,
)


class YoutubeIngestHelpersTests(SimpleTestCase):
    def test_extract_video_id_handles_common_url_shapes(self):
        self.assertEqual(_extract_video_id("dQw4w9WgXcQ"), "dQw4w9WgXcQ")
        self.assertEqual(
            _extract_video_id("https://www.youtube.com/watch?v=dQw4w9WgXcQ"),
            "dQw4w9WgXcQ",
        )
        self.assertEqual(
            _extract_video_id("https://youtu.be/dQw4w9WgXcQ?t=3"),
            "dQw4w9WgXcQ",
        )

    def test_chunk_transcript_segments_creates_overlap(self):
        segments = [
            {"text": "alpha bravo charlie delta", "start": 0, "end": 5},
            {"text": "echo foxtrot golf hotel", "start": 5, "end": 10},
            {"text": "india juliet kilo lima", "start": 10, "end": 15},
        ]

        chunks = chunk_transcript_segments(segments, max_tokens=8, overlap_tokens=2)
        self.assertEqual(len(chunks), 2)
        self.assertIn("alpha bravo", chunks[0]["text"])
        self.assertTrue(chunks[1]["text"].startswith("echo foxtrot"))
        self.assertEqual(chunks[0]["start_time"], 0.0)
        self.assertEqual(chunks[1]["end_time"], 15.0)

    def test_summarize_error_maps_youtube_bot_challenge(self):
        ingestor = SedroWoolleyYoutubeIngestor(media_root=Path("/tmp"))
        message = ingestor._summarize_error(Exception("ERROR: Sign in to confirm you’re not a bot"))
        self.assertIn("YouTube requested bot verification", message)

    def test_base_yt_dlp_options_include_cookie_file(self):
        ingestor = SedroWoolleyYoutubeIngestor(
            media_root=Path("/tmp"),
            cookies_file=Path("/tmp/test_cookies.txt"),
        )
        options = ingestor._base_yt_dlp_options()
        self.assertEqual(options.get("cookiefile"), "/tmp/test_cookies.txt")

    def test_ingest_single_video_rejects_invalid_url(self):
        ingestor = SedroWoolleyYoutubeIngestor(media_root=Path("/tmp"))
        with self.assertRaises(ValueError):
            ingestor.ingest_single_video(youtube_url="not-a-youtube-url")
