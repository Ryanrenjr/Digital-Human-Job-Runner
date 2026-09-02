import asyncio
import json
import logging
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional
from settings import LOGS_DIR

logger = logging.getLogger(__name__)

OLLAMA_BASE      = "http://127.0.0.1:11434"
DEFAULT_MODEL    = "qwen2.5:7b"
OLLAMA_USER_BIN  = Path.home() / ".local" / "bin" / "ollama"   # user-local fallback
LLAMA_SERVER_BIN = Path.home() / ".local" / "lib" / "ollama" / "llama-server"

_SYSTEM = (
    "你是一个短视频文案整理助手。任务是从文案中提取标题、副标题、关键词、开头钩子。\n\n"
    "【核心规则】\n"
    "- 只从原文中提取信息，不得改写、增加或删减原文任何内容。\n\n"
    "请输出以下 JSON 格式，只输出 JSON，不要任何其他文字：\n"
    '{\n'
    '  "title": "从文案第一句提取标题，10字以内",\n'
    '  "subtitle": "副标题，20字以内，从文案中提取",\n'
    '  "keywords": ["关键词1", "关键词2", "关键词3"],\n'
    '  "opening_hook": "开头3秒钩子，15字以内"\n'
    "}\n\n"
    "只输出 JSON，不要其他文字。"
)

# In-memory process tracking
_PULL_PROCS:   dict                 = {}    # model -> subprocess.Popen
_INSTALL_PROC: Optional[subprocess.Popen] = None


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_http_error(exc) -> str:
    try:
        return exc.read().decode("utf-8", errors="replace")
    except Exception:
        return ""


def _find_ollama_bin() -> str:
    """Return ollama binary path, checking system PATH then user-local install."""
    in_path = shutil.which("ollama")
    if in_path:
        return in_path
    if OLLAMA_USER_BIN.exists():
        return str(OLLAMA_USER_BIN)
    return ""


def _is_ollama_running() -> bool:
    req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5):
            return True
    except Exception:
        return False


def _get_available_models() -> list:
    req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return [m.get("name", "") for m in data.get("models", [])]
    except Exception:
        return []


# ── health check ──────────────────────────────────────────────────────────────

def _check_health_sync(model: str) -> dict:
    ollama_installed = bool(_find_ollama_bin())
    runner_ok        = LLAMA_SERVER_BIN.exists()

    req = urllib.request.Request(f"{OLLAMA_BASE}/api/tags", method="GET")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ConnectionRefusedError):
        return {
            "ok": False, "ollama_running": False, "ollama_installed": ollama_installed,
            "runner_ok": runner_ok,
            "model_found": False, "model": model, "available_models": [],
            "message": "ollama_not_running",
        }
    except Exception as exc:
        return {
            "ok": False, "ollama_running": False, "ollama_installed": ollama_installed,
            "runner_ok": runner_ok,
            "model_found": False, "model": model, "available_models": [],
            "message": f"ollama_error:{exc}",
        }

    available = [m.get("name", "") for m in data.get("models", [])]
    found = model in available
    if not found and ":" not in model:
        found = any(m.startswith(model) for m in available)

    return {
        "ok": found and runner_ok,
        "ollama_running": True,
        "ollama_installed": True,
        "runner_ok": runner_ok,
        "model_found": found,
        "model": model,
        "available_models": available,
        "message": "ready" if (found and runner_ok) else (
            "runner_missing" if not runner_ok else f"model_not_found:{model}"
        ),
    }


async def check_health(model: str) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _check_health_sync, model)


# ── install Ollama ────────────────────────────────────────────────────────────

