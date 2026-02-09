"""I/O helpers for ontology integration."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping, Optional

import pandas as pd


def resolve_metric_path(
    merged_dir: Path,
    site: str,
    participant_id: str,
    metric: str,
    input_spec: Mapping[str, Any],
) -> Optional[Path]:
    path_override = input_spec.get("path")
    if path_override:
        return Path(str(path_override).format(site=site, participant_id=participant_id, metric=metric)).expanduser()
    metric_dir = merged_dir / site / participant_id / metric
    if not metric_dir.exists():
        return None
    for suffix in (".csv.gz", ".csv", ".parquet"):
        candidate = metric_dir / f"{metric}{suffix}"
        if candidate.exists():
            return candidate
    for candidate in metric_dir.iterdir():
        if candidate.suffix in {".csv", ".gz", ".parquet"}:
            return candidate
    return None


def read_metric_file(path: Path) -> pd.DataFrame:
    if path.suffix == ".parquet":
        return pd.read_parquet(path)
    if path.suffix == ".gz" or path.name.endswith(".csv.gz"):
        return pd.read_csv(path, compression="gzip")
    return pd.read_csv(path)


__all__ = ["resolve_metric_path", "read_metric_file"]
