import ffmpeg


class AudioConverter:
    """Responsible for converting audio formats."""

    def __init__(self, sample_rate: str = "16k"):
        self.sample_rate = sample_rate

    def convert_to_wav(self, input_file: str, output_file: str) -> None:
        """Converts any audio/video format to WAV."""
        print("🎼 Converting to WAV...")
        try:
            (
                ffmpeg
                .input(input_file)
                .output(
                    output_file,
                    format='wav',
                    acodec='pcm_s16le',
                    ac=1,
                    ar=self.sample_rate
                )
                .overwrite_output()
                .run(quiet=True, capture_stderr=True)
            )
        except ffmpeg.Error as e:
            raise RuntimeError(f"Error converting audio: {e.stderr.decode()}") from e