def _install_ollama_sync() -> dict:
    global _INSTALL_PROC

    if _find_ollama_bin():
        return {
            "ok": True, "already_installed": True,
            "message": "Ollama is already installed",
            "message_zh": "Ollama 已安装，无需重新安装",
        }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "ollama_install.log"

    # Python-based installer: uses zstandard lib, no sudo, no CLI tools needed
    installer  = Path(__file__).parent / "install_ollama.py"
    python_bin = sys.executable

    try:
        with open(log_path, "w") as lf:
            proc = subprocess.Popen(
                [python_bin, str(installer)],
                stdout=lf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _INSTALL_PROC = proc
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Failed to start install: {exc}",
            "message_zh": f"安装启动失败：{exc}",
        }

    return {
        "ok": True, "started": True,
        "message": "Downloading Ollama (~200 MB). Click Check Install Status to monitor.",
        "message_zh": "正在下载 Ollama（约 200 MB），点击「检查安装进度」查看进度。",
    }


def _install_status_sync() -> dict:
    installed = bool(_find_ollama_bin())

    proc    = _INSTALL_PROC
    running = proc is not None and proc.poll() is None

    log_path = LOGS_DIR / "ollama_install.log"
    log_tail = ""
    if log_path.exists():
        try:
            raw      = log_path.read_text(encoding="utf-8", errors="replace")
            lines    = _strip_ansi(raw).splitlines()
            log_tail = "\n".join(l for l in lines[-20:] if l.strip())
        except Exception:
            pass

    failed = False
    if not running and not installed and log_tail:
        lc = log_tail.lower()
        if any(w in lc for w in ["error", "failed", "command not found"]):
            failed = True

    return {
        "installed": installed,
        "running": running,
        "log_tail": log_tail,
        "failed": failed,
    }


async def install_ollama() -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _install_ollama_sync)


async def install_status() -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _install_status_sync)


# ── repair runners ────────────────────────────────────────────────────────────

_REPAIR_PROC: Optional[subprocess.Popen] = None

def _repair_runners_sync() -> dict:
    global _REPAIR_PROC

    if LLAMA_SERVER_BIN.exists():
        return {
            "ok": True, "already_ok": True,
            "message": "CPU runner already present",
            "message_zh": "CPU 运行库已存在，无需修复",
        }

    proc = _REPAIR_PROC
    if proc is not None and proc.poll() is None:
        return {
            "ok": True, "started": True,
            "message": "Repair already in progress",
            "message_zh": "修复正在进行中，请稍候",
        }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / "repair_runners.log"

    repairer   = Path(__file__).parent / "repair_runners.py"
    python_bin = sys.executable

    try:
        with open(log_path, "w") as lf:
            proc = subprocess.Popen(
                [python_bin, str(repairer)],
                stdout=lf,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        _REPAIR_PROC = proc
    except Exception as exc:
        return {
            "ok": False,
            "message": f"Failed to start repair: {exc}",
            "message_zh": f"修复启动失败：{exc}",
        }

    return {
        "ok": True, "started": True,
        "message": "Downloading CPU runner files (~1.4 GB). Check repair status to monitor.",
        "message_zh": "正在下载 CPU 运行库（约 1.4 GB），请点击「检查修复进度」查看进度。",
    }


def _repair_status_sync() -> dict:
    runner_ok = LLAMA_SERVER_BIN.exists()

    proc    = _REPAIR_PROC
    running = proc is not None and proc.poll() is None

    log_path = LOGS_DIR / "repair_runners.log"
    log_tail = ""
    if log_path.exists():
        try:
            raw      = log_path.read_text(encoding="utf-8", errors="replace")
            lines    = raw.splitlines()
            log_tail = "\n".join(l for l in lines[-15:] if l.strip())
        except Exception:
            pass

    if runner_ok and running:
        # Restart Ollama to pick up new runner libraries
        try:
            subprocess.run(
                ["systemctl", "--user", "restart", "ollama"],
                capture_output=True, timeout=10,
            )
        except Exception:
            pass

    failed = False
    if not running and not runner_ok and log_tail:
        lc = log_tail.lower()
        if any(w in lc for w in ["error", "failed"]):
            failed = True

    return {
        "runner_ok": runner_ok,
        "running":   running,
        "log_tail":  log_tail,
        "failed":    failed,
    }


async def repair_runners() -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _repair_runners_sync)


