"""
Standalone Ollama installer — run as subprocess by script_assistant.py.
Downloads the official Ollama package from ollama.com/download (which includes
CPU runners + GPU libs) and extracts to ~/.local using the `zstandard` Python
library (no sudo, no system zstd CLI needed).
"""
import os
import stat
import sys
import tarfile
import urllib.error
import urllib.request
from pathlib import Path

from ollama_archive import consume_member, extract_member

DEST_DIR      = Path.home() / ".local"
OLLAMA_BIN    = DEST_DIR / "bin" / "ollama"
LLAMA_SERVER  = DEST_DIR / "lib" / "ollama" / "llama-server"
DOWNLOAD_URL  = "https://ollama.com/download/ollama-linux-amd64.tar.zst"

def log(msg):
    print(msg, flush=True)

def should_extract(name: str) -> bool:
    # Skip large CUDA/ROCm/Vulkan libraries when they already exist.
    # Always extract CPU runner libs, llama-server, and the main binary.
    skip_if_exists = (
        "lib/ollama/cuda_v12/",
        "lib/ollama/cuda_v13/",
        "lib/ollama/rocm",
        "lib/ollama/mlx",
        "lib/ollama/vulkan",
    )
    for prefix in skip_if_exists:
        if name.startswith(prefix):
            dest = DEST_DIR / name
            if dest.exists():
                return False  # already on disk, skip
    return True

def main():
    log(f"[install] Downloading Ollama from ollama.com …")
    log(f"[install] URL: {DOWNLOAD_URL}")
    log(f"[install] Extracting to: {DEST_DIR}")

    try:
        import zstandard as zstd
    except ImportError:
        log("[install] ERROR: zstandard Python library not found. Install with: pip install zstandard")
        sys.exit(1)

    DEST_DIR.mkdir(parents=True, exist_ok=True)

    log("[install] Downloading and extracting (this may take 3-8 minutes) …")
    extracted = 0
    try:
        req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(resp) as zstd_reader:
                with tarfile.open(fileobj=zstd_reader, mode="r|") as tar:
                    for member in tar:
                        if should_extract(member.name):
                            extract_member(tar, member, DEST_DIR)
                            if member.size > 0:
                                extracted += 1
                                if extracted % 5 == 0:
                                    log(f"[install] Extracted {extracted} files so far …")
                        else:
                            # Streaming mode: must consume data to advance stream
                            consume_member(tar, member)
    except Exception as exc:
        log(f"[install] ERROR during download/extract: {exc}")
        sys.exit(1)

    if not OLLAMA_BIN.exists():
        log(f"[install] ERROR: {OLLAMA_BIN} not found after extraction.")
        sys.exit(1)

    if not LLAMA_SERVER.exists():
        log(f"[install] ERROR: {LLAMA_SERVER} not found after extraction.")
        sys.exit(1)

    OLLAMA_BIN.chmod(OLLAMA_BIN.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    LLAMA_SERVER.chmod(LLAMA_SERVER.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    log(f"[install] Extracted {extracted} files total.")
    log(f"[install] OLLAMA_INSTALL_OK: {OLLAMA_BIN}")

if __name__ == "__main__":
    main()
