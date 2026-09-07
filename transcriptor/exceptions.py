class TranscriptorError(Exception):
    """Base exception for this package."""


class TranscriptionError(TranscriptorError):
    """Error converting or transcribing audio."""


class TranscriptionCancelled(TranscriptorError):
    """Raised from a progress callback to abort a run in flight.

    Deliberately NOT a TranscriptionError: it is control flow, not a failure,
    and Transcriber.transcribe must let it through instead of reporting the
    job as broken.
    """


class WhisperNotInstalled(TranscriptionError):
    """Whisper (and PyTorch) are an optional extra that is not installed."""

    MESSAGE = (
        "Transcription needs Whisper, which is an optional extra.\n"
        "Install it with:  pip install -r requirements-transcribe.txt\n"
        "On a machine without an NVIDIA GPU, install the smaller CPU-only "
        "PyTorch first:\n"
        "  pip install torch --index-url https://download.pytorch.org/whl/cpu"
    )

    def __init__(self, message: str | None = None):
        super().__init__(message or self.MESSAGE)


class DirectoryError(TranscriptorError):
    """Error creating or accessing a directory."""