async def repair_status() -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _repair_status_sync)


# ── start Ollama ──────────────────────────────────────────────────────────────

def _start_ollama_sync() -> dict:
    if _is_ollama_running():
        return {
            "ok": True, "already_running": True,
            "message": "Ollama is already running",
            "message_zh": "Ollama 已经在运行",
        }

    if not _find_ollama_bin():
        return {
            "ok": False, "already_running": False,
            "ollama_installed": False,
            "message": "Ollama is not installed.",
            "message_zh": "Ollama 未安装，请先安装。",
        }

    # Start via systemd user service (survives backend restarts; auto-restarts on failure)
    try:
        result = subprocess.run(
            ["systemctl", "--user", "start", "ollama"],
            capture_output=True, timeout=10,
        )
        if result.returncode != 0:
            # Fallback: spawn directly if systemd unit not available
            raise RuntimeError(result.stderr.decode("utf-8", errors="replace"))
    except Exception:
        # Direct spawn fallback
        ollama_bin = _find_ollama_bin()
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        try:
            with open(LOGS_DIR / "ollama.log", "a") as lf:
                subprocess.Popen(
                    [ollama_bin, "serve"],
                    stdout=lf, stderr=lf,
                    start_new_session=True,
                )
        except Exception as exc:
            return {
                "ok": False, "already_running": False,
                "message": f"Failed to start Ollama: {exc}",
                "message_zh": f"Ollama 启动失败：{exc}",
            }

    # Wait up to 8 seconds for Ollama to accept connections
    for _ in range(8):
        time.sleep(1)
        if _is_ollama_running():
            return {
                "ok": True, "already_running": False,
                "message": "Ollama started successfully",
                "message_zh": "Ollama 启动成功",
            }

    return {
        "ok": False, "already_running": False,
        "message": "Ollama started but did not respond in time. Try again.",
        "message_zh": "Ollama 进程已启动，但未能在规定时间内响应，请稍后再试。",
    }


async def start_ollama() -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _start_ollama_sync)


# ── pull model ────────────────────────────────────────────────────────────────

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")

def _strip_ansi(text: str) -> str:
    # Remove ANSI escape sequences, then resolve carriage returns (keep last overwrite)
    text = _ANSI_RE.sub("", text)
    lines = []
    for physical_line in text.split("\n"):
        # Split on \r: last segment wins (simulates terminal overwrite)
        segments = physical_line.split("\r")
        lines.append(segments[-1])
    return "\n".join(lines)

def _safe_model_name(model: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]", "_", model)


def _pull_model_sync(model: str) -> dict:
    health = _check_health_sync(model)

    if health["model_found"]:
        return {
            "ok": True, "started": False, "model": model, "installed": True,
            "message": f"Model {model} is already installed",
            "message_zh": f"模型 {model} 已安装，无需重新下载",
        }

    if not health["ollama_running"]:
        return {
            "ok": False, "started": False, "model": model,
            "message": "Ollama is not running. Start Ollama first.",
            "message_zh": "Ollama 未启动，请先启动 Ollama。",
        }

    # Prevent duplicate pulls
    proc = _PULL_PROCS.get(model)
    if proc is not None and proc.poll() is None:
        return {
            "ok": True, "started": True, "model": model,
            "message": "Model download already in progress",
            "message_zh": "模型下载已在进行中，请稍后查看状态",
        }

    ollama_bin = _find_ollama_bin()
    if not ollama_bin:
        return {
            "ok": False, "started": False, "model": model,
            "message": "Ollama command not found",
            "message_zh": "找不到 Ollama 命令",
        }

    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOGS_DIR / f"ollama_pull_{_safe_model_name(model)}.log"

    try:
        with open(log_path, "w") as lf:
            proc = subprocess.Popen(
                [ollama_bin, "pull", model],
                stdout=lf,
                stderr=lf,
                start_new_session=True,
            )
        _PULL_PROCS[model] = proc
    except Exception as exc:
        return {
            "ok": False, "started": False, "model": model,
            "message": f"Failed to start pull: {exc}",
            "message_zh": f"下载启动失败：{exc}",
        }

    return {
        "ok": True, "started": True, "model": model,
        "message": "Model download started",
        "message_zh": "模型下载已开始，可点击查看下载状态检查进度",
        "log_path": str(log_path),
    }


