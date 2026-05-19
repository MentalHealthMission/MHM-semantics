"""Shared helpers for custom feature extraction."""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Iterable, Optional, Sequence

import pandas as pd


DEFAULT_TIME_COLUMNS = [
    "value.time",
    "value.timeCompleted",
    "value.timeReceived",
    "value.startTime",
    "value.dateTime",
    "timestamp",
    "time",
]

DEFAULT_END_COLUMNS = [
    "value.endTime",
    "end_time",
    "endTime",
]

DEFAULT_DURATION_COLUMNS = [
    "value.duration",
    "duration",
]


def select_first_column(df: pd.DataFrame, candidates: Sequence[str]) -> Optional[str]:
    for name in candidates:
        if name in df.columns:
            return name
    return None


def parse_timestamp(series: pd.Series) -> pd.Series:
    if series.empty:
        return pd.to_datetime(series)
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    if pd.api.types.is_numeric_dtype(series):
        values = pd.to_numeric(series, errors="coerce")
        sample = values.dropna()
        if sample.empty:
            return pd.to_datetime(values, unit="s", errors="coerce")
        median = sample.median()
        unit = "ms" if median > 10**12 else "s"
        return pd.to_datetime(values, unit=unit, errors="coerce")
    return pd.to_datetime(series, errors="coerce")


def parse_duration(series: pd.Series) -> pd.Series:
    values = pd.to_numeric(series, errors="coerce")
    sample = values.dropna()
    if sample.empty:
        return values
    median = sample.median()
    # Heuristic: Fitbit durations are often ms; other sources can be seconds.
    if median > 10**5:
        return values / 1000.0
    return values


def to_date(series: pd.Series) -> pd.Series:
    return series.dt.date.astype(str)


def safe_json_load(value: object) -> Optional[dict]:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return None
    return None


def ensure_output_dir(base: Path, entity_id: str) -> Path:
    target = base / entity_id
    target.mkdir(parents=True, exist_ok=True)
    return target


def merge_daily_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
    if not frames:
        return pd.DataFrame()
    merged = frames[0]
    for frame in frames[1:]:
        merged = merged.merge(frame, on="segment_date", how="outer")
    return merged


def minutes_since_midnight(dt: pd.Timestamp) -> float:
    return dt.hour * 60 + dt.minute + dt.second / 60.0
