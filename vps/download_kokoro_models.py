"""Download and verify the exact Kokoro model artifacts used in production."""
from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path


ROOT = Path(os.environ.get("KN_KOKORO_DIR", "/opt/kokoro"))
BASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
FILES = {
    "kokoro-v1.0.int8.onnx": "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c",
    "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}


def digest(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def main() -> None:
    ROOT.mkdir(parents=True, exist_ok=True)
    for name, expected in FILES.items():
        target = ROOT / name
        if not target.exists() or digest(target) != expected:
            temporary = target.with_suffix(target.suffix + ".part")
            temporary.unlink(missing_ok=True)
            urllib.request.urlretrieve(f"{BASE}/{name}", temporary)
            if digest(temporary) != expected:
                temporary.unlink(missing_ok=True)
                raise RuntimeError(f"checksum mismatch for {name}")
            os.replace(temporary, target)


if __name__ == "__main__":
    main()
