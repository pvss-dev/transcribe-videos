from dataclasses import dataclass


@dataclass
class TranscriptionConfig:
    """Configuration for the transcription process."""
    whisper_model: str = "small"
    language: str = "pt"
    audio_quality: str = "192"
    sample_rate: str = "16k"
