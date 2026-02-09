"""Screen unlock count, duration, and engagement features."""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from mhm_core.derived_features.odim_annotations import odim_computation, odim_defaults, odim_outputs
from mhm_core.derived_features.utils import (
    merge_daily_frames,
    parse_duration,
    parse_timestamp,
    select_first_column,
    to_date,
)


def _ios_metrics(df: pd.DataFrame, input_spec: Dict[str, object]) -> pd.DataFrame:
    time_col = input_spec.get("time_column") or select_first_column(df, ["value.time", "value.timeReceived"])
    unlock_col = input_spec.get("unlock_count_column") or select_first_column(df, ["value.totalUnlocks"])
    duration_col = input_spec.get("unlock_duration_column") or select_first_column(df, ["value.totalUnlockDuration"])
    if not time_col:
        return pd.DataFrame()
    times = parse_timestamp(df[time_col])
    df = df.assign(segment_date=to_date(times))
    result = df.groupby("segment_date", dropna=True).agg(
        screen_unlocks_ios=(unlock_col, "sum") if unlock_col else ("segment_date", "size"),
        unlock_duration_ios_sec=(duration_col, lambda s: parse_duration(s).sum()) if duration_col else ("segment_date", "size"),
    )
    return result.reset_index()


def _android_metrics(df: pd.DataFrame, input_spec: Dict[str, object], params: Dict[str, object]) -> pd.DataFrame:
    time_col = input_spec.get("time_column") or select_first_column(df, ["value.time"])
    state_col = input_spec.get("state_column") or select_first_column(df, ["value.interactionState", "interactionState"])
    if not time_col:
        return pd.DataFrame()
    times = parse_timestamp(df[time_col])
    df = df.assign(_timestamp=times).sort_values("_timestamp")
    if state_col and state_col in df.columns:
        states = df[state_col].astype(str).str.upper()
    else:
        states = pd.Series(["UNKNOWN"] * len(df))
    unlock_states = [s.upper() for s in params.get("unlock_states", ["UNLOCKED", "USER_PRESENT", "SCREEN_INTERACTIVE", "INTERACTION_ACTIVE"])]
    lock_states = [s.upper() for s in params.get("lock_states", ["LOCKED", "SCREEN_OFF", "INTERACTION_INACTIVE"])]
    is_unlock = states.isin(unlock_states)
    is_lock = states.isin(lock_states)

    df = df.assign(is_unlock=is_unlock, is_lock=is_lock)
    df["_next_time"] = df["_timestamp"].shift(-1)
    df["_duration_sec"] = (df["_next_time"] - df["_timestamp"]).dt.total_seconds().clip(lower=0)
    df["_unlock_duration"] = df["_duration_sec"].where(df["is_unlock"])
    df["segment_date"] = to_date(df["_timestamp"])

    unlock_transitions = df["is_unlock"] & ~df["is_unlock"].shift(1, fill_value=False)
    df["_unlock_event"] = unlock_transitions.astype(int)

    result = df.groupby("segment_date", dropna=True).agg(
        screen_unlocks_android=("_unlock_event", "sum"),
        unlock_duration_android_sec=("_unlock_duration", "sum"),
    )
    return result.reset_index()


def _combine(df: pd.DataFrame, method: str) -> pd.DataFrame:
    if df.empty:
        return df
    ios_unlocks = "screen_unlocks_ios" in df.columns
    android_unlocks = "screen_unlocks_android" in df.columns
    ios_duration = "unlock_duration_ios_sec" in df.columns
    android_duration = "unlock_duration_android_sec" in df.columns
    if method == "sum":
        if ios_unlocks and android_unlocks:
            df["screen_unlocks"] = df[["screen_unlocks_ios", "screen_unlocks_android"]].sum(axis=1, skipna=True)
        elif ios_unlocks:
            df["screen_unlocks"] = df["screen_unlocks_ios"]
        elif android_unlocks:
            df["screen_unlocks"] = df["screen_unlocks_android"]
        if ios_duration and android_duration:
            df["unlock_duration_sec"] = df[["unlock_duration_ios_sec", "unlock_duration_android_sec"]].sum(axis=1, skipna=True)
        elif ios_duration:
            df["unlock_duration_sec"] = df["unlock_duration_ios_sec"]
        elif android_duration:
            df["unlock_duration_sec"] = df["unlock_duration_android_sec"]
    else:
        if ios_unlocks and android_unlocks:
            df["screen_unlocks"] = df["screen_unlocks_ios"].combine_first(df["screen_unlocks_android"])
        elif ios_unlocks:
            df["screen_unlocks"] = df["screen_unlocks_ios"]
        elif android_unlocks:
            df["screen_unlocks"] = df["screen_unlocks_android"]
        if ios_duration and android_duration:
            df["unlock_duration_sec"] = df["unlock_duration_ios_sec"].combine_first(df["unlock_duration_android_sec"])
        elif ios_duration:
            df["unlock_duration_sec"] = df["unlock_duration_ios_sec"]
        elif android_duration:
            df["unlock_duration_sec"] = df["unlock_duration_android_sec"]
    return df


