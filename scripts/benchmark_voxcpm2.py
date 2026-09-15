"""Run a reproducible VoxCPM2 Ryan voice benchmark outside formal jobs.

The benchmark loads one model and one reference/LoRA pair, then changes only
the dimension named by each case. It writes audio and machine-readable rows
under benchmarks/voice instead of touching the job queue.
"""

from __future__ import annotations

import argparse
import csv
import difflib
import inspect
import json
import os
import re
import time
from pathlib import Path

import soundfile as sf
from voxcpm import VoxCPM

from voice_engine import audio_quality_score, build_voxcpm_control_instruction, find_control_terms_in_transcript


TEXT = (
    "最近经常有人问我一个问题，人工智能生成内容的速度越来越快，但真正决定一个产品好不好用的，"
    "往往不是模型有多大，而是它能不能真正融入你的工作流程。"
)
SEED = 20260915
BASE_STYLE = "professional_natural"
BASE_PACE = "natural"
BASE_CFG = 2.0
BASE_STEPS = 10
BASE_NORMALIZE = True
BASE_DENOISE = False
BASE_RETRY = True
BASE_RETRY_MAX = 3


def chinese_instruction(style: str, pace: str) -> str:
    return build_voxcpm_control_instruction(style, pace)


def case(name: str, group: str, *, style=BASE_STYLE, pace=BASE_PACE,
         cfg=BASE_CFG, steps=BASE_STEPS, instruction_language="Chinese",
         instruction=None) -> dict:
    control = instruction or chinese_instruction(style, pace)
    return {
        "name": name,
        "group": group,
        "style": style,
        "pace": pace,
        "cfg": float(cfg),
        "steps": int(steps),
        "instructionLanguage": instruction_language,
        "controlInstruction": control,
        "generationText": f"({control}){TEXT}",
    }


def build_cases() -> list[dict]:
    cases = [
        case("A_professional_natural", "style"),
        case("B_serious_authoritative", "style", style="serious_authoritative"),
        case("C_warm_storytelling", "style", style="warm_storytelling"),
        case("D_professional_slightly_fast", "style", pace="slightly_fast"),
    ]
    cases.extend(case(f"{pace}", "pace", pace=pace) for pace in ("slow", "natural", "slightly_fast", "fast"))
    cases.extend(case(f"steps_{steps}", "steps", steps=steps) for steps in (6, 10, 18, 25, 30))
    cases.extend(case(f"cfg_{cfg:g}", "cfg", cfg=cfg) for cfg in (1.5, 2.0, 2.5, 3.0))
    cases.extend([
        case(
            "chinese_professional_slightly_fast",
            "instructions",
            pace="slightly_fast",
            instruction_language="Chinese",
        ),
        case(
            "english_professional_slightly_fast",
            "instructions",
            pace="slightly_fast",
            instruction_language="English",
            instruction="natural and professional, slightly faster speaking pace, clear articulation",
        ),
        case(
            "chinese_warm_storytelling",
            "instructions",
            style="warm_storytelling",
            instruction_language="Chinese",
        ),
        case(
            "english_serious_authoritative",
            "instructions",
            style="serious_authoritative",
            instruction_language="English",
            instruction="serious, restrained and trustworthy, stable intonation, clear emphasis",
        ),
    ])
    return cases


def chinese_characters(text: str) -> int:
    return len(re.findall(r"[\u4e00-\u9fff]", text))


def normalize_transcript(text: str) -> str:
    return re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]", "", str(text or "")).lower()


def load_asr():
    if os.environ.get("DHJR_BENCHMARK_ASR", "1").lower() not in {"1", "true", "yes", "on"}:
        return None
    try:
        import stable_whisper
        return stable_whisper.load_model(os.environ.get("DHJR_ASR_MODEL", "base"))
    except Exception as exc:
        print(f"[WARN] ASR unavailable: {exc}")
        return None


def asr_metrics(asr_model, audio_path: Path, expected: str, instruction: str) -> dict:
    if asr_model is None:
        return {"asrConsistency": None, "asrTranscript": "", "controlTermsLeaked": []}
    try:
        result = asr_model.transcribe(str(audio_path), language="zh", verbose=False)
        transcript = getattr(result, "text", "")
        ratio = difflib.SequenceMatcher(None, normalize_transcript(expected), normalize_transcript(transcript)).ratio()
        terms = find_control_terms_in_transcript(transcript)
        english_terms = [term for term in ("natural", "professional", "slightly faster", "clear articulation", "serious", "restrained") if term.lower() in transcript.lower()]
        return {
            "asrConsistency": round(ratio, 4),
            "asrTranscript": transcript,
            "controlTermsLeaked": sorted(set(terms + english_terms)),
        }
    except Exception as exc:
        return {"asrConsistency": None, "asrTranscript": "", "controlTermsLeaked": [], "asrError": str(exc)}


