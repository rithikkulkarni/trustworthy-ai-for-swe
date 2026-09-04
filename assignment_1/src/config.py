"""
Central config loader for Assignment 1 Task 5 (PII detection).

Reads config.json (next to this file) so parameters shared or relevant
across sample_stackv2.py and pii_detect.py live in one editable place
instead of being hardcoded per-script. Both scripts still expose CLI flags
that default to these values and can override them for one-off runs.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent / "config.json"


@dataclass
class SamplingConfig:
    dataset_name: str
    dataset_revision: str
    language_config: str
    extension: str
    n: int
    seed: int
    buffer_size: int
    scan_limit: int
    min_bytes: int
    max_bytes: int
    max_files_per_repo: int
    out_dir: str
    manifest_path: str


@dataclass
class DetectionConfig:
    extensions: list[str]
    entropy_threshold: float
    min_secret_length: int


@dataclass
class LLMConfig:
    model: str
    input_usd_per_m_tokens: float
    output_usd_per_m_tokens: float
    temperature: float
    verify_by_default: bool


@dataclass
class ReportConfig:
    max_examples_per_type: int


@dataclass
class Config:
    sampling: SamplingConfig
    detection: DetectionConfig
    llm: LLMConfig
    report: ReportConfig


def load_config(path: Path | None = None) -> Config:
    path = path or _CONFIG_PATH
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    return Config(
        sampling=SamplingConfig(**raw["sampling"]),
        detection=DetectionConfig(**raw["detection"]),
        llm=LLMConfig(**raw["llm"]),
        report=ReportConfig(**raw["report"]),
    )


CONFIG = load_config()
