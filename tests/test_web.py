import json
import threading
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from transcriptor.transcriber import TranscriptionProgress, TranscriptionResult
from transcriptor.web import server


@pytest.fixture
def client():
    server.jobs.clear_finished()
    return TestClient(server.app)


@pytest.fixture
def other_client():
    """A second visitor: each TestClient keeps its own cookie jar."""
    return TestClient(server.app)


@pytest.fixture
def fake_whisper(monkeypatch, tmp_path):
    """Replace Whisper with a stub, so tests never load a model."""
    monkeypatch.setattr(server.Transcriber, "is_available", staticmethod(lambda: True))
    monkeypatch.setattr(server, "OUTPUT_DIR", tmp_path / "transcripts")

    gate = threading.Event()
    gate.set()

    class FakeService:
        release = gate

        def __init__(self, config, on_progress=None):
            self.on_progress = on_progress

        def process(self, source, output_file=None, write_srt=False, workdir=None):
            from transcriptor.service import TranscriptionOutcome

            gate.wait(timeout=5)
            self.on_progress(TranscriptionProgress("loading_model", model="tiny"))
            self.on_progress(TranscriptionProgress(
                "transcribing", percent=100.0, seconds_done=90, seconds_total=90))

            target = Path(output_file)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("texto transcrito", encoding="utf-8")
            srt = target.with_suffix(".srt")
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nolá\n", encoding="utf-8")

            return TranscriptionOutcome(
                success=True,
                result=TranscriptionResult(text="texto transcrito", language="pt"),
                transcript_path=target,
                srt_path=srt,
            )

    monkeypatch.setattr("transcriptor.service.TranscriptionService", FakeService)
    return FakeService


def upload(client, name="aula.mp4", content=b"fake media", **fields):
    return client.post(
        "/api/transcribe",
        files={"file": (name, content, "video/mp4")},
        data=fields,
    )


def drain(client, job_id, release=None):
    events = []
    with client.stream("GET", f"/api/jobs/{job_id}/events") as response:
        for line in response.iter_lines():
            if not line.startswith("data:"):
                continue
            events.append(json.loads(line[5:].strip()))
            if release is not None:
                release.set()
            if events[-1]["status"] in ("completed", "error", "cancelled"):
                break
    return events


# --------------------------- basics ---------------------------

def test_health(client):
    body = client.get("/api/health").json()
    assert body["status"] == "ok"
    assert "small" in body["whisper_models"]
    assert body["max_upload_mb"] > 0


def test_static_assets_are_served(client):
    assert client.get("/").status_code == 200
    assert "text/css" in client.get("/style.css").headers["content-type"]
    assert client.get("/app.js").status_code == 200


def test_there_is_no_download_endpoint():
    """This service never fetches from YouTube; the routes must not exist.

    Checked against the router rather than by status code: the static mount
    at "/" answers unknown POSTs with 405, which would pass a status check
    even if the route were somehow present.
    """
    paths = {getattr(r, "path", "") for r in server.app.routes}
    assert not any("download" in p or "info" in p for p in paths)


def test_the_package_carries_no_yt_dlp_dependency():
    import transcriptor

    assert not hasattr(transcriptor, "VideoDownloader")
    with pytest.raises(ImportError):
        __import__("transcriptor.downloader")


# --------------------------- upload ---------------------------

def test_upload_transcribes_and_saves_both_files(client, fake_whisper, tmp_path):
    fake_whisper.release.clear()
    job = upload(client, "aula gravada.mp4", whisper_model="tiny", language="pt").json()
    assert job["source_name"] == "aula gravada.mp4"

    events = drain(client, job["id"], release=fake_whisper.release)
    statuses = [e["status"] for e in events]
    assert "loading_model" in statuses
    assert "transcribing" in statuses

    final = events[-1]
    assert final["status"] == "completed"
    assert final["detected_language"] == "pt"
    assert final["has_srt"] is True
    assert "texto transcrito" in final["transcript_preview"]

    saved = Path(final["transcript_path"])
    assert saved.name == "aula gravada.txt"
    assert saved.read_text(encoding="utf-8") == "texto transcrito"


