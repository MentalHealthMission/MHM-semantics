"""Parse inline ODIM metadata from derived feature scripts."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


COMPUTATION_RE = re.compile(r"#\s*odim:computation", re.IGNORECASE)


def extract_column_from_code(line: str) -> Optional[str]:
    if "[" in line and "]" in line:
        match = re.search(r"\[(?:'|\")(.*?)(?:'|\")\]", line)
        if match:
            return match.group(1)
    if "=" in line:
        left = line.split("=", 1)[0].strip()
        if left.startswith("df["):
            match = re.search(r"df\[(?:'|\")(.*?)(?:'|\")\]", left)
            if match:
                return match.group(1)
    return None


def parse_comment_meta(comment: str) -> Dict[str, Any]:
    if not comment.lower().startswith("odim:"):
        return {}
    odim_feature = None
    category = None
    doc = None
    column = None
    for part in comment.split("|"):
        token = part.strip()
        if token.lower().startswith("odim:"):
            odim_feature = token
        elif token.lower().startswith("category:"):
            category = token.split(":", 1)[1].strip()
        elif token.lower().startswith("column:"):
            column = token.split(":", 1)[1].strip()
        elif token.lower().startswith("doc=") or token.lower().startswith("doc:"):
            doc = token.split("=", 1)[1].strip() if "=" in token else token.split(":", 1)[1].strip()
    return {
        "odim_feature": odim_feature,
        "category": category,
        "doc": doc,
        "column": column,
    }


def parse_computation_comment(comment: str) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    for part in comment.split("|"):
        token = part.strip()
        if token.lower().startswith("odim:computation"):
            continue
        if token.startswith("id="):
            payload["id"] = token.split("=", 1)[1].strip()
        elif token.startswith("type="):
            payload["type"] = token.split("=", 1)[1].strip()
        elif token.startswith("label="):
            payload["label"] = token.split("=", 1)[1].strip()
        elif token.startswith("uses="):
            uses = token.split("=", 1)[1].strip()
            payload["uses"] = [item.strip() for item in uses.split(",") if item.strip()]
    return payload


def parse_inline_metadata(path: Path) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, Any]]:
    inline: Dict[str, Dict[str, Any]] = {}
    computation: Dict[str, Any] = {}
    pending_meta: Optional[Dict[str, Any]] = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if "# odim:" not in raw:
            if pending_meta:
                if not raw.strip() or raw.lstrip().startswith("#"):
                    continue
                column = extract_column_from_code(raw)
                if column:
                    pending_meta.pop("column", None)
                    inline[column] = pending_meta
                pending_meta = None
            continue
        code, comment = raw.split("#", 1)
        comment = comment.strip()
        if COMPUTATION_RE.search(f"#{comment}"):
            computation = parse_computation_comment(comment)
            continue
        meta = parse_comment_meta(comment)
        if not meta:
            continue
        column = meta.get("column")
        if not column and code.strip():
            column = extract_column_from_code(code)
        if column:
            meta.pop("column", None)
            inline[column] = meta
            pending_meta = None
        else:
            pending_meta = meta
    return inline, computation


def resolve_inline(
    inline: Dict[str, Dict[str, Any]],
    column: str,
) -> Optional[Dict[str, Any]]:
    if column in inline:
        return inline[column]
    for key, meta in inline.items():
        if "{segment}" in key:
            pattern = "^" + re.escape(key).replace("\\{segment\\}", ".+") + "$"
            if re.match(pattern, column):
                return meta
    return None