async def pull_model(model: str) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _pull_model_sync, model)


# ── pull status ───────────────────────────────────────────────────────────────

def _pull_status_sync(model: str) -> dict:
    available = _get_available_models()
    installed = model in available

    proc    = _PULL_PROCS.get(model)
    running = proc is not None and proc.poll() is None

    log_path = LOGS_DIR / f"ollama_pull_{_safe_model_name(model)}.log"
    log_tail = ""
    if log_path.exists():
        try:
            raw    = log_path.read_text(encoding="utf-8", errors="replace")
            lines  = _strip_ansi(raw).splitlines()
            # Keep only progress lines (contain %) and error lines; skip spinner-only lines
            useful = [l for l in lines if l.strip() and
                      ("%" in l or "error" in l.lower() or "success" in l.lower() or "verif" in l.lower())]
            log_tail = useful[-1] if useful else ""
            # Detect active pull even after backend restart: log modified in last 15 s
            if not running and not installed and log_path.stat().st_mtime > time.time() - 15:
                running = True
        except Exception:
            pass

    return {
        "model":          model,
        "running":        running,
        "installed":      installed,
        "log_tail":       log_tail,
        "ollama_running": _is_ollama_running(),
    }


async def pull_status(model: str) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _pull_status_sync, model)


# ── format script ─────────────────────────────────────────────────────────────

def _call_ollama(model: str, raw_text: str) -> dict:
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user",   "content": f"输入文案：\n{raw_text}"},
            ],
            "stream": False,
            "format": "json",
        },
        ensure_ascii=False,
    ).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_BASE}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = _read_http_error(exc).lower()
        if "llama-server" in body or "runner" in body or "binary not found" in body:
            raise ValueError("runner_missing")
        if exc.code == 404 or ("not found" in body and "model" in body):
            raise ValueError(f"model_not_found:{model}")
        raise ValueError(f"ollama_http_{exc.code}")
    except (urllib.error.URLError, OSError, ConnectionRefusedError):
        raise ValueError("ollama_not_running")

    content = data.get("message", {}).get("content", "")
    if not content:
        raise ValueError("Empty response from Ollama")

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    m = re.search(r"\{[\s\S]*\}", content)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Cannot parse Ollama response as JSON: {content[:300]}")


_PUNC_BREAK = frozenset('，。！？、：；')
_MAX_SUBTITLE = 15
_MIN_SUBTITLE = 8

def _split_subtitle_line(text: str) -> list:
    """Re-split a single subtitle line that is too long into ≤15-char chunks."""
    result = []
    while len(text) > _MAX_SUBTITLE:
        chunk = text[:_MAX_SUBTITLE]
        # Prefer breaking at a punctuation mark in the last few chars
        bp = -1
        for i in range(len(chunk) - 1, _MIN_SUBTITLE - 2, -1):
            if chunk[i] in _PUNC_BREAK:
                bp = i + 1
                break
        if bp > 0:
            result.append(text[:bp].rstrip('，。'))
            text = text[bp:]
        else:
            # If cutting at _MAX_SUBTITLE leaves a tiny tail (≤4 chars), split near
            # the middle instead to avoid orphan fragments like "匙", "元化", "把控"
            remaining_len = len(text) - _MAX_SUBTITLE
            if 0 < remaining_len <= 4:
                cut = len(text) // 2
            else:
                cut = _MAX_SUBTITLE
            result.append(text[:cut])
            text = text[cut:]
    if text.strip():
        result.append(text.strip().rstrip('，。'))
    return [r for r in result if r.strip()]


