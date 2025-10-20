import sys

from .config import TranscriptionConfig
from .service import TranscriptionService


def main():
    """Main CLI function."""
    if len(sys.argv) < 2:
        print("Usage: python -m transcriptor <video_path_or_url> [output_file]")
        print("\nExamples:")
        print("  python -m transcriptor video.mp4")
        print("  python -m transcriptor https://youtube.com/watch?v=... result.txt")
        sys.exit(1)

    path_or_url = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "transcription.txt"

    try:
        config = TranscriptionConfig()
        service = TranscriptionService(config)
        service.process(path_or_url, output_file)
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
