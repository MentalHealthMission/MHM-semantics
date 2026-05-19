"""Ontology namespace bindings.

The current ODIM assets still use the historical CONNECT URL. Treat that URI as
a compatibility namespace, not a hard-coded semantic-kernel assumption.
"""

from __future__ import annotations

import os
from typing import Iterable


LEGACY_CONNECT_ODIM_NAMESPACE = "http://connectdigitalstudy.com/ontology#"
ODIM_NAMESPACE_ENV = "MHM_ODIM_NAMESPACE"


def normalize_namespace(namespace: str) -> str:
    value = str(namespace or "").strip() or LEGACY_CONNECT_ODIM_NAMESPACE
    if value.endswith(("#", "/")):
        return value
    return value + "#"


def default_odim_namespace() -> str:
    return normalize_namespace(os.getenv(ODIM_NAMESPACE_ENV, LEGACY_CONNECT_ODIM_NAMESPACE))


def odim_namespaces(
    namespace: str | None = None,
    *,
    aliases: Iterable[str] = (),
) -> tuple[str, ...]:
    ordered: list[str] = []
    for candidate in [namespace or default_odim_namespace(), LEGACY_CONNECT_ODIM_NAMESPACE, *aliases]:
        normalized = normalize_namespace(candidate)
        if normalized not in ordered:
            ordered.append(normalized)
    return tuple(ordered)


def odim_curie_from_uri(uri: str, *, namespace: str | None = None, aliases: Iterable[str] = ()) -> str:
    text = str(uri or "").strip()
    for candidate in odim_namespaces(namespace, aliases=aliases):
        if text.startswith(candidate):
            return f"odim:{text.split(candidate, 1)[1]}"
    return text


def odim_uri(local: str, *, namespace: str | None = None) -> str:
    value = str(local or "").strip()
    if value.startswith("odim:"):
        value = value.split(":", 1)[1]
    return default_odim_namespace() + value if namespace is None else normalize_namespace(namespace) + value


__all__ = [
    "LEGACY_CONNECT_ODIM_NAMESPACE",
    "ODIM_NAMESPACE_ENV",
    "default_odim_namespace",
    "normalize_namespace",
    "odim_curie_from_uri",
    "odim_namespaces",
    "odim_uri",
]
