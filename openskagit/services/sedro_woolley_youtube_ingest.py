from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional
from urllib.parse import parse_qs, urlparse

from django.db import transaction
from django.utils import timezone

from openskagit.models import SedroWoolleyYoutubeChunk, SedroWoolleyYoutubeVideo


LOGGER = logging.getLogger(__name__)

YOUTUBE_WATCH_URL = "https://www.youtube.com/watch?v={video_id}"
YOUTUBE_VIDEO_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]{6,15}$")
TEMP_AUDIO_EXTENSIONS = {".mp3", ".m4a", ".webm", ".opus", ".wav", ".aac", ".ogg"}
YOUTUBE_BOT_CHALLENGE_MARKERS = (
    "sign in to confirm you're not a bot",
    "sign in to confirm you’re not a bot",
)


def _parse_upload_date(raw_value: Any) -> Optional[dt.date]:
    if not raw_value:
        return None
    text = str(raw_value).strip()
    if not text:
        return None
    try:
        return dt.datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip())


def _extract_video_id(value: str) -> str:
    text = (value or "").strip()
    if not text:
        return ""

    if YOUTUBE_VIDEO_ID_PATTERN.match(text):
        return text

    parsed = urlparse(text)
    if "youtube.com" in parsed.netloc.lower():
        query_video_id = parse_qs(parsed.query).get("v", [""])[0].strip()
        if YOUTUBE_VIDEO_ID_PATTERN.match(query_video_id):
            return query_video_id

        path_parts = [segment for segment in parsed.path.split("/") if segment]
        if len(path_parts) >= 2 and path_parts[0] in {"shorts", "live"}:
            candidate = path_parts[1]
            if YOUTUBE_VIDEO_ID_PATTERN.match(candidate):
                return candidate

    if "youtu.be" in parsed.netloc.lower():
        candidate = parsed.path.strip("/").split("/")[0]
        if YOUTUBE_VIDEO_ID_PATTERN.match(candidate):
            return candidate

    return ""


def chunk_transcript_segments(
    segments: list[dict[str, Any]],
    *,
    max_tokens: int = 400,
    overlap_tokens: int = 50,
) -> list[dict[str, Any]]:
    """
    Build overlapping chunks from Whisper segments while preserving rough timings.
    Token count is approximated using whitespace-delimited words.
    """
    cleaned_segments: list[dict[str, Any]] = []
    for segment in segments or []:
        text = _normalize_whitespace(str(segment.get("text") or ""))
        if not text:
            continue
        words = text.split()
        cleaned_segments.append(
            {
                "text": text,
                "start": float(segment.get("start") or 0),
                "end": float(segment.get("end") or 0),
                "token_count": len(words),
            }
        )

    if not cleaned_segments:
        return []

    chunks: list[dict[str, Any]] = []
    current_segments: list[dict[str, Any]] = []
    current_tokens = 0

    for segment in cleaned_segments:
        seg_tokens = segment["token_count"]
        if current_segments and current_tokens + seg_tokens > max_tokens:
            chunks.append(_render_chunk(current_segments))

            overlap_items: list[dict[str, Any]] = []
            if overlap_tokens > 0:
                overlap_accum = 0
                for previous in reversed(current_segments):
                    overlap_items.insert(0, previous)
                    overlap_accum += previous["token_count"]
                    if overlap_accum >= overlap_tokens:
                        break

            current_segments = overlap_items[:]
            current_tokens = sum(item["token_count"] for item in current_segments)

        current_segments.append(segment)
        current_tokens += seg_tokens

    if current_segments:
        chunks.append(_render_chunk(current_segments))

    for index, chunk in enumerate(chunks):
        chunk["chunk_index"] = index

    return chunks


def _render_chunk(segments: list[dict[str, Any]]) -> dict[str, Any]:
    text = " ".join(item["text"] for item in segments).strip()
    token_count = sum(item["token_count"] for item in segments)
    return {
        "text": text,
        "start_time": float(segments[0]["start"]),
        "end_time": float(segments[-1]["end"]),
        "token_count": token_count,
    }


