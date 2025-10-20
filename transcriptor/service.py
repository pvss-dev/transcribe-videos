import os
import tempfile

from .config import TranscriptionConfig
from .downloader import AudioDownloader
from .converter import AudioConverter
from .transcriptor import Transcriptor
from .file_manager import FileManager


class TranscriptionService:
    """Main service that orchestrates the transcription process."""

    def __init__(self, config: TranscriptionConfig):
        self.config = config
        self.downloader = AudioDownloader(config.audio_quality)
        self.converter = AudioConverter(config.sample_rate)
        self.transcriptor = Transcriptor(config.whisper_model, config.language)
        self.file_manager = FileManager()

    def process(self, path_or_url: str, output_file: str = "transcription.txt") -> str:
        """
        Processes an audio file or URL and returns the transcription.

        Args:
            path_or_url: Local path or YouTube URL
            output_file: Output file name

        Returns:
            Transcribed text
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            audio_file = self._get_audio_file(path_or_url, temp_dir)
            wav_file = os.path.join(temp_dir, "audio.wav")

            self.converter.convert_to_wav(audio_file, wav_file)
            text = self.transcriptor.transcribe(wav_file)
            self.file_manager.save_transcription(text, output_file)

            return text

    def _get_audio_file(self, path_or_url: str, temp_dir: str) -> str:
        """Gets the audio file, downloading if necessary."""
        if self.downloader.is_url(path_or_url):
            audio_base_path = os.path.join(temp_dir, "audio")

            self.downloader.download_from_youtube(path_or_url, audio_base_path)

            return audio_base_path + ".mp3"

        self.file_manager.validate_file(path_or_url)
        return path_or_url