# Knowledge Nuggets

The current production path uses Make for orchestration and a persistent
Redis-backed worker for asset ingestion and FFmpeg rendering. GitHub Actions
contains component checks and source-hunt tools; a green Action is not a
production quality pass.

Read [the stabilization audit](docs/stabilization-audit.md) before changing the
pipeline. Its stage-1 workflow tests the existing renderer with fixed assets
only. It does not generate a publishable Short.

YouTube uploading is disabled for this development phase. Do not commit
credentials or API keys to this repository.
