# Knowledge Nuggets Renderer

Free GitHub Actions render engine for the Make.com Knowledge Nuggets YouTube pipeline.

Make dispatches the workflow. GitHub Actions renders with FFmpeg and faster-whisper, publishes the resulting MP4 as a temporary release asset, and can callback into Make.

Do not commit credentials or API keys to this repository.
