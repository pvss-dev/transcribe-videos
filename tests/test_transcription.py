import subprocess
from pathlib import Path

import pytest

from transcriptor.exceptions import TranscriptionError, WhisperNotInstalled
from transcriptor import (
    AudioConverter,
    TranscriptionConfig,
    TranscriptionService,
)
from transcriptor.transcriber import (
    Transcriber,
    TranscriptionProgress,
    TranscriptionResult,
)


# --------------------------- config ---------------------------

def test_rejects_unknown_model():
    with pytest.raises(ValueError, match="Unknown Whisper model"):
        TranscriptionConfig(whisper_model="enormous")


def test_turbo_cannot_translate():
    """Whisper's turbo model has no translation task; fail early, not mid-run."""
    with pytest.raises(ValueError, match="cannot translate"):
        TranscriptionConfig(whisper_model="turbo", task="translate")

    # ...but turbo transcribing is fine, and medium may translate.
    TranscriptionConfig(whisper_model="turbo")
    TranscriptionConfig(whisper_model="medium", task="translate")


def test_language_may_be_none_for_autodetect():
    assert TranscriptionConfig(language=None).language is None


# --------------------------- converter ---------------------------

def test_converter_reports_missing_ffmpeg(monkeypatch, tmp_path):
    def boom(*args, **kwargs):
        raise FileNotFoundError("ffmpeg")

    monkeypatch.setattr(subprocess, "run", boom)
    with pytest.raises(TranscriptionError, match="ffmpeg not found"):
        AudioConverter().convert_to_wav(tmp_path / "in.mp4", tmp_path / "out.wav")


def test_converter_surfaces_ffmpeg_failure(monkeypatch, tmp_path):
    class Failed:
        returncode = 1
        stderr = "some/file.mp4: Invalid data found when processing input"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Failed())
    with pytest.raises(TranscriptionError, match="Invalid data found"):
        AudioConverter().convert_to_wav(tmp_path / "in.mp4", tmp_path / "out.wav")


def test_converter_targets_mono_16bit(monkeypatch, tmp_path):
    """Whisper expects 16 kHz mono PCM; the flags must say so."""
    captured = {}

    class Ok:
        returncode = 0
        stderr = ""

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        out = Path(cmd[cmd.index("-y") + 1])
        out.write_bytes(b"RIFFfake")
        return Ok()

    monkeypatch.setattr(subprocess, "run", fake_run)
    AudioConverter(sample_rate="16k").convert_to_wav(tmp_path / "in.mp4", tmp_path / "out.wav")

    cmd = captured["cmd"]
    assert cmd[cmd.index("-ac") + 1] == "1"
    assert cmd[cmd.index("-ar") + 1] == "16k"
    assert cmd[cmd.index("-acodec") + 1] == "pcm_s16le"
    assert "-vn" in cmd


# --------------------------- results ---------------------------

def test_srt_rendering_uses_comma_milliseconds():
    result = TranscriptionResult(
        text="ok",
        segments=[
            {"start": 0.0, "end": 2.5, "text": " Hello there "},
            {"start": 2.5, "end": 3661.25, "text": "Later"},
            {"start": 5.0, "end": 6.0, "text": "   "},  # blank: skipped
        ],
    )
    srt = result.as_srt()

    assert "00:00:00,000 --> 00:00:02,500" in srt
    assert "01:01:01,250" in srt
    assert "Hello there" in srt
    assert srt.count("-->") == 2


# --------------------------- progress ---------------------------

def test_progress_dataclass_carries_position():
    p = TranscriptionProgress("transcribing", percent=42.0, seconds_done=21, seconds_total=50)
    assert p.percent == 42.0
    assert p.seconds_done == 21


