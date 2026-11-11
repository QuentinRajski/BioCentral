"""
Intervalles de référence à partir d'une population de résultats (CLSI EP28-A3c).

  - estimation : méthode non paramétrique des rangs (rang = p·(n + 1)), limites
    aux percentiles 2,5 et 97,5, avec l'intervalle de confiance à 90 % de chaque
    limite : rangs de la loi binomiale à partir de 120 valeurs (tables CLSI),
    bootstrap entre 40 et 119 valeurs ;
  - vérification : part des résultats de la population situés hors d'un
    intervalle annoncé (fournisseur, littérature), critère CLSI des 10 %.

Les résultats « sous le seuil » / « au-dessus du seuil » comptent à leur rang,
avec pour valeur le seuil lui-même : si une limite tombe sur le seuil de mesure,
l'appelant doit l'afficher comme « ≤ seuil » et non comme une valeur exacte.

Ce module ne dépend ni de PySide6 ni de la base.
"""
import math
from dataclasses import dataclass, field

import numpy as np
from scipy import stats as sps

EFFECTIF_MINIMAL = 40        # en dessous, les percentiles 2,5 / 97,5 ne sont pas estimables par les rangs
EFFECTIF_RECOMMANDE = 120    # recommandation CLSI pour établir un intervalle de référence
EFFECTIF_VERIFICATION = 20   # effectif minimal CLSI pour vérifier un intervalle existant
TIRAGES_BOOTSTRAP = 2000


@dataclass
class IntervalleReference:
    n: int
    limite_basse: float | None
    limite_haute: float | None
    ic_basse: tuple[float, float] | None = None
    ic_haute: tuple[float, float] | None = None
    methode_ic: str | None = None           # "rangs" ou "bootstrap"
    avertissements: list[str] = field(default_factory=list)


@dataclass
class VerificationIntervalle:
    n: int
    n_sous: int
    n_sur: int
    pourcent_hors: float
    verdict: bool | None        # None : effectif insuffisant pour conclure

    @property
    def n_hors(self) -> int:
        return self.n_sous + self.n_sur


def _quantile_rangs(tri: np.ndarray, p: float) -> float:
    """Valeur de rang p·(n + 1) (rangs à partir de 1), interpolée linéairement."""
    n = len(tri)
    rang = min(max(p * (n + 1), 1.0), float(n))
    bas = int(math.floor(rang))
    haut = min(bas + 1, n)
    return float(tri[bas - 1] + (rang - bas) * (tri[haut - 1] - tri[bas - 1]))


def _rangs_ic_binomiale(n: int, p: float, confiance: float) -> tuple[int, int] | None:
    """Rangs (à partir de 1) encadrant le quantile p avec la confiance demandée.
    None si l'effectif est trop faible pour que le plus petit rang suffise."""
    queue = (1 - confiance) / 2
    cdf = sps.binom.cdf(np.arange(0, n + 1), n, p)
    bas = [k for k in range(1, n + 1) if cdf[k - 1] <= queue]
    haut = [k for k in range(1, n + 1) if cdf[k - 1] >= 1 - queue]
    if not bas or not haut:
        return None
    return max(bas), min(haut)


def estimer(valeurs, niveau: float = 0.95, confiance: float = 0.90, graine: int = 12345) -> IntervalleReference:
    """Intervalle de référence central (95 % par défaut) et IC à 90 % de ses limites."""
    tri = np.sort(np.array([float(v) for v in valeurs if v is not None], dtype=float))
    n = len(tri)
    p_bas = (1 - niveau) / 2
    p_haut = 1 - p_bas
    avertissements: list[str] = []

    if n < EFFECTIF_MINIMAL:
        avertissements.append(
            f"{n} résultat(s) : il en faut au moins {EFFECTIF_MINIMAL} pour estimer les percentiles "
            f"2,5 et 97,5 ({EFFECTIF_RECOMMANDE} recommandés par le CLSI)."
        )
        return IntervalleReference(n, None, None, avertissements=avertissements)

    resultat = IntervalleReference(n, _quantile_rangs(tri, p_bas), _quantile_rangs(tri, p_haut))

    rangs = _rangs_ic_binomiale(n, p_bas, confiance) if n >= EFFECTIF_RECOMMANDE else None
    if rangs is not None:
        bas, haut = rangs
        resultat.ic_basse = (float(tri[bas - 1]), float(tri[haut - 1]))
        resultat.ic_haute = (float(tri[n - haut]), float(tri[n - bas]))
        resultat.methode_ic = "rangs"
    else:
        rng = np.random.default_rng(graine)
        tirages = np.sort(rng.choice(tri, size=(TIRAGES_BOOTSTRAP, n), replace=True), axis=1)
        rang_bas = min(max(p_bas * (n + 1), 1.0), float(n)) - 1
        rang_haut = min(max(p_haut * (n + 1), 1.0), float(n)) - 1

        def colonne(rang: float) -> np.ndarray:
            b = int(math.floor(rang))
            h = min(b + 1, n - 1)
            return tirages[:, b] + (rang - b) * (tirages[:, h] - tirages[:, b])

        queue = 100 * (1 - confiance) / 2
        basses, hautes = colonne(rang_bas), colonne(rang_haut)
        resultat.ic_basse = (float(np.percentile(basses, queue)), float(np.percentile(basses, 100 - queue)))
        resultat.ic_haute = (float(np.percentile(hautes, queue)), float(np.percentile(hautes, 100 - queue)))
        resultat.methode_ic = "bootstrap"
        avertissements.append(
            f"{n} résultats : intervalle indicatif. Le CLSI recommande au moins {EFFECTIF_RECOMMANDE} "
            "sujets par groupe pour établir un intervalle de référence."
        )

    resultat.avertissements = avertissements
    return resultat


def verifier(valeurs, borne_basse: float | None, borne_haute: float | None) -> VerificationIntervalle:
    """
    Part des résultats hors de l'intervalle [borne_basse ; borne_haute] (une borne
    None n'est pas vérifiée). Critère CLSI EP28-A3c : l'intervalle est considéré
    comme transférable si au plus 10 % des résultats en sortent, sur au moins 20 sujets.
    """
    donnees = [float(v) for v in valeurs if v is not None]
    n = len(donnees)
    n_sous = sum(1 for v in donnees if borne_basse is not None and v < borne_basse)
    n_sur = sum(1 for v in donnees if borne_haute is not None and v > borne_haute)
    pourcent = 100 * (n_sous + n_sur) / n if n else 0.0
    verdict = (pourcent <= 10.0) if n >= EFFECTIF_VERIFICATION else None
    return VerificationIntervalle(n, n_sous, n_sur, pourcent, verdict)
