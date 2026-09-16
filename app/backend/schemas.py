from typing import List, Literal, Optional, Union

from pydantic import BaseModel


class JobCreateRequest(BaseModel):
    title: str
    subtitle: str
    keywords: Union[List[str], str]
    script: str
    background_id: str
    voice_id: Optional[str] = None
    voice_language: str = "zh"
    voice_dialect: Optional[str] = "mandarin"
    voice_mode: str = "basic_tts"
    voice_style: str = "professional_natural"
    voice_pace: str = "natural"
    voice_quality: str = "high"
    voice_seed: Optional[Union[int, Literal["auto"]]] = "auto"
    voice_best_of: Optional[int] = None
    voice_cfg: Optional[float] = None
    voice_inference_timesteps: Optional[int] = None
    voice_text_normalize: bool = True
    voice_reference_cleanup: bool = False
    voice_retry_badcase: bool = True
    output_type: str = "clean_video"
    outro_id: Optional[str] = None
    subtitle_enabled: bool = True
    shutdown_after_done: bool = False
    subtitle_lines: Optional[List[str]] = None
    opening_hook: Optional[str] = None
    script_source: Optional[str] = None   # "manual" | "ollama"
    script_model: Optional[str] = None


class JobRunResponse(BaseModel):
    message: str
    job_id: str
    pid: int


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    database: dict | None = None


class ScriptFormatRequest(BaseModel):
    raw_text: str
    language: str = "zh"
    target_line_length: str = "10-15"
    model: str = "qwen2.5:7b"


class QueueAutoRunRequest(BaseModel):
    enabled: bool


class QueueShutdownRequest(BaseModel):
    enabled: bool


class PullModelRequest(BaseModel):
    model: str


class TranscriptReviewRequest(BaseModel):
    rows: List[dict]


class OutroUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