def load_model(base_model: Path, checkpoint: Path) -> VoxCPM:
    from voxcpm.model.voxcpm import LoRAConfig

    config_path = checkpoint / "lora_config.json"
    if not config_path.exists():
        raise FileNotFoundError(f"LoRA config not found: {config_path}")
    info = json.loads(config_path.read_text(encoding="utf-8"))
    return VoxCPM.from_pretrained(
        hf_model_id=str(base_model),
        load_denoiser=False,
        optimize=True,
        lora_config=LoRAConfig(**info["lora_config"]),
        lora_weights_path=str(checkpoint),
    )


def run(args: argparse.Namespace) -> Path:
    output_root = Path(args.output).resolve()
    for group in ("style", "pace", "steps", "cfg", "instructions"):
        (output_root / group).mkdir(parents=True, exist_ok=True)

    print(f"Loading VoxCPM2 from {args.base_model}")
    model = load_model(Path(args.base_model), Path(args.checkpoint))
    seed_supported = "seed" in inspect.signature(model._generate).parameters
    print(f"Official seed API: {seed_supported}")
    asr_model = load_asr()
    rows = []
    for item in build_cases():
        out_dir = output_root / item["group"]
        out_path = out_dir / f"{item['name']}.wav"
        print(f"Generating {item['group']}/{item['name']} ...")
        started = time.perf_counter()
        kwargs = {
            "text": item["generationText"],
            "reference_wav_path": str(args.reference),
            "cfg_value": item["cfg"],
            "inference_timesteps": item["steps"],
            "normalize": BASE_NORMALIZE,
            "denoise": BASE_DENOISE,
            "retry_badcase": BASE_RETRY,
            "retry_badcase_max_times": BASE_RETRY_MAX,
            "seed": SEED,
        }
        if not seed_supported:
            raise RuntimeError("The installed VoxCPM runtime does not support the official seed API")
        wav = model.generate(**kwargs)
        generation_seconds = time.perf_counter() - started
        sample_rate = int(model.tts_model.sample_rate)
        sf.write(out_path, wav, sample_rate)
        duration = len(wav) / sample_rate
        successful_seed = getattr(model.tts_model, "last_successful_seed", None)
        metrics = asr_metrics(asr_model, out_path, TEXT, item["controlInstruction"])
        row = {
            "speaker": "Ryan",
            "cloneMode": "controllable_clone",
            "group": item["group"],
            "case": item["name"],
            "style": item["style"],
            "pace": item["pace"],
            "controlInstruction": item["controlInstruction"],
            "instructionLanguage": item["instructionLanguage"],
            "cfg": item["cfg"],
            "steps": item["steps"],
            "requestedSeed": SEED,
            "successfulSeed": int(successful_seed) if successful_seed is not None else None,
            "duration": round(duration, 6),
            "generationSeconds": round(generation_seconds, 3),
            "charactersPerSecond": round(chinese_characters(TEXT) / duration, 4),
            "qualityScore": round(audio_quality_score(wav, sample_rate), 4),
            "audioPath": str(out_path),
            **metrics,
        }
        rows.append(row)
        print(json.dumps(row, ensure_ascii=False))

    fields = list(rows[0].keys())
    csv_path = output_root / "results.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    metadata = {
        "runtime": {
            "voxcpmPath": str(Path(inspect.getfile(VoxCPM)).resolve()),
            "seedSupported": seed_supported,
            "baseModel": str(args.base_model),
            "checkpoint": str(args.checkpoint),
            "reference": str(args.reference),
        },
        "speaker": "Ryan",
        "cloneMode": "controllable_clone",
        "text": TEXT,
        "fixed": {
            "seed": SEED,
            "cfg": BASE_CFG,
            "steps": BASE_STEPS,
            "normalize": BASE_NORMALIZE,
            "denoise": BASE_DENOISE,
            "retryBadcase": BASE_RETRY,
            "bestOf": 1,
        },
        "rows": rows,
    }
    (output_root / "benchmark.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"results.csv: {csv_path}")
    return output_root


def parse_args() -> argparse.Namespace:
    root = Path(os.environ.get("DHJR_ENGINE_WORKSPACE", Path.home() / "AI-Workspace"))
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default=str(Path(os.environ.get("DHJR_WORKSPACE", root)) / "benchmarks/voice/voxcpm_ryan_20260915"))
    parser.add_argument("--base-model", default=os.environ.get("DHJR_VOXCPM_PRETRAINED", str(root / "projects/VoxCPM/pretrained_models/VoxCPM2")))
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--reference", required=True)
    return parser.parse_args()


if __name__ == "__main__":
    run(parse_args())
