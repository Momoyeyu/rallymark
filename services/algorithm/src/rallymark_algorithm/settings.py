import hashlib
import json
import logging
import os
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class InferenceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tad_top_k: int = Field(default=200, ge=1, le=200)
    nearby_seconds: float = Field(default=5, ge=1, le=10)
    ocr_crop: str = Field(default="540:120:85:915", pattern=r"^\d+:\d+:\d+:\d+$")
    ocr_width: int = Field(default=1920, gt=0)
    ocr_height: int = Field(default=1080, gt=0)
    timeout_seconds: int = Field(default=2700, ge=1, le=10800)

    @model_validator(mode="after")
    def validate_crop(self):
        width, height, x, y = map(int, self.ocr_crop.split(":"))
        if width < 1 or height < 1 or x + width > self.ocr_width or y + height > self.ocr_height:
            raise ValueError("OCR crop must lie within the configured scoreboard image dimensions")
        return self


class AlgorithmConfig(InferenceConfig):
    version: str = "ftt-540cc9f"
    lease_seconds: int = Field(default=60, ge=10)
    max_attempts: int = Field(default=2, ge=1, le=5)
    runner: str = Field(default="real", pattern="^(real|fake)$")


class Settings(BaseModel):
    database_url: str
    internal_token: str = Field(min_length=16)
    business_internal_url: str = "http://api:8000"
    work_root: Path = Path("/data/work")
    weights_root: Path = Path("/models")
    ftt_root: Path
    algorithm: AlgorithmConfig = Field(default_factory=AlgorithmConfig)
    environment: str = "production"
    log_level: str = "INFO"
    retention_days: int = Field(default=7, ge=1)
    min_gpu_memory_gib: float = Field(default=12, gt=0, le=256)

    @model_validator(mode="after")
    def check_fake(self):
        if self.algorithm.runner == "fake" and self.environment not in ("development", "test"):
            raise ValueError("Fake runner requires ENVIRONMENT=development or test")
        return self

    @classmethod
    def load(cls):
        config_file = os.environ.get("CONFIG_PATH")
        raw = yaml.safe_load(Path(config_file).read_text()) if config_file else {}
        raw = raw or {}
        settings = cls(
            database_url=os.environ["DATABASE_URL"],
            internal_token=os.environ["INTERNAL_TOKEN"],
            business_internal_url=os.environ.get("BUSINESS_INTERNAL_URL", "http://api:8000").rstrip("/"),
            work_root=Path(os.environ.get("WORK_ROOT", "/data/work")),
            weights_root=Path(os.environ.get("WEIGHTS_ROOT", "/models")),
            ftt_root=Path(
                os.environ.get("FTT_ROOT", str(Path(__file__).resolve().parents[2] / "vendor/ftt"))
            ),
            algorithm=raw.get("algorithm", {}),
            environment=os.environ.get("ENVIRONMENT", "production"),
            log_level=raw.get("logging", {}).get("level", "INFO"),
            retention_days=raw.get("application", {}).get("retention_days", 7),
            min_gpu_memory_gib=os.environ.get("MIN_GPU_MEMORY_GIB", "12"),
        )
        return settings


def config_hash(config):
    return hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class JsonFormatter(logging.Formatter):
    def format(self, record):
        entry = {
            "time": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "service": "algorithm",
            "event": record.getMessage(),
        }
        for key in (
            "job_id",
            "video_id",
            "algorithm_version",
            "config_hash",
            "stage",
            "request_id",
            "attempt",
            "elapsed_seconds",
            "error_code",
            "gpu_name",
            "gpu_memory_gib",
            "gpu_free_gib",
        ):
            if hasattr(record, key):
                entry[key] = getattr(record, key)
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)


def configure_logging(level):
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    logging.basicConfig(level=level, handlers=[handler], force=True)
