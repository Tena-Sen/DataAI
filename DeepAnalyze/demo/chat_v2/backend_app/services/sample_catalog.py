from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException


SAMPLE_DATA_ROOT = (
    Path(__file__).resolve().parents[2] / "demo_datasets_20260815"
).resolve()
SAMPLE_CATALOG_PATH = SAMPLE_DATA_ROOT / "catalog.json"


@lru_cache(maxsize=1)
def _load_catalog() -> tuple[dict, ...]:
    try:
        payload = json.loads(SAMPLE_CATALOG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Unable to load sample data catalog: {exc}") from exc

    datasets = payload.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        raise RuntimeError("Sample data catalog must contain datasets")

    seen_ids: set[str] = set()
    normalized: list[dict] = []
    for dataset in datasets:
        dataset_id = str(dataset.get("id", "")).strip()
        files = dataset.get("files")
        questions = dataset.get("questions")
        if (
            not dataset_id
            or dataset_id in seen_ids
            or not isinstance(files, list)
            or not files
            or not isinstance(questions, list)
            or not questions
        ):
            raise RuntimeError(f"Invalid sample dataset entry: {dataset_id or '<missing>'}")
        seen_ids.add(dataset_id)
        normalized.append(dataset)
    return tuple(normalized)


def list_sample_datasets() -> list[dict]:
    return [
        {
            "id": dataset["id"],
            "kind": dataset["kind"],
            "title": dataset["title"],
            "description": dataset["description"],
            "files": [Path(path).name for path in dataset["files"]],
            "questions": dataset["questions"],
        }
        for dataset in _load_catalog()
    ]


def get_sample_dataset(dataset_id: str) -> dict:
    normalized_id = str(dataset_id or "").strip()
    for dataset in _load_catalog():
        if dataset["id"] == normalized_id:
            return dataset
    raise HTTPException(status_code=404, detail="Unknown sample dataset")


def resolve_sample_files(dataset: dict) -> list[Path]:
    sources: list[Path] = []
    for relative_path in dataset["files"]:
        source = (SAMPLE_DATA_ROOT / str(relative_path)).resolve()
        if source != SAMPLE_DATA_ROOT and SAMPLE_DATA_ROOT not in source.parents:
            raise RuntimeError("Sample data path escapes the catalog root")
        if not source.is_file():
            raise RuntimeError(f"Sample data file does not exist: {relative_path}")
        sources.append(source)
    return sources
