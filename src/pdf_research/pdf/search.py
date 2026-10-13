"""Lexical passage search with exact PDF page provenance."""

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader

from pdf_research.models import Orientation, Preuve, Source

_STOP = {
    "a",
    "an",
    "and",
    "de",
    "des",
    "du",
    "est",
    "is",
    "la",
    "le",
    "les",
    "of",
    "the",
    "un",
    "une",
}
_NEGATION = {"aucun", "jamais", "ne", "n", "not", "pas", "no"}
_AUXILIARY = {"do", "does", "did"}


def _tokens(value: str) -> list[str]:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    without_accents = "".join(c for c in normalized if not unicodedata.combining(c))
    return re.findall(r"[a-z0-9]+", without_accents)


def _keywords(value: str) -> list[str]:
    return [token for token in _tokens(value) if token not in _STOP]


def _orientation(affirmation: str, extrait: str) -> Orientation:
    claim_tokens = _keywords(affirmation)
    claim = [token for token in claim_tokens if token not in _NEGATION]
    excerpt = _keywords(extrait)
    core = [token for token in excerpt if token not in _NEGATION | _AUXILIARY]
    if not claim:
        return Orientation.INDETERMINEE
    if _ordered_subset(claim, core):
        claim_negative = any(token in _NEGATION for token in claim_tokens)
        excerpt_negative = any(token in _NEGATION for token in excerpt)
        return (
            Orientation.APPUI if claim_negative == excerpt_negative else Orientation.CONTRADICTION
        )
    claim_words = [token for token in claim if not token.isdigit()]
    core_words = [token for token in core if not token.isdigit()]
    claim_numbers = {token for token in claim if token.isdigit()}
    core_numbers = {token for token in core if token.isdigit()}
    if (
        claim_numbers
        and core_numbers
        and claim_numbers.isdisjoint(core_numbers)
        and _ordered_subset(claim_words, core_words)
    ):
        return Orientation.CONTRADICTION
    return Orientation.INDETERMINEE


def _ordered_subset(needles: list[str], haystack: list[str]) -> bool:
    iterator = iter(haystack)
    return all(any(token == needle for token in iterator) for needle in needles)


@dataclass(frozen=True)
class Passage:
    source: Source
    texte: str


class PDFSearchTool:
    """Index text passages from PDFs and retrieve cited excerpts."""

    def __init__(self, root: Path):
        self.root = root.resolve()
        pdfs = sorted(self.root.rglob("*.pdf"))
        if not pdfs:
            raise ValueError(f"aucun PDF dans {self.root}")
        self.empreintes: dict[str, str] = {}
        self.passages: list[Passage] = []
        self.pages_sans_texte: list[Source] = []
        for pdf in pdfs:
            relative = pdf.relative_to(self.root).as_posix()
            self.empreintes[relative] = hashlib.sha256(pdf.read_bytes()).hexdigest()
            reader = PdfReader(str(pdf))
            for page_number, page in enumerate(reader.pages, start=1):
                source = Source(fichier=relative, page=page_number)
                text = page.extract_text() or ""
                if not text.strip():
                    self.pages_sans_texte.append(source)
                    continue
                text = re.sub(r"\s+", " ", text).strip()
                for chunk in re.split(r"(?<=[.!?])\s+", text):
                    if chunk.strip():
                        self.passages.append(Passage(source, chunk.strip()))
        if not self.passages:
            raise ValueError("aucun texte extractible dans les PDF (OCR nécessaire ?)")

    def rechercher(self, requete: str, limit: int = 12, min_overlap: float = 0.5) -> list[Preuve]:
        """Return ranked passages; a hit is never itself proof of a claim."""
        if limit < 1:
            raise ValueError("limit doit être positif")
        if not 0 < min_overlap <= 1:
            raise ValueError("min_overlap doit être dans ]0, 1]")
        query = set(_keywords(requete)) - _NEGATION
        if not query:
            return []
        ranked: list[Preuve] = []
        for passage in self.passages:
            words = set(_keywords(passage.texte)) - _NEGATION - _AUXILIARY
            overlap = len(query & words) / len(query)
            if overlap < min_overlap:
                continue
            ranked.append(
                Preuve(
                    source=passage.source,
                    extrait=passage.texte,
                    orientation=_orientation(requete, passage.texte),
                    score=round(overlap, 4),
                )
            )
        ranked.sort(key=lambda hit: (-hit.score, hit.source.fichier, hit.source.page, hit.extrait))
        return ranked[:limit]
