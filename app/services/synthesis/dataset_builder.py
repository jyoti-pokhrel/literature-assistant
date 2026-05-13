from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


DEFAULT_DATASET_PATH = Path(__file__).resolve().parent.parent.parent.parent / "data" / "research_gap_dataset.jsonl"


def dataset_path() -> Path:
    configured = os.getenv("RESEARCH_GAP_DATASET_PATH")
    return Path(configured).expanduser() if configured else DEFAULT_DATASET_PATH


MAX_DATASET_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB cap


def append_gap_dataset_record(record: dict[str, Any]) -> str | None:
    """Append one synthesis run as JSONL with size-based rotation."""
    path = dataset_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # Simple rotation: if file > 10MB, move to .bak and start fresh
        if path.exists() and path.stat().st_size > MAX_DATASET_SIZE_BYTES:
            bak_path = path.with_suffix(".jsonl.bak")
            if bak_path.exists():
                bak_path.unlink()
            path.rename(bak_path)
            
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return str(path)
    except OSError:
        return None