def test_both_artifacts_are_downloadable(client, fake_whisper):
    job = upload(client).json()
    drain(client, job["id"])

    txt = client.get(f"/api/jobs/{job['id']}/transcript")
    assert txt.status_code == 200
    assert "texto transcrito" in txt.text

    srt = client.get(f"/api/jobs/{job['id']}/subtitles")
    assert srt.status_code == 200
    assert "-->" in srt.text


def test_uploaded_media_is_deleted_afterwards(client, fake_whisper):
    job = upload(client).json()
    stored = Path(server.jobs.get(job["id"]).local_path)

    final = drain(client, job["id"])[-1]

    assert final["status"] == "completed"
    assert not stored.exists(), "the uploaded copy must not linger on the server"
    assert not stored.parent.exists()


def test_filename_directories_are_stripped(client, fake_whisper):
    """A crafted filename must not write outside the upload directory."""
    job = upload(client, "../../../../tmp/evil.mp4").json()
    assert job["source_name"] == "evil.mp4"
    stored = Path(server.jobs.get(job["id"]).local_path)
    assert stored.parent.parent == server.UPLOAD_ROOT


def test_empty_file_is_rejected(client, fake_whisper):
    response = upload(client, "empty.mp4", content=b"")
    assert response.status_code == 400
    assert "empty" in response.json()["detail"].lower()


def test_unknown_model_is_rejected(client, fake_whisper):
    response = upload(client, whisper_model="gigantic")
    assert response.status_code == 400
    assert "Unknown Whisper model" in response.json()["detail"]


def test_upload_refused_when_whisper_is_missing(client, monkeypatch):
    monkeypatch.setattr(server.Transcriber, "is_available", staticmethod(lambda: False))
    response = upload(client)
    assert response.status_code == 503


def test_oversized_upload_is_rejected(client, fake_whisper, monkeypatch):
    monkeypatch.setattr(server, "MAX_UPLOAD_BYTES", 10)
    response = upload(client, content=b"x" * 5000)
    assert response.status_code == 413


# --------------------------- session isolation ---------------------------

def test_visitors_do_not_see_each_others_jobs(client, other_client, fake_whisper):
    mine = upload(client).json()
    drain(client, mine["id"])

    assert [j["id"] for j in client.get("/api/jobs").json()["jobs"]] == [mine["id"]]
    assert other_client.get("/api/jobs").json()["jobs"] == []


def test_a_visitor_cannot_reach_another_visitors_job(client, other_client, fake_whisper):
    mine = upload(client).json()
    drain(client, mine["id"])

    # 404, not 403: a stranger must not learn the job even exists.
    for path in ("transcript", "subtitles", "events"):
        assert other_client.get(f"/api/jobs/{mine['id']}/{path}").status_code == 404
    assert other_client.post(f"/api/jobs/{mine['id']}/cancel").status_code == 404


def test_clearing_only_removes_your_own_jobs(client, other_client, fake_whisper):
    mine = upload(client).json()
    theirs = upload(other_client).json()
    drain(client, mine["id"])
    drain(other_client, theirs["id"])

    assert other_client.delete("/api/jobs").json()["cleared"] == 1
    assert server.jobs.get(mine["id"]) is not None
    assert server.jobs.get(theirs["id"]) is None


# --------------------------- quota ---------------------------

def test_quota_is_per_session(client, other_client, fake_whisper, monkeypatch):
    from transcriptor.web.jobs import JobManager

    monkeypatch.setattr(server, "jobs", JobManager(max_jobs_per_session_hour=1))

    assert upload(client).status_code == 200
    flooded = upload(client)
    assert flooded.status_code == 429
    assert "per hour" in flooded.json()["detail"]

    # A different visitor still has their own allowance.
    assert upload(other_client).status_code == 200


def test_a_rejected_upload_leaves_no_file_behind(client, fake_whisper, monkeypatch):
    from transcriptor.web.jobs import JobManager

    monkeypatch.setattr(server, "jobs", JobManager(max_jobs_per_session_hour=1))

    # Let the first job finish and clean up, so the count below is stable.
    first = upload(client).json()
    drain(client, first["id"])
    before = set(server.UPLOAD_ROOT.glob("*")) if server.UPLOAD_ROOT.exists() else set()

    rejected = upload(client)
    assert rejected.status_code == 429

    after = set(server.UPLOAD_ROOT.glob("*")) if server.UPLOAD_ROOT.exists() else set()
    assert after == before, "a rejected upload must not leave its bytes on disk"
