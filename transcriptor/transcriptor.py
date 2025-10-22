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
        self.device = self._detect_device()

    @staticmethod
    def _detect_device() -> str:
        """Detects the best available device (CUDA GPU, MPS, or CPU)."""
        try:
            import torch

            # Check for NVIDIA CUDA GPU
            if torch.cuda.is_available():
                device = "cuda"
                gpu_name = torch.cuda.get_device_name(0)
                logger.info(f"Using GPU: {gpu_name}")
                return device

            # Check for Apple Silicon GPU (MPS)
            if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
                logger.info("Using Apple Silicon GPU (MPS)")
                return device

            # Fallback to CPU
            logger.info("GPU not available. Using CPU (this will be slower)")
            return "cpu"

        except ImportError:
            logger.warning("PyTorch not found. Using CPU")
            return "cpu"
        except Exception as e:
            logger.warning(f"Error detecting device: {e}. Using CPU")
            return "cpu"

    @property
    def model(self) -> whisper.Whisper:
        """Loads the Whisper model lazily."""
        if self._model is None:
            logger.info(f"Loading Whisper model ({self.model_name}) on {self.device.upper()}...")
            try:
                self._model = whisper.load_model(self.model_name, device=self.device)
                logger.info("Model loaded successfully")
            except Exception as e:
                if self.device != "cpu":
                    logger.warning(f"Failed to load on {self.device}, falling back to CPU")
                    self.device = "cpu"
                    self._model = whisper.load_model(self.model_name, device="cpu")
                else:
                    raise
        return self._model

    def transcribe(self, wav_file: str) -> str:
        """Transcribes the audio using Whisper."""
        if not os.path.exists(wav_file):
            raise FileNotFoundError(f"WAV file not found: {wav_file}")

        logger.info(f"Transcribing audio using {self.device.upper()}...")

        try:
            result = self.model.transcribe(
                wav_file,
                language=self.language,
                verbose=False
            )
        except Exception as e:
            raise RuntimeError(f"Transcription failed: {e}") from e

        segments = result["segments"]

        transcription_with_breaks = "\n".join(
            [segment['text'].strip() for segment in segments]
        )

        logger.info("Transcription completed!")
        return transcription_with_breaks
