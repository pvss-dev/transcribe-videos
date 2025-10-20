# 🎙️ Transcriptor

A Python tool for transcribing audio and video files using OpenAI's Whisper model. Supports local files and YouTube
URLs.

## ✨ Features

- 🎬 **YouTube Support**: Download and transcribe videos directly from YouTube
- 📁 **Local Files**: Process audio/video files from your computer
- 🧠 **Multiple Models**: Choose from Whisper's tiny, base, small, medium, large, or turbo models
- 🌍 **Multi-language**: Default Portuguese (pt), but supports multiple languages
- 🔄 **Auto-conversion**: Automatically converts any audio/video format to WAV
- 📝 **Clean Output**: Formatted transcription with proper line breaks

## 📋 Requirements

### System Dependencies

You need **FFmpeg** installed on your system:

#### Linux

```bash
sudo apt update
sudo apt install ffmpeg
```

#### macOS

```bash
brew install ffmpeg
```

#### Windows

Download from [ffmpeg.org](https://ffmpeg.org/download.html) and add to PATH.

### Python Version

- Python 3.8 or higher

## 🚀 Installation

1. **Clone the repository**

```bash
git clone https://github.com/pvss-dev/transcribe-videos
cd transcribe-videos
```

2. **Create a virtual environment**

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. **Install dependencies**

```bash
pip install -r requirements.txt
```

## 💻 Usage

### Basic Usage

**Transcribe a local file:**

```bash
python -m transcriptor video.mp4
```

**Transcribe from YouTube:**

```bash
python -m transcriptor "https://youtube.com/watch?v=VIDEO_ID"
```

**Specify output file:**

```bash
python -m transcriptor video.mp4 my_transcription.txt
```

### Using as a Python Module

```python
from transcriptor import TranscriptionConfig, TranscriptionService

# Create configuration
config = TranscriptionConfig(
    whisper_model="small",  # Options: tiny, base, small, medium, large, turbo
    language="pt",  # Language code (pt, en, es, etc.)
    audio_quality="192",  # Audio quality for downloads
    sample_rate="16k"  # Sample rate for processing
)

# Create service and process
service = TranscriptionService(config)
text = service.process("video.mp4", "output.txt")
print(text)
```

## ⚙️ Configuration

### Whisper Models

| Model  | Parameters | Required VRAM | Relative Speed | Best For                  |
|--------|------------|---------------|----------------|---------------------------|
| tiny   | 39 M       | ~1 GB         | ~10x           | Quick tests, fast results |
| base   | 74 M       | ~1 GB         | ~7x            | Fast processing           |
| small  | 244 M      | ~2 GB         | ~4x            | **Recommended balance**   |
| medium | 769 M      | ~5 GB         | ~2x            | High quality              |
| large  | 1550 M     | ~10 GB        | 1x             | Best quality              |
| turbo  | 809 M      | ~6 GB         | **~8x**        | **Fast + great quality**  |

> **Important Notes:**
> - Speeds are relative to the `large` model measured on A100 GPU
> - The `turbo` model is an optimized version of `large-v3` offering faster transcription with minimal quality loss
> - **The `turbo` model does NOT support translation tasks**. For translating non-English audio to English, use `medium`
    or `large` models instead
> - `.en` models (English-only) perform better for English transcription but are not yet supported in this tool

### Supported Languages

The tool supports all languages available in Whisper, including:

- Portuguese (pt)
- English (en)
- Spanish (es)
- French (fr)
- German (de)
- Japanese (ja)
- Chinese (zh)
- [And many more...](https://github.com/openai/whisper#available-models-and-languages)

See [Whisper's tokenizer.py](https://github.com/openai/whisper/blob/main/whisper/tokenizer.py) for the complete list.

## 📁 Project Structure

```
transcriptor/
├── __init__.py          # Package initialization
├── __main__.py          # CLI entry point
├── config.py            # Configuration dataclass
├── service.py           # Main orchestration service
├── transcriptor.py      # Whisper transcription logic
├── downloader.py        # YouTube download functionality
├── converter.py         # Audio format conversion
└── file_manager.py      # File operations and saving
```

## 🔧 Advanced Usage

### Custom Configuration

```python
from transcriptor import TranscriptionConfig, TranscriptionService

# High-quality transcription
config = TranscriptionConfig(
    whisper_model="large",
    language="en",
    audio_quality="320",
    sample_rate="44.1k"
)

service = TranscriptionService(config)
service.process("podcast.mp3", "transcription.txt")
```

### Processing Multiple Files

```python
from transcriptor import TranscriptionConfig, TranscriptionService

config = TranscriptionConfig()
service = TranscriptionService(config)

files = ["video1.mp4", "video2.mp4", "audio.mp3"]

for file in files:
    output = file.replace(".mp4", ".txt").replace(".mp3", ".txt")
    print(f"Processing {file}...")
    service.process(file, output)
```

### Fast Transcription with Turbo

```python
from transcriptor import TranscriptionConfig, TranscriptionService

# Use turbo for fast, high-quality transcription
config = TranscriptionConfig(
    whisper_model="turbo",  # 8x faster than large!
    language="pt"
)

service = TranscriptionService(config)
service.process("long_video.mp4", "transcription.txt")
```

## 🐛 Troubleshooting

### "FFmpeg not found"

- Make sure FFmpeg is installed and available in your PATH
- Test with: `ffmpeg -version`

### "Model download failed"

- First run downloads the Whisper model (can take a few minutes)
- Requires internet connection for first use
- Models are cached in `~/.cache/whisper/`

### "Out of memory"

- Try a smaller model (e.g., "small" instead of "large")
- Process shorter audio files
- Close other applications
- For long videos with limited RAM, consider `tiny` or `base` models

### YouTube download issues

- Make sure the video is public and accessible
- Some regions/videos may be blocked
- Update yt-dlp: `pip install --upgrade yt-dlp`

### "Invalid model" error

- Supported models: `tiny`, `base`, `small`, `medium`, `large`, `turbo`
- Check for typos in the model name
- `.en` variants are not yet supported

## 📦 Dependencies

- **openai-whisper**: Speech recognition model
- **yt-dlp**: YouTube video/audio downloader
- **ffmpeg-python**: Python bindings for FFmpeg
- **tqdm**: Progress bar support

## 📄 License

This project is open source and available under the MIT License.

## 🙏 Acknowledgments

- [OpenAI Whisper](https://github.com/openai/whisper) for the amazing speech recognition model
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) for YouTube download functionality
- [FFmpeg](https://ffmpeg.org/) for audio/video processing

## 📚 Additional Resources

- [Whisper Paper](https://arxiv.org/abs/2212.04356)
- [Whisper Model Card](https://github.com/openai/whisper/blob/main/model-card.md)
- [OpenAI Whisper Blog](https://openai.com/blog/whisper)

---

**Made with ❤️ by [pvss-dev](https://github.com/pvss-dev)**