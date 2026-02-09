"""Device-aware feature unification helpers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Optional

import pandas as pd

from mhm_core.derived_features import screen_features
from mhm_core.derived_features.utils import merge_daily_frames, parse_timestamp, select_first_column, to_date
from mhm_core.reduce_rapids_features import DEFAULT_TIME_COLS, _resolve_feature_column

from .config import UnificationFeature
from .io import read_metric_file, resolve_metric_path


@dataclass
class UnifiedFeatureOutput:
    feature_id: str
    dataframe: pd.DataFrame
    dimensions: List[str]
    unify: bool


def _daily_sum(df: pd.DataFrame, time_col: str, value_col: str, *, cumulative: bool = False) -> pd.DataFrame:
    times = parse_timestamp(df[time_col])
    if cumulative:
        ordered = df.assign(_timestamp=times).sort_values("_timestamp")
        steps = pd.to_numeric(ordered[value_col], errors="coerce").fillna(0)
        diffs = steps.diff()
        if not diffs.empty:
            diffs.iloc[0] = 0
        diffs = diffs.clip(lower=0)
        daily = pd.DataFrame({"segment_date": to_date(ordered["_timestamp"]), "value": diffs})
        grouped = daily.groupby("segment_date", dropna=True)["value"].sum().reset_index()
        return grouped

    df = df.assign(segment_date=to_date(times))
    grouped = df.groupby("segment_date", dropna=True)[value_col].sum().reset_index()
    grouped.rename(columns={value_col: "value"}, inplace=True)
    return grouped


def _coalesce_by_day(rows: pd.DataFrame) -> pd.DataFrame:
    if rows.empty:
        return rows
    rows = rows.sort_values(["segment_date", "priority"], ascending=[True, True])
    picked = rows.groupby("segment_date", dropna=True).first().reset_index()
    return picked


def _load_metric(
    merged_dir: Path,
    site: str,
    participant_id: str,
    spec: Mapping[str, object],
) -> Optional[pd.DataFrame]:
    metric = spec.get("metric")
    if not metric:
        return None
    metric_path = resolve_metric_path(merged_dir, site, participant_id, str(metric), spec)
    if not metric_path or not metric_path.exists():
        return None
    return read_metric_file(metric_path)


def unify_daily_sum(
    *,
    feature: UnificationFeature,
    merged_dir: Path,
    site: str,
    participant_id: str,
) -> pd.DataFrame:
    inputs = feature.inputs or []
    if not isinstance(inputs, list):
        raise ValueError(f"daily_sum inputs for {feature.feature_id} must be a list")

    frames: List[pd.DataFrame] = []
    for spec in inputs:
        if not isinstance(spec, Mapping):
            continue
        df = _load_metric(merged_dir, site, participant_id, spec)
        if df is None or df.empty:
            continue
        time_col = spec.get("time_column") or select_first_column(df, ["value.time", "value.timeReceived", "value.dateTime"])
        value_col = spec.get("value_column") or select_first_column(df, ["value.steps", "value.doubleValue", "value.numberOfSteps", "steps"])
        if time_col and time_col not in df.columns:
            time_col = None
        if value_col and value_col not in df.columns:
            value_col = None
        if not time_col or not value_col:
            continue
        cumulative = bool(spec.get("cumulative", False))
        daily = _daily_sum(df, str(time_col), str(value_col), cumulative=cumulative)
        if daily.empty:
            continue
        daily["source_metric"] = str(spec.get("metric"))
        daily["source_label"] = str(spec.get("name", spec.get("metric", "")))
        daily["priority"] = int(spec.get("priority", 999))
        frames.append(daily)

    if not frames:
        return pd.DataFrame()

    combined = pd.concat(frames, ignore_index=True)
    if feature.selection.get("same_day") == "prefer_priority":
        combined = _coalesce_by_day(combined)
    return combined


def unify_screen_usage(
    *,
    feature: UnificationFeature,
    merged_dir: Path,
    site: str,
    participant_id: str,
) -> pd.DataFrame:
    if not isinstance(feature.inputs, Mapping):
        raise ValueError(f"screen_usage inputs for {feature.feature_id} must be a mapping")
    inputs_spec = feature.inputs

    ios_spec = dict(inputs_spec.get("ios") or {})
    android_spec = dict(inputs_spec.get("android") or {})

    ios_df = _load_metric(merged_dir, site, participant_id, ios_spec) if ios_spec else None
    android_df = _load_metric(merged_dir, site, participant_id, android_spec) if android_spec else None

    result = screen_features.compute(
        inputs={"ios": ios_df, "android": android_df},
        input_specs={"ios": ios_spec, "android": android_spec},
        params=feature.params,
        participant_id=participant_id,
        logger=None,
    )
    if result is None or result.empty:
        return pd.DataFrame()

    df = result.copy()
    if "unlock_duration_sec" not in df.columns and "unlock_duration_ios_sec" in df.columns:
        df["unlock_duration_sec"] = df["unlock_duration_ios_sec"]
    source = []
    for _, row in df.iterrows():
        ios_val = row.get("unlock_duration_ios_sec")
        android_val = row.get("unlock_duration_android_sec")
        if pd.notna(ios_val) and pd.notna(android_val):
            source.append("sensorkit_device_usage+android_phone_user_interaction")
        elif pd.notna(ios_val):
            source.append("sensorkit_device_usage")
        elif pd.notna(android_val):
            source.append("android_phone_user_interaction")
        else:
            source.append("")
    df["source_metric"] = source
    return df[["segment_date", feature.output_column, "source_metric"]]


def unify_column(
    *,
    feature: UnificationFeature,
    merged_dir: Path,
    site: str,
    participant_id: str,
) -> pd.DataFrame:
    inputs = feature.inputs or []
    if not isinstance(inputs, list):
        raise ValueError(f"column inputs for {feature.feature_id} must be a list")

    frames: List[pd.DataFrame] = []
    for spec in inputs:
        if not isinstance(spec, Mapping):
            continue
        df = None
        path_override = spec.get("path")
        if path_override:
            metric_path = Path(str(path_override).format(site=site, participant_id=participant_id, metric=spec.get("metric", ""))).expanduser()
            if metric_path.exists():
                try:
                    df = read_metric_file(metric_path)
                except pd.errors.EmptyDataError:
                    df = None
        else:
            df = _load_metric(merged_dir, site, participant_id, spec)
        if df is None or df.empty:
            continue

        segment_col = spec.get("segment_column") or spec.get("date_column") or "segment_date"
        value_col = spec.get("value_column")
        if not value_col or value_col not in df.columns:
            continue
        if segment_col in df.columns:
            segment_values = parse_timestamp(df[segment_col])
        else:
            time_col = select_first_column(df, ["value.time", "value.timeReceived", "value.dateTime"])
            if not time_col:
                continue
            segment_values = parse_timestamp(df[time_col])

        data = {
            "segment_date": to_date(segment_values),
            "value": pd.to_numeric(df[value_col], errors="coerce"),
        }
        for dim in feature.dimensions or []:
            if dim in df.columns:
                data[dim] = df[dim]
        subset = pd.DataFrame(data)
        subset = subset.dropna(subset=["segment_date"])
        if subset.empty:
            continue
        source_metric = spec.get("source_metric") or spec.get("metric") or spec.get("name", "")
        subset["source_metric"] = str(source_metric)
        subset["priority"] = int(spec.get("priority", 999))
        frames.append(subset)

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if feature.selection.get("same_day") == "prefer_priority":
        combined = _coalesce_by_day(combined)
    combined = combined.rename(columns={"value": feature.output_column})
    keep_cols = ["segment_date", feature.output_column, "source_metric"]
    for dim in feature.dimensions or []:
        if dim in combined.columns:
            keep_cols.append(dim)
    return combined[keep_cols]


def unify_features_for_participant(
    *,
    features: Iterable[UnificationFeature],
    merged_dir: Path,
    site: str,
    participant_id: str,
) -> List[UnifiedFeatureOutput]:
    outputs: List[UnifiedFeatureOutput] = []
    for feature in features:
        if feature.method == "daily_sum":
            df = unify_daily_sum(feature=feature, merged_dir=merged_dir, site=site, participant_id=participant_id)
            if df.empty:
                continue
            df = df.rename(columns={"value": feature.output_column})
            df = df[["segment_date", feature.output_column, "source_metric"]]
        elif feature.method == "rapids_reduce":
            df = unify_rapids_reduce(feature=feature, participant_id=participant_id)
            if df.empty:
                continue
        elif feature.method == "column":
            df = unify_column(feature=feature, merged_dir=merged_dir, site=site, participant_id=participant_id)
            if df.empty:
                continue
        elif feature.method == "screen_usage":
            df = unify_screen_usage(feature=feature, merged_dir=merged_dir, site=site, participant_id=participant_id)
            if df.empty:
                continue
        else:
            raise ValueError(f"Unknown unification method {feature.method} for {feature.feature_id}")

        outputs.append(
            UnifiedFeatureOutput(
                feature_id=feature.feature_id,
                dataframe=df,
                dimensions=list(feature.dimensions),
                unify=bool(feature.unify),
            )
        )
    return outputs


def merge_unified_outputs(outputs: List[UnifiedFeatureOutput]) -> pd.DataFrame:
    if not outputs:
        return pd.DataFrame()
    frames: List[pd.DataFrame] = []
    for output in outputs:
        if not output.unify or output.dimensions:
            continue
        df = output.dataframe.copy()
        source_col = f"{output.feature_id}_source"
        df = df.rename(columns={"source_metric": source_col})
        frames.append(df)
    merged = merge_daily_frames(frames)
    return merged


def _read_rapids_feature_frame(rapids_dir: Path, participant_id: str, sensor: str) -> Optional[pd.DataFrame]:
    features_root = rapids_dir / "data" / "processed" / "features"
    path = features_root / participant_id / f"{sensor.lower()}.csv"
    if not path.exists():
        return None
    return pd.read_csv(path)


def unify_rapids_reduce(*, feature: UnificationFeature, participant_id: str) -> pd.DataFrame:
    inputs = feature.inputs or []
    if not isinstance(inputs, list):
        raise ValueError(f"rapids_reduce inputs for {feature.feature_id} must be a list")

    frames: List[pd.DataFrame] = []
    for spec in inputs:
        if not isinstance(spec, Mapping):
            continue
        sensor = spec.get("sensor")
        provider = spec.get("provider", "rapids")
        feat_name = spec.get("feature")
        if not sensor or not feat_name:
            continue
        rapids_dir = Path(str(spec.get("rapids_dir", ""))).expanduser()
        df = _read_rapids_feature_frame(rapids_dir, participant_id, str(sensor))
        if df is None or df.empty:
            continue

        time_cols = [col for col in DEFAULT_TIME_COLS if col in df.columns]
        if not time_cols:
            continue
        value_col = _resolve_feature_column(df.columns, str(sensor), str(provider), str(feat_name), spec.get("column"))
        subset = df[time_cols + [value_col]].copy()
        subset = subset.rename(columns={value_col: "value"})
        preferred_time_cols = [
            "local_segment_start_datetime",
            "local_segment_label",
            "local_segment",
        ]
        chosen_time = next((col for col in preferred_time_cols if col in subset.columns), time_cols[0])
        subset["segment_date"] = pd.to_datetime(subset[chosen_time], errors="coerce").dt.date.astype(str)
        subset = subset[subset["segment_date"].notna() & (subset["segment_date"] != "NaT")]
        subset["source_metric"] = f"rapids:{sensor}:{feat_name}:{spec.get('label', '')}".rstrip(":")
        subset["priority"] = int(spec.get("priority", 999))
        frames.append(subset[["segment_date", "value", "source_metric", "priority"]])

    if not frames:
        return pd.DataFrame()
    combined = pd.concat(frames, ignore_index=True)
    if feature.selection.get("same_day") == "prefer_priority":
        combined = _coalesce_by_day(combined)
    combined = combined.rename(columns={"value": feature.output_column})
    return combined[["segment_date", feature.output_column, "source_metric"]]


__all__ = ["UnificationFeature", "UnifiedFeatureOutput", "unify_features_for_participant", "merge_unified_outputs"]
