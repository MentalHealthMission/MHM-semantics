"""Helpers for annotating derived feature outputs with ODIM metadata."""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping


def odim_computation(**metadata: Any):
    """Attach computation metadata to a derived feature function."""

    def decorator(func):
        setattr(func, "__odim_computation__", dict(metadata))
        return func

    return decorator


def odim_outputs(outputs: Iterable[Mapping[str, Any]]):
    """Attach output metadata to a derived feature function."""
    output_list: List[Dict[str, Any]] = [dict(item) for item in outputs]

    def decorator(func):
        setattr(func, "__odim_outputs__", output_list)
        return func

    return decorator


def odim_defaults(**metadata: Any):
    """Attach default params/outputs metadata to a derived feature function."""

    def decorator(func):
        setattr(func, "__odim_defaults__", dict(metadata))
        return func

    return decorator
