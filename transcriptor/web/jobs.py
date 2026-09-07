"""In-memory job queue backing the web UI.

Whisper is fully synchronous, so each transcription runs on its own worker
thread and publishes events to every client watching that job. Each watcher
gets its own queue -- a single shared one would split the events between two
open tabs and hand the end-of-stream sentinel to only one of them.
"""

import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from ..config import TranscriptionConfig
from ..exceptions import TranscriptionCancelled

# Sentinel pushed onto a job's queue when no further events will arrive.
_DONE = object()

# Statuses after which a job emits no further events.
_TERMINAL = {"completed", "error", "cancelled"}

# How long a job waits for a free slot before giving up. Long enough to ride
# out a busy spell, short enough that a client is not held forever.
_QUEUE_TIMEOUT = 1800.0

# The wait for a slot is polled rather than blocking for the whole timeout, so
# a cancellation while queued is noticed in under a second instead of only when
# some other job finally frees the slot.
_SLOT_POLL = 0.5


@dataclass
class Job:
    """One transcription, its live state, and the queue feeding its SSE stream."""

    id: str
    # Which browser session queued this. Every job endpoint checks it, so one
    # visitor can never see, cancel or download another visitor's work.
    owner: str
    source_name: str
    local_path: str
    output_path: str
    config: TranscriptionConfig
    status: str = "queued"
    percent: float = 0.0
    seconds_done: Optional[float] = None
    seconds_total: Optional[float] = None
    uploaded_bytes: int = 0
    total_bytes: Optional[int] = None
    transcript_path: Optional[str] = None
    srt_path: Optional[str] = None
    transcript_preview: Optional[str] = None
    detected_language: Optional[str] = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)

    # Where this job is going to write, filled in before the work starts. A
    # retention sweep protects it for the whole run; `transcript_path` only
    # appears once the file is already on disk, moments before the job ends.
    target_path: Optional[str] = None

    _cancel: threading.Event = field(default_factory=threading.Event, repr=False)
    _streams: list[queue.Queue] = field(default_factory=list, repr=False)
    _streams_lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _closed: bool = field(default=False, repr=False)

    # ------------------------------------------------------------------
    # event fan-out
    # ------------------------------------------------------------------

    def subscribe(self) -> queue.Queue:
        """Open a private event stream for one watcher, ended by `_DONE`."""
        stream: queue.Queue = queue.Queue()
        with self._streams_lock:
            if self._closed:
                # The job ended before this watcher connected. Close its stream
                # at once rather than leaving it on keepalives forever.
                stream.put(_DONE)
            else:
                self._streams.append(stream)
        return stream

    def unsubscribe(self, stream: queue.Queue) -> None:
        with self._streams_lock:
            try:
                self._streams.remove(stream)
            except ValueError:
                pass

    def publish(self, event: Any) -> None:
        """Hand `event` to every watcher. `_DONE` closes the job for good."""
        with self._streams_lock:
            if self._closed:
                return
            if event is _DONE:
                self._closed = True
            streams = list(self._streams)
            if self._closed:
                self._streams.clear()
        for stream in streams:
            stream.put(event)

    def written_paths(self) -> list[str]:
        """Every file this job owns on disk, including ones not written yet."""
        paths = [self.transcript_path, self.srt_path]
        if self.target_path:
            paths.append(self.target_path)
            paths.append(str(Path(self.target_path).with_suffix(".srt")))
        return [p for p in paths if p]

    def snapshot(self) -> dict[str, Any]:
        """Serializable view of the job for the client."""
        return {
            "id": self.id,
            "source_name": self.source_name,
            "status": self.status,
            "percent": round(self.percent, 1),
            "seconds_done": self.seconds_done,
            "seconds_total": self.seconds_total,
            "model": self.config.whisper_model,
            "transcript_path": self.transcript_path,
            "has_srt": self.srt_path is not None,
            "transcript_preview": self.transcript_preview,
            "detected_language": self.detected_language,
            "error": self.error,
        }


class QuotaExceeded(Exception):
    """The session has queued more jobs than its allowance."""


