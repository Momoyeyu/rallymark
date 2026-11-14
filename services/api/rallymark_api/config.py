import hashlib
import json
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ApplicationConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    max_upload_bytes: int = Field(default=500_000_000, gt=0)
    max_duration_seconds: int = Field(default=900, gt=0)
    retention_days: int = Field(default=7, ge=1)
    session_cookie_secure: bool = False
    poll_seconds: float = Field(default=2, gt=0)


class AlgorithmConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = "ftt-4781dc8"
    tad_top_k: int = Field(default=200, ge=1, le=200)
    nearby_seconds: float = Field(default=9, ge=1, le=30)
    protect_top_m: int = Field(default=100, ge=0, le=200)
    min_duration_s: float = Field(default=0.5, ge=0, le=5)
    score_filter: bool = True
    fragment_gap_s: float = Field(default=1, ge=0, le=5)
    score_confidence: float = Field(default=0.8, ge=0, le=1)
    edge_window_s: float = Field(default=60, ge=0, le=120)
    ocr_crop: str = Field(default="auto", pattern=r"^(auto|\d+:\d+:\d+:\d+)$")
    ocr_width: int = Field(default=1920, gt=0)
    ocr_height: int = Field(default=1080, gt=0)
    parallel_inference: bool = True
    decoder_mode: str = Field(default="prefetch", pattern=r"^(fresh|reuse|prefetch)$")
    decode_workers: int = Field(default=4, ge=1, le=4)
    prefetch_depth: int = Field(default=4, ge=1, le=8)
    ocr_execution_provider: str = Field(default="cuda", pattern=r"^(cpu|cuda)$")
    timeout_seconds: int = Field(default=2700, gt=0)
    lease_seconds: int = Field(default=60, ge=30)
    max_attempts: int = Field(default=2, ge=1, le=5)
    runner: str = Field(default="real", pattern=r"^(real|fake)$")

    @model_validator(mode="after")
    def validate_protection(self):
        if self.protect_top_m > self.tad_top_k:
            raise ValueError("Protected TAD count must not exceed Top-N")
        return self


class LoggingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    level: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR)$")


class Config(BaseModel):
    model_config = ConfigDict(extra="forbid")
    application: ApplicationConfig = ApplicationConfig()
    algorithm: AlgorithmConfig = AlgorithmConfig()
    logging: LoggingConfig = LoggingConfig()

    def snapshot(self):
        return self.algorithm.model_dump(
            exclude={"version", "runner", "lease_seconds", "max_attempts"}
        )

    def digest(self):
        return hashlib.sha256(
            json.dumps(self.snapshot(), sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=None)
    database_url: str
    internal_token: SecretStr = Field(min_length=16)
    config_path: Path | None = None
    media_root: Path = Path("data/media")
    algorithm_url: str = "http://algorithm:8001"
    dispatcher_enabled: bool = True

    def load_config(self):
        return (
            Config.model_validate(yaml.safe_load(self.config_path.read_text()) or {})
            if self.config_path
            else Config()
        )
