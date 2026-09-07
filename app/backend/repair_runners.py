"""
One-shot repair script: downloads the official Ollama package and extracts
the CPU runner + shared libs that are missing from the GitHub-release tarball.
Run as: python repair_runners.py
"""
import os
import stat
import sys
import tarfile
import urllib.request
from pathlib import Path

from ollama_archive import consume_member, extract_member

DEST_DIR     = Path.home() / ".local"
LLAMA_SERVER = DEST_DIR / "lib" / "ollama" / "llama-server"
DOWNLOAD_URL = "https://ollama.com/download/ollama-linux-amd64.tar.zst"

# Only extract these prefixes (everything except huge CUDA/ROCm/Vulkan GPU libs)
SKIP_PREFIXES = (
    "bin/",                  # main binary already installed + may be in use
    "lib/ollama/cuda_v12/",
    "lib/ollama/cuda_v13/",
    "lib/ollama/rocm",
    "lib/ollama/mlx",
    "lib/ollama/vulkan",
)

def log(msg):
    print(msg, flush=True)

def main():
    if LLAMA_SERVER.exists():
        log(f"[repair] llama-server already present at {LLAMA_SERVER}")
        log("[repair] REPAIR_OK")
        return

    log("[repair] llama-server missing — downloading CPU runner files …")
    log(f"[repair] URL: {DOWNLOAD_URL}")

    try:
        import zstandard as zstd
    except ImportError:
        log("[repair] ERROR: zstandard Python library not found.")
        sys.exit(1)

    DEST_DIR.mkdir(parents=True, exist_ok=True)

    extracted = 0
    try:
        req = urllib.request.Request(DOWNLOAD_URL, headers={"User-Agent": "curl/8.0"})
        with urllib.request.urlopen(req, timeout=600) as resp:
            dctx = zstd.ZstdDecompressor()
            with dctx.stream_reader(resp) as zstd_reader:
                with tarfile.open(fileobj=zstd_reader, mode="r|") as tar:
                    for member in tar:
                        skip = any(member.name.startswith(p) for p in SKIP_PREFIXES)
                        if skip:
                            # In streaming mode we must consume the data explicitly
                            # (tarfile doesn't auto-skip on continue)
                            consume_member(tar, member)
                            continue
                        extract_member(tar, member, DEST_DIR)
                        if member.size > 0:
                            extracted += 1
                            if extracted <= 10 or extracted % 10 == 0:
                                log(f"[repair] +{member.name} ({member.size} bytes)")
    except Exception as exc:
        log(f"[repair] ERROR: {exc}")
        sys.exit(1)

    if not LLAMA_SERVER.exists():
        log(f"[repair] ERROR: {LLAMA_SERVER} still not found after extraction.")
        sys.exit(1)

    LLAMA_SERVER.chmod(LLAMA_SERVER.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    log(f"[repair] Extracted {extracted} files.")
    log("[repair] REPAIR_OK")

if __name__ == "__main__":
    main()
