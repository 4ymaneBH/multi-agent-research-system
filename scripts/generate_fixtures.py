"""Recreate the 20 small, text-based PDF evaluation dossiers offline."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "cases"
TECHNOLOGIES = ("PostgreSQL", "Redis", "Kafka", "SQLite", "Elasticsearch")
KINDS = ("etayee", "contredite", "preuve_absente", "contradictoire")


def pdf_bytes(pages: list[str]) -> bytes:
    """Build a minimal valid PDF with searchable ASCII text on each page."""
    objects: dict[int, bytes] = {}
    page_ids = [3 + 2 * i for i in range(len(pages))]
    font_id = 3 + 2 * len(pages)
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = b" ".join(f"{number} 0 R".encode() for number in page_ids)
    objects[2] = (
        b"<< /Type /Pages /Kids [" + kids + b"] /Count " + str(len(pages)).encode() + b" >>"
    )
    for index, text in enumerate(pages):
        page_id = page_ids[index]
        content_id = page_id + 1
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii")
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> /Contents {content_id} 0 R >>"
        ).encode()
        objects[content_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode() + stream + b"\nendstream"
        )
    objects[font_id] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number in range(1, font_id + 1):
        offsets.append(len(data))
        data.extend(f"{number} 0 obj\n".encode() + objects[number] + b"\nendobj\n")
    xref = len(data)
    data.extend(f"xref\n0 {font_id + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]:
        data.extend(f"{offset:010d} 00000 n \n".encode())
    data.extend(
        f"trailer\n<< /Size {font_id + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    )
    return bytes(data)


def main() -> None:
    for number in range(1, 21):
        kind = KINDS[(number - 1) % len(KINDS)]
        name = f"Atlas{number:02d}"
        technology = TECHNOLOGIES[(number - 1) % len(TECHNOLOGIES)]
        claim = f"Project {name} will use {technology}."
        positive = claim
        negative = f"Project {name} will not use {technology}."
        pages = {
            "etayee": [f"Technical note for {name}.", positive],
            "contredite": [f"Technical note for {name}.", negative],
            "preuve_absente": [
                "Warehouse inventory was checked today.",
                "Maintenance was completed in July.",
            ],
            "contradictoire": [positive, negative],
        }[kind]
        case_dir = ROOT / f"{number:02d}_{kind}"
        documents = case_dir / "documents"
        documents.mkdir(parents=True, exist_ok=True)
        (documents / "report.pdf").write_bytes(pdf_bytes(pages))
        (case_dir / "case.json").write_text(
            json.dumps({"id": case_dir.name, "affirmations": [claim]}, indent=2) + "\n",
            encoding="utf-8",
        )
        (case_dir / "expected.json").write_text(
            json.dumps(
                {
                    "statut": kind,
                    "page": None
                    if kind == "preuve_absente"
                    else (1 if kind == "contradictoire" else 2),
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