class JobManager:
    """Creates, tracks and cancels transcription jobs.

    Concurrency is capped on purpose: a Whisper run pins a CPU core for
    minutes, so without a ceiling a handful of visitors would take the whole
    machine down.
    """

    def __init__(
            self,
            max_jobs: int = 200,
            max_concurrent: int = 1,
            max_jobs_per_session_hour: Optional[int] = None,
    ):
        self._jobs: dict[str, Job] = {}
        self._lock = threading.Lock()
        self._max_jobs = max_jobs
        self._slots = threading.Semaphore(max_concurrent)
        self._max_per_session_hour = max_jobs_per_session_hour

    # ------------------------------------------------------------------
    # lookup
    # ------------------------------------------------------------------

    def get(self, job_id: str, owner: Optional[str] = None) -> Optional[Job]:
        """Fetch a job. With `owner`, only that session's job is returned."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            return None
        if owner is not None and job.owner != owner:
            # Indistinguishable from "no such job", so ids cannot be probed.
            return None
        return job

    def all(self, owner: Optional[str] = None) -> list[Job]:
        with self._lock:
            found = [j for j in self._jobs.values() if owner is None or j.owner == owner]
        return sorted(found, key=lambda j: j.created_at, reverse=True)

    def active_paths(self) -> list[str]:
        """Files of jobs still running, which a sweep must not delete."""
        with self._lock:
            running = [j for j in self._jobs.values() if j.status not in _TERMINAL]
        return [path for job in running for path in job.written_paths()]

    # ------------------------------------------------------------------
    # lifecycle
    # ------------------------------------------------------------------

    def _register(self, job: Job) -> None:
        with self._lock:
            self._jobs[job.id] = job
            if len(self._jobs) > self._max_jobs:
                finished = sorted(
                    (j for j in self._jobs.values() if j.status in _TERMINAL),
                    key=lambda j: j.created_at,
                )
                for old in finished[: len(self._jobs) - self._max_jobs]:
                    self._jobs.pop(old.id, None)

    def _check_quota(self, owner: str) -> None:
        if self._max_per_session_hour is None:
            return
        cutoff = time.time() - 3600
        with self._lock:
            recent = sum(
                1 for j in self._jobs.values()
                if j.owner == owner and j.created_at > cutoff
            )
        if recent >= self._max_per_session_hour:
            raise QuotaExceeded(
                f"Limit of {self._max_per_session_hour} transcriptions per hour "
                "reached. Try again later."
            )

    def create(
            self,
            owner: str,
            local_path: str,
            source_name: str,
            output_path: str,
            config: TranscriptionConfig,
            total_bytes: Optional[int] = None,
    ) -> Job:
        self._check_quota(owner)
        job = Job(
            id=uuid.uuid4().hex[:12],
            owner=owner,
            source_name=source_name,
            local_path=local_path,
            output_path=output_path,
            config=config,
            total_bytes=total_bytes,
        )
        self._register(job)
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def cancel(self, job_id: str, owner: Optional[str] = None) -> bool:
        job = self.get(job_id, owner)
        if job is None or job.status in _TERMINAL:
            return False
        job._cancel.set()
        job.status = "cancelling"
        self._emit(job)
        return True

    def clear_finished(self, owner: Optional[str] = None) -> int:
        with self._lock:
            done = [
                j for j in self._jobs.values()
                if j.status in _TERMINAL and (owner is None or j.owner == owner)
            ]
            for job in done:
                self._jobs.pop(job.id, None)
        return len(done)

    # ------------------------------------------------------------------
    # events
    # ------------------------------------------------------------------

    def _emit(self, job: Job) -> None:
        job.publish(job.snapshot())

    def _finish(self, job: Job) -> None:
        job.publish(_DONE)

    # ------------------------------------------------------------------
    # worker
    # ------------------------------------------------------------------

    def _run(self, job: Job) -> None:
        from ..service import TranscriptionService
        from ..transcriber import TranscriptionProgress

        def on_progress(progress: "TranscriptionProgress") -> None:
            if job._cancel.is_set():
                raise TranscriptionCancelled()
            if progress.status == "loading_model":
                job.status = "loading_model"
            elif progress.status == "transcribing":
                job.status = "transcribing"
                if progress.percent is not None:
                    job.percent = progress.percent
                job.seconds_done = progress.seconds_done
                job.seconds_total = progress.seconds_total
            self._emit(job)

        # Known before the queue wait, so a retention sweep protects the file
        # this job is about to write even while it is still waiting its turn.
        job.target_path = str(Path(job.output_path) / f"{Path(job.source_name).stem}.txt")

        # Everything queues behind the global limit. The job stays visible as
        # "queued" meanwhile, so the page shows it waiting rather than nothing.
        if not self._wait_for_slot(job):
            if not job._cancel.is_set():
                job.error = "The server is busy; try again in a few minutes."
            self._finalize(job)
            return

        try:
            service = TranscriptionService(job.config, on_progress=on_progress)
            outcome = service.process(
                job.local_path,
                job.target_path,
                write_srt=True,
                # Keep the intermediate WAV next to the upload, so it is
                # removed with the rest of the upload directory.
                workdir=str(Path(job.local_path).parent),
            )

            if outcome.success:
                job.transcript_path = str(outcome.transcript_path)
                job.srt_path = str(outcome.srt_path) if outcome.srt_path else None
                if outcome.result:
                    job.detected_language = outcome.result.language
                    preview = outcome.result.text.strip().replace("\n", " ")
                    job.transcript_preview = preview[:300] + ("..." if len(preview) > 300 else "")
            else:
                job.error = outcome.error

        except TranscriptionCancelled:
            job.status = "cancelling"
        except Exception as e:
            job.error = f"{type(e).__name__}: {e}"
        finally:
            self._slots.release()
            self._finalize(job)

    def _wait_for_slot(self, job: Job) -> bool:
        """Hold the job until a worker slot frees up.

        Polls instead of blocking on one long `acquire`, so cancelling a job
        that is still queued takes effect immediately rather than whenever the
        job ahead of it happens to finish.
        """
        deadline = time.monotonic() + _QUEUE_TIMEOUT
        while not job._cancel.is_set():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            if self._slots.acquire(timeout=min(_SLOT_POLL, remaining)):
                return True
        return False

    def _finalize(self, job: Job) -> None:
        """Settle a job's terminal state and close its event stream."""
        # Discard the upload before marking the job terminal: a snapshot taken
        # in between would advertise a file that is about to vanish.
        self._discard_upload(job)

        if job.transcript_path:
            # The transcript exists. A cancellation that lands in this same
            # instant does not undo work already on disk.
            job.status = "completed"
            job.percent = 100.0
        elif job.status == "cancelling" or job._cancel.is_set():
            job.status = "cancelled"
            job.error = "Cancelled by user"
        elif job.error:
            job.status = "error"
        else:
            job.status = "completed"
            job.percent = 100.0

        self._emit(job)
        self._finish(job)

    @staticmethod
    def _discard_upload(job: Job) -> None:
        """The visitor already has the original; a copy here serves nobody."""
        try:
            upload = Path(job.local_path)
            upload.unlink(missing_ok=True)
            if upload.parent.is_dir() and not any(upload.parent.iterdir()):
                upload.parent.rmdir()
        except OSError:
            pass


def is_terminal(status: str) -> bool:
    return status in _TERMINAL
