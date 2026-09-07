"""FastAPI server exposing the transcriber to the browser."""

import asyncio
import json
import logging
import os
import queue
import secrets
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from ..config import WHISPER_MODELS, TranscriptionConfig
from ..retention import RetentionPolicy, RetentionScheduler
from ..transcriber import Transcriber
from .jobs import _DONE, JobManager, QuotaExceeded

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Where transcripts are written. Never taken from the client.
OUTPUT_DIR = Path(os.getenv("TRANSCRIPTOR_OUTPUT", "./transcripts")).expanduser()

# Media the browser uploads lands here until its job finishes.
UPLOAD_ROOT = Path(tempfile.gettempdir()) / "transcriptor-uploads"

# Keep in step with client_max_body_size in the nginx config, which must
# sit just above this: nginx checks Content-Length and rejects instantly,
# while a limit only enforced here would let the whole file upload first.
MAX_UPLOAD_BYTES = int(os.getenv("TRANSCRIPTOR_MAX_UPLOAD_MB", "500")) * 1024 * 1024
CHUNK = 1024 * 1024

SESSION_COOKIE = "transcriptor_session"

app = FastAPI(title="Transcriptor", version="2.0.0")

jobs = JobManager(
    max_concurrent=int(os.getenv("TRANSCRIPTOR_MAX_CONCURRENT", "1")),
    max_jobs_per_session_hour=(
        int(os.getenv("TRANSCRIPTOR_JOBS_PER_HOUR", "0")) or None
    ),
)

# Set by run() when the operator asks for automatic cleanup; stays None
# otherwise, so no file is ever deleted unless requested.
retention: Optional[RetentionScheduler] = None


def session_of(request: Request) -> str:
    """The caller's session id, from the cookie set by the middleware."""
    return request.cookies.get(SESSION_COOKIE) or request.state.session


@app.middleware("http")
async def attach_session(request: Request, call_next):
    """Give every visitor an opaque id, so jobs can be scoped to them.

    This is ownership, not authentication: it stops one visitor seeing or
    cancelling another's transcriptions. It does not identify anybody.
    """
    existing = request.cookies.get(SESSION_COOKIE)
    request.state.session = existing or secrets.token_urlsafe(24)

    response = await call_next(request)

    if not existing:
        response.set_cookie(
            SESSION_COOKIE,
            request.state.session,
            max_age=60 * 60 * 24 * 30,
            httponly=True,
            samesite="lax",
        )
    return response


# ----------------------------------------------------------------------
# meta
# ----------------------------------------------------------------------

@app.get("/api/health")
async def health() -> dict:
    return {
        "status": "ok",
        "transcription_available": Transcriber.is_available(),
        "whisper_models": list(WHISPER_MODELS),
        "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
        "retention": retention.policy.describe() if retention else None,
    }


# ----------------------------------------------------------------------
# uploads
# ----------------------------------------------------------------------

@app.post("/api/transcribe")
async def upload_and_transcribe(
        request: Request,
        file: UploadFile = File(...),
        whisper_model: str = Form("small"),
        language: str = Form("pt"),
) -> dict:
    """Accept a media file from the browser and transcribe it."""
    if not Transcriber.is_available():
        raise HTTPException(
            status_code=503,
            detail="Transcription is not installed on this server.",
        )

    try:
        config = TranscriptionConfig(
            whisper_model=whisper_model,
            # An empty language means "let Whisper detect it".
            language=language or None,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    # Keep only the basename: a browser may send a path, and "../" in it must
    # never escape the upload directory.
    source_name = Path(file.filename or "upload").name
    if not source_name or source_name in (".", ".."):
        source_name = "upload"

    workdir = UPLOAD_ROOT / uuid.uuid4().hex[:12]
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / source_name

    written = 0
    try:
        with target.open("wb") as sink:
            while chunk := await file.read(CHUNK):
                written += len(chunk)
                if written > MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is larger than {MAX_UPLOAD_BYTES // (1024**2)} MB",
                    )
                sink.write(chunk)
    except HTTPException:
        shutil.rmtree(workdir, ignore_errors=True)
        raise
    except OSError as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Could not store upload: {e}") from e
    finally:
        await file.close()

    if written == 0:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="The uploaded file is empty")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        job = jobs.create(
            owner=session_of(request),
            local_path=str(target),
            source_name=source_name,
            output_path=str(OUTPUT_DIR.resolve()),
            config=config,
            total_bytes=written,
        )
    except QuotaExceeded as e:
        shutil.rmtree(workdir, ignore_errors=True)
        raise HTTPException(status_code=429, detail=str(e)) from e

    return job.snapshot()


