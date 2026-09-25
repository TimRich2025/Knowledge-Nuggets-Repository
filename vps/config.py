from pathlib import Path
import os

ROOT = Path(os.environ.get("KN_DATA_DIR", "/data")).resolve()
CACHE = ROOT / "cache"
JOBS = ROOT / "jobs"
PENDING = JOBS / "pending"
WORKING = JOBS / "working"
COMPLETED = JOBS / "completed"
FAILED = JOBS / "failed"
OUTPUTS = ROOT / "outputs"
TMP = ROOT / "tmp"

for p in (CACHE, PENDING, WORKING, COMPLETED, FAILED, OUTPUTS, TMP):
    p.mkdir(parents=True, exist_ok=True)

API_TOKEN = os.environ.get("KN_API_TOKEN", "")
REDIS_URL = os.environ.get("REDIS_URL", "")
CALLBACK_TOKEN = os.environ.get("KN_CALLBACK_TOKEN", "")
ALLOWED_CALLBACK_URL = os.environ.get("KN_ALLOWED_CALLBACK_URL", "")
PUBLIC_BASE_URL = os.environ.get("KN_PUBLIC_BASE_URL", "").rstrip("/")
POLL_SECONDS = float(os.environ.get("KN_POLL_SECONDS", "2"))
MAX_CACHE_GB = float(os.environ.get("KN_MAX_CACHE_GB", "80"))
YOUTUBE_DATA_API_KEY = os.environ.get("KN_YOUTUBE_DATA_API_KEY", "")
YOUTUBE_TREND_REGION = os.environ.get("KN_YOUTUBE_TREND_REGION", "US").upper()
