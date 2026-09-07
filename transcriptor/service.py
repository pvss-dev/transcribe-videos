import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import TranscriptionConfig
from .converter import AudioConverter
from .exceptions import TranscriptionError
from .transcriber import TranscribeProgress, Transcriber, TranscriptionResult

logger = logging.getLogger(__name__)


@dataclass
class TranscriptionOutcome:
    """What a full media -> transcript run produced."""

    success: bool
    result: Optional[TranscriptionResult] = None
    transcript_path: Optional[Path] = None
    srt_path: Optional[Path] = None
    error: Optional[str] = None


class TranscriptionService:
    """Turns a local media file into a transcript.

    Deliberately has no downloader: this service only ever reads files that
    are already on disk. Fetching from YouTube would drag in yt-dlp and, on a
    datacenter IP, fail the bot check on most videos anyway.
    """

    def __init__(
            self,
            config: Optional[TranscriptionConfig] = None,
            on_progress: Optional[TranscribeProgress] = None,
    ):
        self.config = config or TranscriptionConfig()
        self.converter = AudioConverter(self.config.sample_rate)
        self.transcriber = Transcriber(self.config, on_progress=on_progress)

    def process(
            self,
            source: str | Path,
            output_file: Optional[str | Path] = None,
            write_srt: bool = False,
            workdir: Optional[str | Path] = None,
    ) -> TranscriptionOutcome:
        """Convert, transcribe and save.

        Args:
            source: Media file to transcribe.
            output_file: Where to write the transcript. Defaults to the source
                path with a .txt suffix.
            write_srt: Also write a .srt beside the transcript.
            workdir: Where the intermediate WAV goes. Defaults beside the
                source, which is where an uploaded file already lives.
        """
        try:
            source = Path(source).expanduser()
            if not source.exists():
                raise TranscriptionError(f"File not found: {source}")
            if not source.is_file():
                raise TranscriptionError(f"Path is not a file: {source}")

            scratch = Path(workdir).expanduser() if workdir else source.parent
            scratch.mkdir(parents=True, exist_ok=True)
            wav = scratch / f"{source.stem}.__whisper.wav"

            try:
                self.converter.convert_to_wav(source, wav)
                result = self.transcriber.transcribe(wav)
            finally:
                # The WAV is several times the size of the source; never leave
                # it behind, even when the transcription fails.
                wav.unlink(missing_ok=True)

            target = Path(output_file).expanduser() if output_file else source.with_suffix(".txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(result.text, encoding="utf-8")
            logger.info(f"Transcript saved at: {target}")

            srt_path = None
            if write_srt:
                srt_path = target.with_suffix(".srt")
                srt_path.write_text(result.as_srt(), encoding="utf-8")
                logger.info(f"Subtitles saved at: {srt_path}")

            return TranscriptionOutcome(
                success=True, result=result, transcript_path=target, srt_path=srt_path,
            )

        except TranscriptionError as e:
            logger.error(f"Transcription failed: {e}")
            return TranscriptionOutcome(success=False, error=str(e))
        except Exception as e:
            logger.exception("Unexpected error during transcription")
            return TranscriptionOutcome(success=False, error=f"{type(e).__name__}: {e}")
