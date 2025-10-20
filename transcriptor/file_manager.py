import os


class FileManager:
    """Responsible for managing files and saving."""

    @staticmethod
    def validate_file(path: str) -> None:
        """Validates if the file exists and is accessible."""
        if not os.path.exists(path):
            raise FileNotFoundError(f"File not found: {path}")
        if not os.path.isfile(path):
            raise ValueError(f"Path is not a file: {path}")

    @staticmethod
    def save_transcription(text: str, output_file: str = "transcription.txt") -> None:
        """Saves the transcription to a file."""
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"\n✅ Transcription completed!")
        print(f"📄 File saved at: {output_file}")
