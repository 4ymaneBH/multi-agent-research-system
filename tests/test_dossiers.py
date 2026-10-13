"""Integration checks against the 20 committed PDF dossiers."""

import json
from pathlib import Path

import pytest

from pdf_research.models import Budget, Statut
from pdf_research.pdf.search import PDFSearchTool
from pdf_research.research.engine import ResearchEngine, approuver, exporter
from pdf_research.storage.checkpoint import charger
from scripts.generate_fixtures import pdf_bytes

CASES = Path(__file__).resolve().parents[1] / "fixtures" / "cases"


@pytest.mark.parametrize("case_dir", sorted(CASES.iterdir()), ids=lambda path: path.name)
def test_dossier(case_dir: Path, tmp_path: Path) -> None:
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    state_path = tmp_path / "state.json"
    engine = ResearchEngine(case_dir, state_path)
    state = engine.creer_ou_reprendre(Budget(max_appels=2, max_boucles_par_affirmation=2))
    engine.executer(state)

    assert state.appels_utilises == 2
    assert len(state.resultats) == 1
    result = state.resultats[0]
    assert result.statut == Statut(expected["statut"])
    assert (result.source.page if result.source else None) == expected["page"]
    if expected["page"] is None:
        assert result.extrait is None
        assert result.preuves == []
    else:
        assert result.extrait
        assert result.source.fichier == "documents/report.pdf"
        assert all(hit.source.page in (1, 2) for hit in result.preuves)
    assert charger(state_path) == state


def test_budget_resume_and_export_gate(tmp_path: Path) -> None:
    case_dir = CASES / "04_contradictoire"
    state_path = tmp_path / "run.json"
    output_path = tmp_path / "export.json"
    engine = ResearchEngine(case_dir, state_path)
    state = engine.creer_ou_reprendre(Budget(max_appels=1, max_boucles_par_affirmation=2))
    engine.executer(state)
    assert state.appels_utilises == 1
    assert not state.resultats
    with pytest.raises(ValueError, match="validation humaine"):
        exporter(state_path, output_path)
    with pytest.raises(ValueError, match="incomplète"):
        approuver(state_path, "Analyste")

    resumed = engine.creer_ou_reprendre(Budget(max_appels=2, max_boucles_par_affirmation=2))
    engine.executer(resumed)
    assert resumed.resultats[0].statut == Statut.CONTRADICTOIRE
    with pytest.raises(ValueError, match="validation humaine"):
        exporter(state_path, output_path)
    approuver(state_path, "Analyste", "Passages et pages vérifiés")
    with pytest.raises(ValueError, match="checkpoint"):
        exporter(state_path, state_path)
    exporter(state_path, output_path)
    exported = json.loads(output_path.read_text(encoding="utf-8"))
    assert exported["revue"]["valideur"] == "Analyste"
    assert exported["resultats"][0]["statut"] == "contradictoire"
    assert exported["appels_utilises"] == 2


def test_interruption_reserves_call_and_resume(tmp_path: Path, monkeypatch) -> None:
    case_dir = CASES / "01_etayee"
    state_path = tmp_path / "run.json"
    engine = ResearchEngine(case_dir, state_path)
    state = engine.creer_ou_reprendre(Budget(max_appels=2, max_boucles_par_affirmation=1))

    def interrupt(*args, **kwargs):
        raise KeyboardInterrupt

    original = engine.tool.rechercher
    monkeypatch.setattr(engine.tool, "rechercher", interrupt)
    with pytest.raises(KeyboardInterrupt):
        engine.executer(state)
    saved = charger(state_path)
    assert saved.appels_utilises == 1
    assert saved.essai_courant == 0
    assert saved.recherche_en_cours

    monkeypatch.setattr(engine.tool, "rechercher", original)
    engine.executer(engine.creer_ou_reprendre())
    assert charger(state_path).resultats[0].statut == Statut.ETAYEE


def test_corpus_change_blocks_resume(tmp_path: Path) -> None:
    source = CASES / "02_contredite"
    copied = tmp_path / "case"
    copied.mkdir()
    (copied / "documents").mkdir()
    (copied / "case.json").write_bytes((source / "case.json").read_bytes())
    pdf = copied / "documents" / "report.pdf"
    pdf.write_bytes((source / "documents" / "report.pdf").read_bytes())
    state_path = tmp_path / "state.json"
    engine = ResearchEngine(copied, state_path)
    engine.creer_ou_reprendre()
    pdf.write_bytes(pdf.read_bytes() + b"\n")
    with pytest.raises(ValueError, match="modifié"):
        ResearchEngine(copied, state_path).creer_ou_reprendre()


def test_negated_claim_and_numeric_contradiction(tmp_path: Path) -> None:
    (tmp_path / "facts.pdf").write_bytes(
        pdf_bytes(["Project Vega will not use Redis.", "Project Vega has 12 servers."])
    )
    search = PDFSearchTool(tmp_path)
    negative = search.rechercher("Project Vega will not use Redis.")
    assert negative[0].orientation.value == "appui"
    numeric = search.rechercher("Project Vega has 10 servers.")
    assert numeric[0].orientation.value == "contradiction"
    assert numeric[0].source.page == 2
