from typing import List, Optional, Union

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
    voice_style: str = "professional_calm"
    voice_checkpoint_path: Optional[str] = None
    voice_reference_wav_path: Optional[str] = None
    voice_reference_text: Optional[str] = None
    voice_training_status: Optional[str] = None
    output_type: str = "clean_video"
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
