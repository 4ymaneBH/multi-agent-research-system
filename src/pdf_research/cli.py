"""Command-line interface for local PDF research dossiers."""

import argparse
import json
import sys
from pathlib import Path

from pdf_research.models import Budget
from pdf_research.pdf.search import PDFSearchTool
from pdf_research.research.engine import ResearchEngine, approuver, exporter
from pdf_research.storage.checkpoint import charger


def _afficher(state) -> None:
    print(f"Dossier: {state.dossier.id}")
    print(f"Progression: {len(state.resultats)}/{len(state.dossier.affirmations)}")
    print(f"Appels: {state.appels_utilises}/{state.budget.max_appels}")
    print(f"Validation: {state.revue.valideur if state.revue else 'en attente'}")
    for number, result in enumerate(state.resultats, start=1):
        print(f"\n{number}. [{result.statut.value}] {result.affirmation}")
        print(f"   {result.justification}")
        for preuve in result.preuves:
            print(
                f"   {preuve.source.fichier}, p. {preuve.source.page} "
                f"({preuve.orientation.value}): {preuve.extrait}"
            )


def _run(args, resume_only: bool) -> None:
    state_path = Path(args.state)
    if resume_only and not state_path.exists():
        raise FileNotFoundError(f"checkpoint absent: {state_path}")
    engine = ResearchEngine(Path(args.dossier), state_path)
    budget = None
    if state_path.exists() and args.max_calls is not None:
        prior = charger(state_path)
        budget = Budget(
            max_appels=args.max_calls,
            max_boucles_par_affirmation=prior.budget.max_boucles_par_affirmation,
        )
    elif not state_path.exists():
        budget = Budget(
            max_appels=args.max_calls if args.max_calls is not None else 40,
            max_boucles_par_affirmation=args.max_loops if args.max_loops is not None else 2,
        )
    if state_path.exists() and args.max_loops is not None:
        raise ValueError("max-loops est fixé lors de la création du dossier")
    state = engine.creer_ou_reprendre(budget)
    engine.executer(state)
    _afficher(state)
    if len(state.resultats) < len(state.dossier.affirmations):
        print("Budget épuisé. Reprendre avec --max-calls plus élevé.")


def _review(args) -> None:
    if not sys.stdin.isatty():
        raise ValueError("la validation nécessite un terminal interactif")
    state = charger(Path(args.state))
    if len(state.resultats) != len(state.dossier.affirmations):
        raise ValueError("recherche incomplète")
    _afficher(state)
    for number, result in enumerate(state.resultats, start=1):
        print(f"\nVérifier le résultat {number}: {result.affirmation}")
        answer = input("Entrée pour accepter, q pour interrompre: ").strip().lower()
        if answer != "":
            print("Validation interrompue; aucun export autorisé.")
            return
    if input("Saisir VALIDER pour autoriser l'export: ").strip() != "VALIDER":
        print("Validation interrompue; aucun export autorisé.")
        return
    approuver(Path(args.state), args.reviewer, args.comment)
    print("Validation enregistrée.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="pdf-research")
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="chercher des extraits dans les PDF")
    search.add_argument("dossier")
    search.add_argument("query")
    for name in ("run", "resume"):
        command = commands.add_parser(name, help="exécuter ou reprendre la recherche")
        command.add_argument("dossier")
        command.add_argument("--state", required=True)
        command.add_argument("--max-calls", type=int)
        command.add_argument("--max-loops", type=int)
    show = commands.add_parser("show", help="afficher les preuves et la progression")
    show.add_argument("state")
    review = commands.add_parser("review", help="valider les résultats en personne")
    review.add_argument("state")
    review.add_argument("--reviewer", required=True)
    review.add_argument("--comment", default="")
    export = commands.add_parser("export", help="exporter un rapport JSON validé")
    export.add_argument("state")
    export.add_argument("--output", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "search":
            tool = PDFSearchTool(Path(args.dossier))
            print(
                json.dumps(
                    [hit.model_dump(mode="json") for hit in tool.rechercher(args.query)],
                    ensure_ascii=False,
                    indent=2,
                )
            )
        elif args.command in ("run", "resume"):
            _run(args, resume_only=args.command == "resume")
        elif args.command == "show":
            _afficher(charger(Path(args.state)))
        elif args.command == "review":
            _review(args)
        elif args.command == "export":
            exporter(Path(args.state), Path(args.output))
            print(f"Export créé: {args.output}")
    except (ValueError, FileNotFoundError, OSError) as exc:
        print(f"Erreur: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
