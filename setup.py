from setuptools import find_packages, setup

setup(
    name="transcriptor",
    version="2.0.0",
    packages=find_packages(exclude=["tests", "tests.*"]),
    include_package_data=True,
    package_data={"transcriptor": ["web/static/*"]},
    install_requires=[],
    extras_require={
        "web": ["fastapi>=0.115", "uvicorn[standard]>=0.30", "python-multipart>=0.0.9"],
        # Whisper pulls in PyTorch (~1 GB, or ~200 MB for the CPU-only build
        # from https://download.pytorch.org/whl/cpu).
        "transcribe": ["openai-whisper>=20240930"],
        "dev": ["pytest>=8.0", "httpx>=0.27"],
    },
    entry_points={
        "console_scripts": [
            "transcribe=transcriptor.cli:main",
            "transcriptor-web=transcriptor.web.cli:main",
            "transcriptor-clean=transcriptor.cleanup_cli:main",
        ],
    },
    python_requires=">=3.10",
    author="Paulo Vitor S. Soares",
    description="Transcribe audio and video with Whisper, from a CLI or the browser",
    keywords="whisper transcription subtitles srt speech-to-text",
)
