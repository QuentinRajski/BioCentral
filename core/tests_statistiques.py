"""
Tests statistiques optionnels — normalité, valeurs aberrantes, comparaison de
groupes. Séparés de core/stats.py (qui ne dépend que de la bibliothèque
standard) parce que ces tests nécessitent scipy, une dépendance plus lourde
qui ne sert qu'ici.
"""
from dataclasses import dataclass

from scipy import stats as scipy_stats


@dataclass
class ResultatNormalite:
    p_valeur: float
    normale: bool  # True si on ne peut pas rejeter l'hypothèse de normalité (p > 0.05)


def test_normalite(valeurs: list[float]) -> ResultatNormalite | None:
    """Shapiro-Wilk. None si l'échantillon est trop petit (< 3) pour être testé."""
    if len(valeurs) < 3:
        return None
    _, p = scipy_stats.shapiro(valeurs)
    return ResultatNormalite(p_valeur=round(p, 4), normale=(p > 0.05))


@dataclass
class ResultatAberrantes:
    n_sous: int
    n_sur: int
    borne_basse: float
    borne_haute: float


def detecter_aberrantes(valeurs: list[float], q1: float, q3: float) -> ResultatAberrantes:
    """
    Méthode IQR (Tukey) : une valeur est aberrante si elle sort de
    [Q1 - 1.5*IQR ; Q3 + 1.5*IQR]. Différent du statut 'hors bornes' existant,
    qui se base sur le domaine de mesure de la machine, pas sur la distribution
    observée de l'échantillon filtré.
    """
    iqr = q3 - q1
    basse = q1 - 1.5 * iqr
    haute = q3 + 1.5 * iqr
    return ResultatAberrantes(
        n_sous=sum(1 for v in valeurs if v < basse),
        n_sur=sum(1 for v in valeurs if v > haute),
        borne_basse=round(basse, 3),
        borne_haute=round(haute, 3),
    )


@dataclass
class ResultatComparaison:
    p_valeur: float
    significatif: bool
    n_a: int
    n_b: int


def comparer_deux_groupes(valeurs_a: list[float], valeurs_b: list[float]) -> ResultatComparaison | None:
    """Mann-Whitney U (non paramétrique — adapté à des distributions non normales,
    ce qui est le cas fréquent en biologie médicale). None si un groupe est vide."""
    if not valeurs_a or not valeurs_b:
        return None
    try:
        _, p = scipy_stats.mannwhitneyu(valeurs_a, valeurs_b, alternative="two-sided")
    except ValueError:
        return None
    return ResultatComparaison(
        p_valeur=round(p, 4), significatif=(p < 0.05), n_a=len(valeurs_a), n_b=len(valeurs_b),
    )
