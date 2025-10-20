import logging
import os
import whisper
from typing import Optional

logger = logging.getLogger(__name__)


class Transcriptor:
    """Responsible for transcribing audio using Whisper."""

    def __init__(self, model_name: str, language: str = "pt"):
        self.model_name = model_name
        self.language = language
        self._model: Optional[whisper.Whisper] = None

    @property
    def model(self) -> whisper.Whisper:
        """Loads the Whisper model lazily."""
        if self._model is None:
            logger.info(f"Loading Whisper model ({self.model_name})...")
            self._model = whisper.load_model(self.model_name, device="cpu")
        return self._model

    def transcribe(self, wav_file: str) -> str:
        """Transcribes the audio using Whisper."""
        if not os.path.exists(wav_file):
            raise FileNotFoundError(f"WAV file not found: {wav_file}")

        logger.info("Transcribing audio...")

        try:
            result = self.model.transcribe(
                wav_file,
                language=self.language,
                verbose=True
            )
        except Exception as e:
            raise RuntimeError(f"Transcription failed: {e}") from e

        segments = result["segments"]

        transcription_with_breaks = "\n".join(
            [segment['text'].strip() for segment in segments]
        )

        return transcription_with_breaks
