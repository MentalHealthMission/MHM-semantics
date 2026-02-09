"""Rule catalog extraction utilities."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Tuple
import re
import shlex


CONSTRUCT_RE = re.compile(r"CONSTRUCT\s*\{.*?\ba\s+(odim:[A-Za-z0-9_]+)", re.S)
CLASS_RE = re.compile(r"\ba\s+(odim:[A-Za-z0-9_]+)")
COMMENT_RE = re.compile(r"rdfs:comment\s+\"([^\"]+)\"")
PLACEHOLDER_RE = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")
VALUES_RE = re.compile(r"VALUES\s*\(([^)]*)\)\s*\{([^}]*)\}", re.IGNORECASE | re.DOTALL)
TUPLE_RE = re.compile(r"\(([^)]*)\)")


def _coerce_literal(value: str) -> Any:
    text = value.strip()
    if not text:
        return ""
    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        text = text[1:-1]
    try:
        if "." in text:
            return float(text)
        return int(text)
    except ValueError:
        return text


def extract_rule_tokens(path: Path) -> List[Dict[str, Any]]:
    text = path.read_text(encoding="utf-8")
    defaults: Dict[str, Any] = {}
    for block in VALUES_RE.finditer(text):
        vars_raw = block.group(1)
        body = block.group(2)
        var_names = [item.strip().lstrip("?") for item in vars_raw.split() if item.strip()]
        if not var_names:
            continue
        tuple_match = TUPLE_RE.search(body)
        if not tuple_match:
            continue
        try:
            values = shlex.split(tuple_match.group(1).strip())
        except ValueError:
            values = tuple_match.group(1).strip().split()
        if not values:
            continue
        for idx, var_name in enumerate(var_names):
            if idx >= len(values) or not var_name:
                continue
            if var_name not in defaults:
                defaults[var_name] = _coerce_literal(values[idx])

    token_names = set(PLACEHOLDER_RE.findall(text)) | set(defaults.keys())
    tokens: List[Dict[str, Any]] = []
    for name in sorted(token_names):
        token: Dict[str, Any] = {"name": name, "has_default": name in defaults}
        if name in defaults:
            token["default"] = defaults[name]
        tokens.append(token)
    return tokens


def extract_rule_dependencies(path: Path, repo_root: Path) -> Tuple[str, List[str], str, str | None]:
    text = path.read_text(encoding="utf-8")
    construct = CONSTRUCT_RE.search(text)
    if not construct:
        raise ValueError(f"Unable to find CONSTRUCT class in {path}")
    phenotype = construct.group(1)
    classes = set(CLASS_RE.findall(text))
    classes.discard(phenotype)
    classes.discard("odim:Participant")
    comment_match = COMMENT_RE.search(text)
    comment = comment_match.group(1).strip() if comment_match else None
    rel_path = path
    try:
        rel_path = path.relative_to(repo_root)
    except ValueError:
        rel_path = path
    return phenotype, sorted(classes), str(rel_path.as_posix()), comment


def extract_phenotype_catalog(rules_dir: Path, repo_root: Path) -> Dict[str, dict]:
    phenotypes: Dict[str, dict] = {}
    if not rules_dir.exists():
        return phenotypes
    for rule in sorted(rules_dir.glob("*.rq")):
        phenotype, deps, rel_path, comment = extract_rule_dependencies(rule, repo_root)
        phenotypes[phenotype] = {
            "rule": rel_path,
            "depends_on": deps,
            "doc": comment,
            "tokens": extract_rule_tokens(rule),
        }
    return phenotypes


__all__ = ["extract_phenotype_catalog", "extract_rule_dependencies", "extract_rule_tokens"]