# ----------------------------------------------------------------------
# jobs
# ----------------------------------------------------------------------

@app.get("/api/jobs")
async def list_jobs(request: Request) -> dict:
    return {"jobs": [job.snapshot() for job in jobs.all(session_of(request))]}


@app.delete("/api/jobs")
async def clear_jobs(request: Request) -> dict:
    return {"cleared": jobs.clear_finished(session_of(request))}


@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request) -> dict:
    if not jobs.cancel(job_id, session_of(request)):
        raise HTTPException(status_code=404, detail="Job not found or already finished")
    return {"cancelled": True}


def _serve(job_id: str, request: Request, attribute: str, media_type: str) -> FileResponse:
    job = jobs.get(job_id, session_of(request))
    path = getattr(job, attribute, None) if job else None
    if not path:
        raise HTTPException(status_code=404, detail="Not available")

    resolved = Path(path)
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File no longer on disk")

    return FileResponse(resolved, filename=resolved.name, media_type=media_type)


@app.get("/api/jobs/{job_id}/transcript")
async def download_transcript(job_id: str, request: Request) -> FileResponse:
    return _serve(job_id, request, "transcript_path", "text/plain; charset=utf-8")


@app.get("/api/jobs/{job_id}/subtitles")
async def download_subtitles(job_id: str, request: Request) -> FileResponse:
    return _serve(job_id, request, "srt_path", "application/x-subrip")


@app.get("/api/jobs/{job_id}/events")
async def job_events(job_id: str, request: Request) -> StreamingResponse:
    """Server-sent events carrying live progress for one job."""
    job = jobs.get(job_id, session_of(request))
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    # Subscribe before the response starts: an event published between the
    # lookup above and the first read would otherwise be lost.
    stream = job.subscribe()

    async def event_stream():
        try:
            # Send current state immediately so a late subscriber isn't blank.
            yield f"data: {json.dumps(job.snapshot())}\n\n"

            while True:
                try:
                    event = await asyncio.to_thread(stream.get, True, 15)
                except queue.Empty:
                    # Comment frame keeps proxies from closing an idle connection.
                    yield ": keepalive\n\n"
                    continue

                if event is _DONE:
                    yield f"event: done\ndata: {json.dumps(job.snapshot())}\n\n"
                    return

                yield f"data: {json.dumps(event)}\n\n"
        finally:
            job.unsubscribe(stream)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")


def run(
        host: str = "127.0.0.1",
        port: int = 8000,
        reload: bool = False,
        retention_policy: Optional[RetentionPolicy] = None,
        retention_interval_minutes: float = 60.0,
) -> None:
    """Entry point used by `python -m transcriptor.web`."""
    import uvicorn

    global retention

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
    )

    if retention_policy is not None and retention_policy.is_active:
        retention = RetentionScheduler(
            directory=OUTPUT_DIR,
            policy=retention_policy,
            interval_seconds=retention_interval_minutes * 60,
            protected_paths=jobs.active_paths,
        )
        retention.start()

    print(f"\n  Transcriptor  ->  http://{host}:{port}\n")
    uvicorn.run(
        "transcriptor.web.server:app" if reload else app,
        host=host,
        port=port,
        reload=reload,
        log_level="warning",
    )
