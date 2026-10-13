"""Research loop, conservative evidence status, and human export gate."""

from datetime import UTC, datetime
from pathlib import Path

from pdf_research.models import (
    Budget,
    Dossier,
    EtatRecherche,
    Orientation,
    Resultat,
    Revue,
    Statut,
)
from pdf_research.pdf.search import PDFSearchTool
from pdf_research.storage.checkpoint import charger, enregistrer, enregistrer_json


def _unique(preuves):
    seen = set()
    result = []
    for preuve in preuves:
        key = (preuve.source.fichier, preuve.source.page, preuve.extrait)
        if key not in seen:
            seen.add(key)
            result.append(preuve)
    return result


def _conclure(affirmation: str, preuves) -> Resultat:
    preuves = _unique(preuves)
    orientations = {preuve.orientation for preuve in preuves}
    if Orientation.APPUI in orientations and Orientation.CONTRADICTION in orientations:
        statut = Statut.CONTRADICTOIRE
        raison = "Passages concordants et contradictoires dans le corpus."
    elif Orientation.CONTRADICTION in orientations:
        statut = Statut.CONTREDITE
        raison = "Contradiction explicite détectée; contrôle humain requis."
    elif Orientation.APPUI in orientations:
        statut = Statut.ETAYEE
        raison = "Formulation concordante détectée; contrôle humain requis."
    elif preuves:
        statut = Statut.A_VERIFIER
        raison = "Passages proches sans concordance littérale vérifiable."
    else:
        statut = Statut.ABSENTE
        raison = (
            "Aucun passage pertinent trouvé dans les PDF indexés; cela ne prouve pas la fausseté."
        )
    primary = preuves[0] if preuves else None
    return Resultat(
        affirmation=affirmation,
        source=primary.source if primary else None,
        extrait=primary.extrait if primary else None,
        statut=statut,
        preuves=preuves,
        justification=raison,
    )


class ResearchEngine:
    def __init__(self, dossier_dir: Path, state_path: Path):
        self.dossier_dir = dossier_dir.resolve()
        self.state_path = state_path.resolve()
        self.tool = PDFSearchTool(self.dossier_dir)

    def creer_ou_reprendre(self, budget: Budget | None = None) -> EtatRecherche:
        manifest = Dossier.model_validate_json(
            (self.dossier_dir / "case.json").read_text(encoding="utf-8")
        )
        if self.state_path.exists():
            state = charger(self.state_path)
            if state.dossier != manifest or state.empreintes_pdf != self.tool.empreintes:
                raise ValueError("dossier ou PDF modifié depuis le checkpoint")
            if budget:
                if budget.max_appels < state.budget.max_appels:
                    raise ValueError("le budget ne peut pas diminuer à la reprise")
                if budget.max_boucles_par_affirmation != state.budget.max_boucles_par_affirmation:
                    raise ValueError("la limite des boucles ne peut pas changer à la reprise")
                state.budget.max_appels = budget.max_appels
                enregistrer(self.state_path, state)
            return state
        state = EtatRecherche(
            dossier=manifest,
            empreintes_pdf=self.tool.empreintes,
            budget=budget or Budget(),
        )
        enregistrer(self.state_path, state)
        return state

    def executer(self, state: EtatRecherche) -> EtatRecherche:
        if state.revue:
            raise ValueError("ce dossier est déjà validé")
        while state.index_affirmation < len(state.dossier.affirmations):
            if (
                not state.recherche_en_cours
                and state.essai_courant >= state.budget.max_boucles_par_affirmation
            ):
                self._terminer_affirmation(state)
                continue
            if state.appels_utilises >= state.budget.max_appels:
                break
            affirmation = state.dossier.affirmations[state.index_affirmation]
            # Reserve every invocation durably. An interrupted call is retried at the same loop
            # position and consumes another call from the budget.
            threshold = max(0.35, 0.8 - 0.2 * state.essai_courant)
            state.appels_utilises += 1
            state.recherche_en_cours = True
            enregistrer(self.state_path, state)
            hits = self.tool.rechercher(affirmation, min_overlap=threshold)
            state.preuves_courantes = _unique([*state.preuves_courantes, *hits])
            state.essai_courant += 1
            state.recherche_en_cours = False
            enregistrer(self.state_path, state)
            if state.essai_courant >= state.budget.max_boucles_par_affirmation:
                self._terminer_affirmation(state)
        return state

    def _terminer_affirmation(self, state: EtatRecherche) -> None:
        affirmation = state.dossier.affirmations[state.index_affirmation]
        state.resultats.append(_conclure(affirmation, state.preuves_courantes))
        state.index_affirmation += 1
        state.essai_courant = 0
        state.recherche_en_cours = False
        state.preuves_courantes = []
        enregistrer(self.state_path, state)


def approuver(state_path: Path, valideur: str, commentaire: str = "") -> EtatRecherche:
    state = charger(state_path)
    if state.index_affirmation != len(state.dossier.affirmations):
        raise ValueError("recherche incomplète; validation impossible")
    if state.revue:
        raise ValueError("dossier déjà validé")
    state.revue = Revue(
        valideur=valideur.strip(),
        date_utc=datetime.now(UTC).isoformat(),
        commentaire=commentaire,
    )
    enregistrer(state_path, state)
    return state


def exporter(state_path: Path, output_path: Path) -> None:
    if state_path.resolve() == output_path.resolve():
        raise ValueError("l'export ne peut pas remplacer le checkpoint")
    state = charger(state_path)
    if not state.revue:
        raise ValueError("validation humaine requise avant export")
    enregistrer_json(
        output_path,
        {
            "dossier": state.dossier.model_dump(mode="json"),
            "resultats": [result.model_dump(mode="json") for result in state.resultats],
            "revue": state.revue.model_dump(mode="json"),
            "budget": state.budget.model_dump(mode="json"),
            "appels_utilises": state.appels_utilises,
            "empreintes_pdf": state.empreintes_pdf,
        },
    )
