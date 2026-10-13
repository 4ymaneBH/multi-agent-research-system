"""Validated input, evidence, and report formats."""

from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator


class Statut(StrEnum):
    ETAYEE = "etayee"
    CONTREDITE = "contredite"
    CONTRADICTOIRE = "contradictoire"
    ABSENTE = "preuve_absente"
    A_VERIFIER = "a_verifier"


class Orientation(StrEnum):
    APPUI = "appui"
    CONTRADICTION = "contradiction"
    INDETERMINEE = "indeterminee"


class Source(BaseModel):
    fichier: str = Field(min_length=1)
    page: int = Field(ge=1)


class Preuve(BaseModel):
    source: Source
    extrait: str = Field(min_length=1)
    orientation: Orientation
    score: float = Field(ge=0, le=1)


class Resultat(BaseModel):
    affirmation: str = Field(min_length=1)
    source: Source | None = None
    extrait: str | None = None
    statut: Statut
    preuves: list[Preuve] = Field(default_factory=list)
    justification: str = ""

    @model_validator(mode="after")
    def validate_primary_evidence(self) -> "Resultat":
        if (self.source is None) != (self.extrait is None):
            raise ValueError("source et extrait doivent être renseignés ensemble")
        if self.preuves and (
            self.source != self.preuves[0].source or self.extrait != self.preuves[0].extrait
        ):
            raise ValueError("source et extrait doivent pointer vers la première preuve")
        if not self.preuves and self.source is not None:
            raise ValueError("source et extrait nécessitent une preuve")
        if self.statut == Statut.ABSENTE and self.preuves:
            raise ValueError("une preuve absente ne peut pas avoir d'extrait")
        if self.statut != Statut.ABSENTE and not self.preuves:
            raise ValueError("un résultat avec preuve doit contenir au moins un extrait")
        return self


class Dossier(BaseModel):
    id: str = Field(min_length=1)
    affirmations: list[str] = Field(min_length=1)

    @field_validator("affirmations")
    @classmethod
    def non_empty_claims(cls, values: list[str]) -> list[str]:
        if any(not value.strip() for value in values):
            raise ValueError("les affirmations ne peuvent pas être vides")
        return values


class Budget(BaseModel):
    max_appels: int = Field(default=40, ge=1)
    max_boucles_par_affirmation: int = Field(default=2, ge=1, le=5)


class Revue(BaseModel):
    valideur: str = Field(min_length=1)
    date_utc: str
    commentaire: str = ""


class EtatRecherche(BaseModel):
    version: int = 1
    dossier: Dossier
    empreintes_pdf: dict[str, str]
    budget: Budget
    appels_utilises: int = Field(default=0, ge=0)
    index_affirmation: int = Field(default=0, ge=0)
    essai_courant: int = Field(default=0, ge=0)
    recherche_en_cours: bool = False
    preuves_courantes: list[Preuve] = Field(default_factory=list)
    resultats: list[Resultat] = Field(default_factory=list)
    revue: Revue | None = None

    @model_validator(mode="after")
    def check_progress(self) -> "EtatRecherche":
        if self.index_affirmation != len(self.resultats):
            raise ValueError("l'index doit suivre les résultats terminés")
        if self.index_affirmation > len(self.dossier.affirmations):
            raise ValueError("trop de résultats")
        if self.appels_utilises > self.budget.max_appels:
            raise ValueError("budget dépassé")
        if self.essai_courant > self.budget.max_boucles_par_affirmation:
            raise ValueError("limite de boucles dépassée")
        if (
            self.recherche_en_cours
            and self.essai_courant >= self.budget.max_boucles_par_affirmation
        ):
            raise ValueError("une recherche réservée doit avoir une boucle disponible")
        if self.revue and self.index_affirmation != len(self.dossier.affirmations):
            raise ValueError("revue impossible avant la fin de la recherche")
        return self