def _merge_short_fragments(lines: list, min_frag: int = 3) -> list:
    """Merge fragments shorter than min_frag chars into adjacent lines."""
    result = []
    for line in lines:
        if len(line) < min_frag and result:
            merged = result[-1] + line
            if len(merged) <= _MAX_SUBTITLE:
                result[-1] = merged
                continue
        result.append(line)
    return result


def _fix_subtitle_lines(lines: list) -> list:
    """Ensure all subtitle lines are ≤15 chars; re-split those that aren't."""
    out = []
    for line in lines:
        line = str(line).strip().rstrip('，。')
        if not line:
            continue
        if len(line) <= _MAX_SUBTITLE:
            out.append(line)
        else:
            out.extend(_split_subtitle_line(line))
    return _merge_short_fragments(out)


# Sentence-ending punctuation for primary splits
_SENTENCE_END = re.compile(r'(?<=[。！？])')
# Clause-level punctuation for secondary splits
_CLAUSE_PUNC  = frozenset('，、；：')


def _split_long_line(line: str) -> list[str]:
    """Split a single line that is > _MAX_SUBTITLE chars, preserving all content."""
    sentences = [s.strip() for s in _SENTENCE_END.split(line) if s.strip()]

    segments: list[str] = []
    for sent in sentences:
        if len(sent) <= _MAX_SUBTITLE:
            segments.append(sent)
            continue
        parts: list[str] = []
        buf = ""
        for ch in sent:
            buf += ch
            if ch in _CLAUSE_PUNC and len(buf) >= 6:
                parts.append(buf.rstrip('，、；：'))
                buf = ""
        if buf.strip():
            parts.append(buf.strip())
        for part in parts:
            part = part.strip()
            if not part:
                continue
            if len(part) <= _MAX_SUBTITLE:
                segments.append(part)
            else:
                segments.extend(_split_subtitle_line(part))

    out: list[str] = []
    for seg in segments:
        seg = seg.strip().rstrip('，。')
        if not seg:
            continue
        if out and len(seg) <= 4 and len(out[-1]) + len(seg) <= _MAX_SUBTITLE:
            out[-1] += seg
        else:
            out.append(seg)
    return _merge_short_fragments(out, min_frag=3)


def _generate_subtitles_from_script(text: str) -> list[str]:
    """
    Generate subtitle lines from text, preserving original paragraph structure.
    - Blank lines in the input become "" entries (paragraph breaks).
    - Lines ≤ 15 chars are kept as-is.
    - Lines > 15 chars are re-split using sentence/clause boundaries.
    """
    out: list[str] = []
    prev_was_empty = True  # suppress leading blanks

    for raw_line in text.splitlines():
        line = raw_line.strip().rstrip('，。')

        if not line:
            if not prev_was_empty and out:
                out.append("")
            prev_was_empty = True
            continue

        prev_was_empty = False
        if len(line) <= _MAX_SUBTITLE:
            out.append(line)
        else:
            out.extend(_split_long_line(line))

    # Remove trailing blank entries
    while out and out[-1] == "":
        out.pop()

    return out


async def format_script(raw_text: str, model: str = DEFAULT_MODEL) -> dict:
    loop = asyncio.get_event_loop()
    raw  = await loop.run_in_executor(None, _call_ollama, model, raw_text)

    keywords = raw.get("keywords", [])
    if not isinstance(keywords, list):
        keywords = [str(keywords)]

    # Keep original text unchanged — AI only extracts metadata, never rewrites content
    clean_script = raw_text.strip()

    # Generate subtitle lines from the original input — 100% content preserved, just re-split
    subtitle_lines = _generate_subtitles_from_script(raw_text)

    return {
        "title":          str(raw.get("title",        "")),
        "subtitle":       str(raw.get("subtitle",     "")),
        "keywords":       [str(k) for k in keywords],
        "clean_script":   clean_script,
        "subtitle_lines": subtitle_lines,
        "opening_hook":   str(raw.get("opening_hook", "")),
    }
