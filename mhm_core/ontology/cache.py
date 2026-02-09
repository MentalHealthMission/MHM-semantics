"""Cache helpers for ontology-generated assets."""
from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Iterable, List
import json


CACHE_VERSION = "v1"


def _iter_files(path: Path) -> List[Path]:
    if path.is_dir():
        return sorted([p for p in path.rglob("*") if p.is_file()])
    if path.exists():
        return [path]
    return []


def _hash_paths(paths: Iterable[Path]) -> tuple[str, list[dict[str, str]]]:
    hasher = sha256()
    entries: list[dict[str, str]] = []
    for root in sorted({p.resolve() for p in paths}, key=lambda p: str(p)):
        for file_path in _iter_files(root):
            rel = file_path.as_posix()
            data = file_path.read_bytes()
            digest = sha256(data).hexdigest()
            entries.append({"path": rel, "sha256": digest})
            hasher.update(rel.encode())
            hasher.update(b"\0")
            hasher.update(data)
            hasher.update(b"\0")
    return hasher.hexdigest(), entries


def hash_paths(paths: Iterable[Path]) -> tuple[str, list[dict[str, str]]]:
    """Return a stable content hash and manifest entries for the given paths."""
    return _hash_paths(paths)


def compute_cache_key(*, rules_dir: Path, ontology_files: Iterable[Path], extra_paths: Iterable[Path] = ()) -> tuple[str, dict[str, object]]:
    combined = sha256()
    combined.update(CACHE_VERSION.encode())

    rules_hash, rules_entries = _hash_paths([rules_dir])
    combined.update(rules_hash.encode())

    ontology_hash, ontology_entries = _hash_paths(list(ontology_files))
    combined.update(ontology_hash.encode())

    extra_hash, extra_entries = _hash_paths(list(extra_paths))
    combined.update(extra_hash.encode())

    return (
        combined.hexdigest()[:12],
        {
            "version": CACHE_VERSION,
            "rules_hash": rules_hash,
            "ontology_hash": ontology_hash,
            "extra_hash": extra_hash,
            "rules_files": rules_entries,
            "ontology_files": ontology_entries,
            "extra_files": extra_entries,
        },
    )


@dataclass
class OntologyCache:
    root: Path
    rules_dir: Path
    ontology_files: list[Path]
    extra_paths: list[Path]

    def resolve(self) -> Path:
        key, manifest = compute_cache_key(
            rules_dir=self.rules_dir,
            ontology_files=self.ontology_files,
            extra_paths=self.extra_paths,
        )
        cache_dir = self.root / key
        cache_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = cache_dir / "manifest.json"
        if not manifest_path.exists():
            manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return cache_dir


__all__ = ["OntologyCache", "compute_cache_key", "hash_paths", "CACHE_VERSION"]