def test_transcriber_reports_whisper_missing(monkeypatch):
    """Without the extra installed, the error must say how to install it."""
    import builtins

    real_import = builtins.__import__

    def no_whisper(name, *args, **kwargs):
        if name == "whisper":
            raise ImportError("No module named 'whisper'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_whisper)

    assert Transcriber.is_available() is False
    with pytest.raises(WhisperNotInstalled, match="requirements-transcribe"):
        Transcriber()._require_whisper()


def test_announces_a_first_time_model_download(monkeypatch, caplog):
    """A bare 461 MB tqdm bar with no explanation looks like a hang."""
    import logging

    fake_whisper = type("W", (), {
        "_MODELS": {"small": "https://example/small.pt"},
        "load_model": staticmethod(lambda *a, **k: object()),
    })()
    monkeypatch.setattr(Transcriber, "_require_whisper", staticmethod(lambda: fake_whisper))
    monkeypatch.setattr(Transcriber, "_detect_device", staticmethod(lambda: "cpu"))

    t = Transcriber(TranscriptionConfig(whisper_model="small"))

    monkeypatch.setattr(Transcriber, "_model_is_cached", staticmethod(lambda w, n: False))
    with caplog.at_level(logging.INFO):
        t._model = None
        t.load_model()
    assert any("one time only" in r.message for r in caplog.records)

    # ...and stays quiet once the weights are on disk.
    caplog.clear()
    monkeypatch.setattr(Transcriber, "_model_is_cached", staticmethod(lambda w, n: True))
    with caplog.at_level(logging.INFO):
        t._model = None
        t.load_model()
    assert not any("one time only" in r.message for r in caplog.records)


def test_model_cache_check_never_blocks_loading(monkeypatch):
    """A broken cache probe must not stop a transcription."""
    broken = type("W", (), {})()  # no _MODELS attribute
    assert Transcriber._model_is_cached(broken, "small") is True


# --------------------------- service ---------------------------

def test_missing_local_file_is_reported(tmp_path):
    outcome = TranscriptionService().process(str(tmp_path / "nope.mp4"))
    assert outcome.success is False
    assert "File not found" in outcome.error


def test_directory_is_not_a_valid_source(tmp_path):
    outcome = TranscriptionService().process(str(tmp_path))
    assert outcome.success is False
    assert "not a file" in outcome.error




# --------------------------- cancellation ---------------------------

def test_cancelling_is_not_reported_as_a_failure(tmp_path):
    """A cancel raised from the progress callback is control flow, not an error.

    Transcriber.transcribe wraps everything the model raises into a
    TranscriptionError; without an explicit carve-out, a cancelled job would
    surface as "Transcription failed" instead of "cancelled".
    """
    from transcriptor.exceptions import TranscriptionCancelled

    class CancellingModel:
        def transcribe(self, path, **kwargs):
            raise TranscriptionCancelled()

    wav = tmp_path / "a.wav"
    wav.write_bytes(b"RIFFfake")

    t = Transcriber()
    t._model = CancellingModel()
    t._device = "cpu"

    with pytest.raises(TranscriptionCancelled):
        t.transcribe(wav)

    # ...while a real failure still becomes a TranscriptionError.
    class BrokenModel:
        def transcribe(self, path, **kwargs):
            raise RuntimeError("out of memory")

    t._model = BrokenModel()
    with pytest.raises(TranscriptionError, match="out of memory"):
        t.transcribe(wav)


def test_the_service_lets_a_cancel_through(tmp_path, monkeypatch):
    """process() must not turn a cancel into a failed outcome either."""
    from transcriptor.exceptions import TranscriptionCancelled

    media = tmp_path / "a.mp4"
    media.write_bytes(b"fake")

    service = TranscriptionService()
    monkeypatch.setattr(service.converter, "convert_to_wav",
                        lambda src, dst: Path(dst).write_bytes(b"RIFF") or Path(dst))

    def cancel(_):
        raise TranscriptionCancelled()

    monkeypatch.setattr(service.transcriber, "transcribe", cancel)

    with pytest.raises(TranscriptionCancelled):
        service.process(media)
