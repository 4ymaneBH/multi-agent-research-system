"""Atomic JSON checkpoints for interruption-safe local runs."""

import json
import os
import tempfile
from pathlib import Path

from pdf_research.models import EtatRecherche


def enregistrer_json(path: Path, payload: dict) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", suffix=".tmp", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def enregistrer(path: Path, state: EtatRecherche) -> None:
    enregistrer_json(path, state.model_dump(mode="json"))


def charger(path: Path) -> EtatRecherche:
    return EtatRecherche.model_validate_json(path.read_text(encoding="utf-8"))