@odim_computation(
    id="ScreenUsageAggregationComputation",
    type="odim:AlgorithmicComputation",
    label="Screen unlock aggregation",
    uses=[
        "sensorkit_device_usage",
        "android_phone_user_interaction",
    ],
)
@odim_outputs(
    [
        {
            "column": "screen_unlocks",
            "odim_feature": "odim:ScreenUnlockCountFeature",
            "category": "odim:BehavioralProperty",
            "doc": "Total screen unlock count per day.",
        },
        {
            "column": "unlock_duration_sec",
            "odim_feature": "odim:ScreenUnlockDurationFeature",
            "category": "odim:BehavioralProperty",
            "doc": "Total duration (seconds) of unlocked screen time per day.",
        },
        {
            "column": "mean_unlock_duration_sec",
            "odim_feature": "odim:ScreenUnlockMeanDurationFeature",
            "category": "odim:BehavioralProperty",
            "doc": "Mean duration (seconds) per unlock event per day.",
        },
        {
            "column": "unlock_fragmentation",
            "odim_feature": "odim:ScreenUnlockFragmentationFeature",
            "category": "odim:BehavioralProperty",
            "doc": "Unlocks per hour of unlocked time (fragmentation index).",
        },
    ]
)
@odim_defaults(
    feature_id="screen_usage",
    inputs={
        "ios": {
            "metric": "sensorkit_device_usage",
            "time_column": "value.time",
            "start_column": "value.startTime",
            "end_column": "value.endTime",
            "duration_column": "value.duration",
            "value_column": "value.doubleValue",
            "stage_column": "value.level",
            "segment_column": "segment_date",
            "unlock_count_column": "value.totalUnlocks",
            "unlock_duration_column": "value.totalUnlockDuration",
            "usage_column": "value.applicationUsageByCategory",
        },
        "android": {
            "metric": "android_phone_user_interaction",
            "time_column": "value.time",
            "start_column": "value.startTime",
            "end_column": "value.endTime",
            "duration_column": "value.duration",
            "value_column": "value.doubleValue",
            "stage_column": "value.level",
            "segment_column": "segment_date",
            "state_column": "value.interactionState",
        },
    },
    params={
        "combine": "coalesce",
        "min_unlock_duration_sec": 60,
    }
)
def compute(
    *,
    inputs: Dict[str, Optional[pd.DataFrame]],
    input_specs: Dict[str, Dict[str, object]],
    params: Dict[str, object],
    participant_id: str,
    logger,
) -> pd.DataFrame:
    ios_df = inputs.get("ios")
    android_df = inputs.get("android")
    frames = []
    if ios_df is not None:
        frames.append(_ios_metrics(ios_df, input_specs.get("ios", {})))
    if android_df is not None:
        frames.append(_android_metrics(android_df, input_specs.get("android", {}), params))
    daily = merge_daily_frames([df for df in frames if not df.empty])
    if daily.empty:
        return daily
    combine = str(params.get("combine", "coalesce")).lower()
    daily = _combine(daily, combine)
    unlocks = pd.to_numeric(daily.get("screen_unlocks"), errors="coerce")
    durations = pd.to_numeric(daily.get("unlock_duration_sec"), errors="coerce")
    if unlocks is not None and durations is not None:
        min_duration = float(params.get("min_unlock_duration_sec", 60))
        safe_unlocks = unlocks.where(unlocks > 0)
        safe_duration = durations.where(durations >= min_duration)
        daily["mean_unlock_duration_sec"] = durations / safe_unlocks
        daily["unlock_fragmentation"] = unlocks / (safe_duration / 3600.0)
    return daily