@dataclass
class YoutubeIngestSummary:
    run_id: str
    started_at: str
    finished_at: str
    duration_seconds: float
    channel_url: str
    videos_found: int
    processed_count: int
    completed_count: int
    skipped_count: int
    failed_count: int
    dry_run_count: int
    chunks_written: int
    whisper_model: str
    embedding_model: str
    manifest_path: str
    run_summary_path: str
    failures: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_seconds": self.duration_seconds,
            "channel_url": self.channel_url,
            "videos_found": self.videos_found,
            "processed_count": self.processed_count,
            "completed_count": self.completed_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "dry_run_count": self.dry_run_count,
            "chunks_written": self.chunks_written,
            "whisper_model": self.whisper_model,
            "embedding_model": self.embedding_model,
            "manifest_path": self.manifest_path,
            "run_summary_path": self.run_summary_path,
            "failures": self.failures,
        }


class SedroWoolleyYoutubeIngestor:
    def __init__(
        self,
        *,
        media_root: Path,
        whisper_model_name: str = "base",
        embedding_model_name: str = "all-MiniLM-L6-v2",
        language: str = "en",
        max_chunk_tokens: int = 400,
        overlap_tokens: int = 50,
        embedding_batch_size: int = 32,
        audio_quality: str = "64",
        resume: bool = True,
        force: bool = False,
        retry_failed: bool = False,
        reclaim_processing_minutes: int = 180,
        dry_run: bool = False,
        oldest_first: bool = False,
        keep_temp_files: bool = False,
        temp_root: Optional[Path] = None,
        whisper_device: str = "cpu",
        cookies_file: Optional[Path] = None,
        cookies_from_browser: str = "",
        log_tracebacks: bool = False,
        progress_callback: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.media_root = media_root
        self.root = media_root / "sedro_woolley" / "youtube_ingest"
        self.manifests_root = self.root / "manifests"
        self.runs_root = self.root / "runs"
        self.temp_root = temp_root or (self.root / "tmp")

        self.whisper_model_name = whisper_model_name
        self.embedding_model_name = embedding_model_name
        self.language = language
        self.max_chunk_tokens = max(50, max_chunk_tokens)
        self.overlap_tokens = max(0, overlap_tokens)
        self.embedding_batch_size = max(1, embedding_batch_size)
        self.audio_quality = audio_quality
        self.resume = resume
        self.force = force
        self.retry_failed = retry_failed
        self.reclaim_processing_minutes = max(0, reclaim_processing_minutes)
        self.dry_run = dry_run
        self.oldest_first = oldest_first
        self.keep_temp_files = keep_temp_files
        self.whisper_device = whisper_device
        self.cookies_file = cookies_file
        self.cookies_from_browser = (cookies_from_browser or "").strip()
        self.log_tracebacks = bool(log_tracebacks)
        self.progress_callback = progress_callback

        self._embedding_model: Any = None
        self._whisper_model: Any = None
        self._yt_dlp: Any = None

    def ingest(self, *, channel_url: str, limit: Optional[int] = None) -> YoutubeIngestSummary:
        started_dt = timezone.now()
        started_at = started_dt.isoformat()
        run_id = started_dt.strftime("%Y%m%dT%H%M%SZ")
        start_clock = time.monotonic()

        self.manifests_root.mkdir(parents=True, exist_ok=True)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

        manifest_path = self.manifests_root / f"{run_id}.jsonl"
        run_summary_path = self.runs_root / f"{run_id}.json"

        self._progress(f"Fetching videos from channel: {channel_url}")
        channel_info, entries = self._fetch_channel_entries(channel_url=channel_url, limit=limit)
        if self.oldest_first:
            entries.reverse()

        channel_title = str(channel_info.get("title") or "")
        channel_id = str(channel_info.get("channel_id") or channel_info.get("id") or "")

        processed_count = 0
        completed_count = 0
        skipped_count = 0
        failed_count = 0
        dry_run_count = 0
        chunks_written = 0
        failures: list[dict[str, Any]] = []

        with manifest_path.open("w", encoding="utf-8") as manifest_handle:
            for index, entry in enumerate(entries, start=1):
                video = self._upsert_video_stub(
                    entry=entry,
                    channel_url=channel_url,
                    channel_id=channel_id,
                    channel_title=channel_title,
                )
                if not video:
                    skipped_count += 1
                    manifest_handle.write(
                        json.dumps(
                            {
                                "index": index,
                                "status": "skipped",
                                "reason": "missing_video_id",
                                "video_id": "",
                                "video_url": "",
                                "processed_at": timezone.now().isoformat(),
                            },
                            ensure_ascii=True,
                        )
                        + "\n"
                    )
                    continue

                should_process, reason = self._should_process_video(video)
                if not should_process:
                    skipped_count += 1
                    manifest_handle.write(
                        json.dumps(
                            {
                                "index": index,
                                "status": "skipped",
                                "reason": reason,
                                "video_id": video.video_id,
                                "video_url": video.video_url,
                                "processed_at": timezone.now().isoformat(),
                            },
                            ensure_ascii=True,
                        )
                        + "\n"
                    )
                    continue

                if self.dry_run:
                    dry_run_count += 1
                    manifest_handle.write(
                        json.dumps(
                            {
                                "index": index,
                                "status": "dry_run",
                                "reason": reason,
                                "video_id": video.video_id,
                                "video_url": video.video_url,
                                "processed_at": timezone.now().isoformat(),
                            },
                            ensure_ascii=True,
                        )
                        + "\n"
                    )
                    continue

                processed_count += 1
                self._progress(f"[{index}/{len(entries)}] Processing {video.video_id} - {video.title or video.video_url}")
                try:
                    chunk_count, segment_count, transcript_chars = self._process_video(video)
                    completed_count += 1
                    chunks_written += chunk_count
                    manifest_handle.write(
                        json.dumps(
                            {
                                "index": index,
                                "status": "completed",
                                "reason": reason,
                                "video_id": video.video_id,
                                "video_url": video.video_url,
                                "chunk_count": chunk_count,
                                "segment_count": segment_count,
                                "transcript_char_count": transcript_chars,
                                "processed_at": timezone.now().isoformat(),
                            },
                            ensure_ascii=True,
                        )
                        + "\n"
                    )
                except Exception as exc:  # pragma: no cover - depends on local env + external downloads
                    failed_count += 1
                    error_message = self._summarize_error(exc)
                    failures.append(
                        {
                            "video_id": video.video_id,
                            "video_url": video.video_url,
                            "error": error_message,
                        }
                    )
                    manifest_handle.write(
                        json.dumps(
                            {
                                "index": index,
                                "status": "failed",
                                "reason": reason,
                                "video_id": video.video_id,
                                "video_url": video.video_url,
                                "error": error_message,
                                "processed_at": timezone.now().isoformat(),
                            },
                            ensure_ascii=True,
                        )
                        + "\n"
                    )
                    self._progress(f"[{index}/{len(entries)}] FAILED {video.video_id}: {error_message}")
                    if self.log_tracebacks:
                        LOGGER.exception("Failed processing YouTube video %s", video.video_id)
                    else:
                        LOGGER.warning("Failed processing YouTube video %s: %s", video.video_id, error_message)

        finished_dt = timezone.now()
        summary = YoutubeIngestSummary(
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_dt.isoformat(),
            duration_seconds=round(time.monotonic() - start_clock, 3),
            channel_url=channel_url,
            videos_found=len(entries),
            processed_count=processed_count,
            completed_count=completed_count,
            skipped_count=skipped_count,
            failed_count=failed_count,
            dry_run_count=dry_run_count,
            chunks_written=chunks_written,
            whisper_model=self.whisper_model_name,
            embedding_model=self.embedding_model_name,
            manifest_path=self._relative_media_path(manifest_path),
            run_summary_path=self._relative_media_path(run_summary_path),
            failures=failures,
        )
        run_summary_path.write_text(json.dumps(summary.to_dict(), ensure_ascii=True, indent=2), encoding="utf-8")
        return summary

    def ingest_single_video(self, *, youtube_url: str, force: bool = False) -> SedroWoolleyYoutubeVideo:
        """
        Ensure one YouTube video has completed transcript chunks.
        Reuses existing rows when already completed unless force=True.
        """
        video_id = _extract_video_id(youtube_url)
        if not video_id:
            raise ValueError("Invalid YouTube URL or video ID.")

        canonical_url = YOUTUBE_WATCH_URL.format(video_id=video_id)

        self.manifests_root.mkdir(parents=True, exist_ok=True)
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

        video = self._upsert_video_stub(
            entry={
                "id": video_id,
                "url": canonical_url,
                "webpage_url": canonical_url,
            },
            channel_url="",
            channel_id="",
            channel_title="",
        )
        if video is None:
            raise RuntimeError("Could not initialize a YouTube video record.")

        has_chunks = SedroWoolleyYoutubeChunk.objects.filter(video=video).exists()
        if (
            not force
            and video.status == SedroWoolleyYoutubeVideo.STATUS_COMPLETED
            and has_chunks
        ):
            return video

        self._progress(f"Processing single video {video.video_id}")
        self._process_video(video)
        return SedroWoolleyYoutubeVideo.objects.get(pk=video.pk)

    def _upsert_video_stub(
        self,
        *,
        entry: dict[str, Any],
        channel_url: str,
        channel_id: str,
        channel_title: str,
    ) -> Optional[SedroWoolleyYoutubeVideo]:
        raw_id = str(entry.get("id") or entry.get("url") or entry.get("webpage_url") or "")
        video_id = _extract_video_id(raw_id)
        if not video_id:
            return None

        video_url = YOUTUBE_WATCH_URL.format(video_id=video_id)
        upload_date = _parse_upload_date(entry.get("upload_date"))
        duration = entry.get("duration")
        title = str(entry.get("title") or "")

        video, created = SedroWoolleyYoutubeVideo.objects.get_or_create(
            video_id=video_id,
            defaults={
                "video_url": video_url,
                "channel_url": channel_url,
                "channel_id": channel_id,
                "channel_title": channel_title,
                "title": title[:500],
                "upload_date": upload_date,
                "duration_seconds": int(duration) if duration else None,
            },
        )

        update_fields: list[str] = []
        if video.video_url != video_url:
            video.video_url = video_url
            update_fields.append("video_url")
        if channel_url and video.channel_url != channel_url:
            video.channel_url = channel_url
            update_fields.append("channel_url")
        if channel_id and video.channel_id != channel_id:
            video.channel_id = channel_id
            update_fields.append("channel_id")
        if channel_title and video.channel_title != channel_title:
            video.channel_title = channel_title[:500]
            update_fields.append("channel_title")
        if title and video.title != title:
            video.title = title[:500]
            update_fields.append("title")
        if upload_date and video.upload_date != upload_date:
            video.upload_date = upload_date
            update_fields.append("upload_date")
        if duration and video.duration_seconds != int(duration):
            video.duration_seconds = int(duration)
            update_fields.append("duration_seconds")
        if created and video.status != SedroWoolleyYoutubeVideo.STATUS_PENDING:
            video.status = SedroWoolleyYoutubeVideo.STATUS_PENDING
            update_fields.append("status")

        if update_fields:
            update_fields.extend(["last_seen_at", "updated_at"])
            video.save(update_fields=update_fields)
        else:
            video.save(update_fields=["last_seen_at", "updated_at"])

        return video

    def _should_process_video(self, video: SedroWoolleyYoutubeVideo) -> tuple[bool, str]:
        if self.force:
            return True, "force"

        if not self.resume:
            return True, "resume_disabled"

        if video.status == SedroWoolleyYoutubeVideo.STATUS_COMPLETED:
            return False, "already_completed"
        if video.status == SedroWoolleyYoutubeVideo.STATUS_SKIPPED:
            return False, "marked_skipped"
        if video.status == SedroWoolleyYoutubeVideo.STATUS_FAILED and not self.retry_failed:
            return False, "failed_retry_disabled"

        if video.status == SedroWoolleyYoutubeVideo.STATUS_PROCESSING:
            stale_cutoff = timezone.now() - dt.timedelta(minutes=self.reclaim_processing_minutes)
            if video.updated_at and video.updated_at < stale_cutoff:
                return True, "reclaim_stale_processing"
            return False, "already_processing"

        return True, "pending"

    def _process_video(self, video: SedroWoolleyYoutubeVideo) -> tuple[int, int, int]:
        now = timezone.now()
        video.status = SedroWoolleyYoutubeVideo.STATUS_PROCESSING
        video.whisper_model = self.whisper_model_name
        video.embedding_model = self.embedding_model_name
        video.started_at = now
        video.last_error = ""
        video.save(
            update_fields=[
                "status",
                "whisper_model",
                "embedding_model",
                "started_at",
                "last_error",
                "updated_at",
                "last_seen_at",
            ]
        )

        artifact_stem: Optional[Path] = None
        try:
            info = self._fetch_video_info(video.video_url)
            self._update_video_metadata_from_info(video, info)

            artifact_stem, audio_path = self._download_audio(video.video_url, video.video_id)
            transcription = self._transcribe_audio(audio_path)
            segments = transcription.get("segments") or []
            language = str(transcription.get("language") or "").strip()

            chunks = chunk_transcript_segments(
                segments,
                max_tokens=self.max_chunk_tokens,
                overlap_tokens=self.overlap_tokens,
            )
            if not chunks:
                raise RuntimeError("No transcript chunks were generated from this video.")

            vectors = self._embed_chunks([chunk["text"] for chunk in chunks])
            if len(vectors) != len(chunks):
                raise RuntimeError("Embedding count did not match chunk count.")

            transcript_char_count = sum(len(_normalize_whitespace(str(seg.get("text") or ""))) for seg in segments)
            chunk_rows = []
            for index, chunk in enumerate(chunks):
                text = chunk["text"]
                content_hash = hashlib.sha256(f"{video.video_id}:{index}:{text}".encode("utf-8")).hexdigest()
                chunk_rows.append(
                    SedroWoolleyYoutubeChunk(
                        video=video,
                        chunk_index=index,
                        chunk_text=text,
                        start_time=float(chunk["start_time"]),
                        end_time=float(chunk["end_time"]),
                        token_count=int(chunk["token_count"]),
                        content_hash=content_hash,
                        embedding_model=self.embedding_model_name,
                        embedding=vectors[index],
                        metadata={
                            "video_url": video.video_url,
                            "duration_seconds": video.duration_seconds,
                            "channel_title": video.channel_title,
                        },
                    )
                )

            with transaction.atomic():
                # Keep storage bounded: replace all prior chunks for this video.
                SedroWoolleyYoutubeChunk.objects.filter(video=video).delete()
                SedroWoolleyYoutubeChunk.objects.bulk_create(chunk_rows, batch_size=200)

                video.status = SedroWoolleyYoutubeVideo.STATUS_COMPLETED
                video.transcript_language = language
                video.transcript_segment_count = len(segments)
                video.transcript_char_count = transcript_char_count
                video.chunk_count = len(chunk_rows)
                video.completed_at = timezone.now()
                video.last_error = ""
                video.metadata = {
                    "source": "youtube",
                    "duration_seconds": video.duration_seconds,
                    "chunk_tokens": self.max_chunk_tokens,
                    "overlap_tokens": self.overlap_tokens,
                }
                video.save(
                    update_fields=[
                        "status",
                        "transcript_language",
                        "transcript_segment_count",
                        "transcript_char_count",
                        "chunk_count",
                        "completed_at",
                        "last_error",
                        "metadata",
                        "updated_at",
                        "last_seen_at",
                    ]
                )

            return len(chunk_rows), len(segments), transcript_char_count
        except Exception as exc:
            SedroWoolleyYoutubeVideo.objects.filter(pk=video.pk).update(
                status=SedroWoolleyYoutubeVideo.STATUS_FAILED,
                failure_count=video.failure_count + 1,
                last_error=str(exc)[:4000],
                completed_at=None,
                updated_at=timezone.now(),
            )
            raise
        finally:
            if artifact_stem and not self.keep_temp_files:
                self._cleanup_artifacts(artifact_stem)

    def _update_video_metadata_from_info(self, video: SedroWoolleyYoutubeVideo, info: dict[str, Any]) -> None:
        upload_date = _parse_upload_date(info.get("upload_date"))
        duration = info.get("duration")
        title = str(info.get("title") or "").strip()
        description = str(info.get("description") or "")
        channel_title = str(info.get("channel") or info.get("uploader") or "")
        channel_id = str(info.get("channel_id") or "")

        update_fields: list[str] = []
        if title and video.title != title:
            video.title = title[:500]
            update_fields.append("title")
        if description and video.description != description:
            video.description = description
            update_fields.append("description")
        if upload_date and video.upload_date != upload_date:
            video.upload_date = upload_date
            update_fields.append("upload_date")
        if duration and video.duration_seconds != int(duration):
            video.duration_seconds = int(duration)
            update_fields.append("duration_seconds")
        if channel_title and video.channel_title != channel_title:
            video.channel_title = channel_title[:500]
            update_fields.append("channel_title")
        if channel_id and video.channel_id != channel_id:
            video.channel_id = channel_id
            update_fields.append("channel_id")

        if update_fields:
            update_fields.extend(["updated_at", "last_seen_at"])
            video.save(update_fields=update_fields)

    def _fetch_channel_entries(
        self,
        *,
        channel_url: str,
        limit: Optional[int] = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        ydl_module = self._load_yt_dlp()
        options: dict[str, Any] = self._base_yt_dlp_options()
        options["extract_flat"] = True
        if limit:
            options["playlistend"] = int(limit)

        with ydl_module.YoutubeDL(options) as ydl:
            info = ydl.extract_info(channel_url, download=False)

        entries: list[dict[str, Any]] = []
        for raw_entry in info.get("entries") or []:
            if not isinstance(raw_entry, dict):
                continue
            entries.append(raw_entry)

        return info, entries

    def _fetch_video_info(self, video_url: str) -> dict[str, Any]:
        ydl_module = self._load_yt_dlp()
        options = self._base_yt_dlp_options()
        options["noplaylist"] = True
        options["skip_download"] = True
        with ydl_module.YoutubeDL(options) as ydl:
            return ydl.extract_info(video_url, download=False)

    def _download_audio(self, video_url: str, video_id: str) -> tuple[Path, Path]:
        ydl_module = self._load_yt_dlp()
        safe_id = re.sub(r"[^A-Za-z0-9._-]+", "_", video_id).strip("._") or "video"
        stamp = timezone.now().strftime("%Y%m%dT%H%M%S")
        artifact_stem = self.temp_root / f"{safe_id}_{stamp}"

        options = self._base_yt_dlp_options()
        options["format"] = "bestaudio/best"
        options["outtmpl"] = str(artifact_stem)
        options["noplaylist"] = True
        options["postprocessors"] = [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": self.audio_quality,
                }
            ]
        with ydl_module.YoutubeDL(options) as ydl:
            ydl.download([video_url])

        candidates = sorted(self.temp_root.glob(f"{artifact_stem.name}*"))
        audio_files = [path for path in candidates if path.is_file() and path.suffix.lower() in TEMP_AUDIO_EXTENSIONS]
        if not audio_files:
            raise RuntimeError("Audio download finished but no audio artifact was found.")

        audio_file = max(audio_files, key=lambda path: path.stat().st_size)
        return artifact_stem, audio_file

    def _transcribe_audio(self, audio_file: Path) -> dict[str, Any]:
        whisper_model = self._load_whisper_model()
        kwargs: dict[str, Any] = {
            "verbose": False,
            "word_timestamps": False,
        }
        if self.language:
            kwargs["language"] = self.language
        if self.whisper_device == "cpu":
            kwargs["fp16"] = False

        return whisper_model.transcribe(str(audio_file), **kwargs)

    def _embed_chunks(self, chunk_texts: list[str]) -> list[list[float]]:
        model = self._load_embedding_model()
        vectors = model.encode(
            chunk_texts,
            batch_size=self.embedding_batch_size,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        if hasattr(vectors, "tolist"):
            vector_list = vectors.tolist()
        else:
            vector_list = [list(row) for row in vectors]

        if not vector_list:
            return []

        first_dim = len(vector_list[0])
        if first_dim != 384:
            raise ValueError(
                f"Embedding dimension mismatch. Expected 384, got {first_dim}. "
                "Use a 384-dimension model such as all-MiniLM-L6-v2."
            )

        return vector_list

    def _cleanup_artifacts(self, artifact_stem: Path) -> None:
        for candidate in self.temp_root.glob(f"{artifact_stem.name}*"):
            if not candidate.is_file():
                continue
            try:
                candidate.unlink(missing_ok=True)
            except Exception:
                LOGGER.warning("Failed to remove temp artifact: %s", candidate)

    def _relative_media_path(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.media_root)).replace("\\", "/")
        except ValueError:
            return str(path)

    def _progress(self, message: str) -> None:
        if self.progress_callback:
            self.progress_callback(message)
        else:
            LOGGER.info(message)

    def _base_yt_dlp_options(self) -> dict[str, Any]:
        options: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            # Using a blend of clients tends to be more resilient than web-only defaults.
            "extractor_args": {
                "youtube": {
                    "player_client": ["android", "web"],
                }
            },
        }
        if self.cookies_file:
            options["cookiefile"] = str(self.cookies_file)
        if self.cookies_from_browser:
            # yt-dlp expects a tuple-like value: (browser, profile?, keyring?, container?)
            options["cookiesfrombrowser"] = (self.cookies_from_browser,)
        return options

    def _summarize_error(self, exc: Exception) -> str:
        raw = str(exc).strip() or exc.__class__.__name__
        normalized = raw.lower()
        if any(marker in normalized for marker in YOUTUBE_BOT_CHALLENGE_MARKERS):
            return (
                "YouTube requested bot verification. "
                "Re-run with --cookies-file /path/to/youtube_cookies.txt "
                "or --cookies-from-browser <browser>."
            )
        return raw

    def _load_yt_dlp(self) -> Any:
        if self._yt_dlp is not None:
            return self._yt_dlp
        try:
            import yt_dlp
        except Exception as exc:  # pragma: no cover - dependency/environment specific
            raise RuntimeError(
                "yt-dlp is required. Install it with `pip install yt-dlp`."
            ) from exc
        self._yt_dlp = yt_dlp
        return self._yt_dlp

    def _load_whisper_model(self) -> Any:
        if self._whisper_model is not None:
            return self._whisper_model
        try:
            import whisper
        except Exception as exc:  # pragma: no cover - dependency/environment specific
            raise RuntimeError(
                "openai-whisper is required. Install it with `pip install openai-whisper`."
            ) from exc
        self._progress(f"Loading Whisper model: {self.whisper_model_name}")
        self._whisper_model = whisper.load_model(self.whisper_model_name, device=self.whisper_device)
        return self._whisper_model

    def _load_embedding_model(self) -> Any:
        if self._embedding_model is not None:
            return self._embedding_model
        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:  # pragma: no cover - dependency/environment specific
            raise RuntimeError(
                "sentence-transformers is required. Install it with `pip install sentence-transformers`."
            ) from exc
        self._progress(f"Loading embedding model: {self.embedding_model_name}")
        self._embedding_model = SentenceTransformer(self.embedding_model_name)
        return self._embedding_model
