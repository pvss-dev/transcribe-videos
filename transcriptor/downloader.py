import yt_dlp


class AudioDownloader:
    """Responsible for downloading audio from URLs."""

    def __init__(self, quality: str = "192"):
        self.quality = quality

    @staticmethod
    def is_url(path: str) -> bool:
        """Checks if the path is a URL."""
        return path.startswith(("http://", "https://"))

    def download_from_youtube(self, url: str, output: str) -> None:
        """Downloads audio from YouTube using yt-dlp."""
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': output,
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': self.quality,
            }],
            'quiet': False,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            print("Downloading audio from YouTube...")
            ydl.download([url])
