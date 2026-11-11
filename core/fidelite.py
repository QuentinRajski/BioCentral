"""
Études de fidélité (précision) et de justesse d'une méthode de dosage.

  - répétabilité : n dosages du même échantillon dans une même série
    -> moyenne, écart-type, CV et leur intervalle de confiance ;
  - fidélité intermédiaire avec plusieurs séries (ex. 5 jours × 5 répétitions,
    protocole de type CLSI EP15) : analyse de variance à un facteur aléatoire
    -> composante intra-série (répétabilité), composante inter-séries, et
    fidélité intermédiaire (intra-laboratoire) = somme des deux variances ;
  - justesse : biais de la moyenne par rapport à une valeur cible.

Ce module ne dépend ni de PySide6 ni de la base.
"""
import math
from dataclasses import dataclass

import numpy as np
from scipy import stats as sps


@dataclass
class ResultatSerie:
    """Statistiques d'une série unique de dosages répétés."""
    n: int
    moyenne: float
    ecart_type: float | None
    cv: float | None                  # en %
    ecart_type_ic: tuple[float, float] | None
    cv_ic: tuple[float, float] | None
    minimum: float
    maximum: float


@dataclass
class ResultatComposantes:
    """Composantes de variance d'un plan à plusieurs séries (ANOVA à un facteur)."""
    n_total: int
    n_series: int
    moyenne: float
    s_repetabilite: float             # intra-série
    s_inter_series: float             # entre séries (0 si non mise en évidence)
    s_fidelite_intermediaire: float   # intra-laboratoire = √(s_r² + s_inter²)
    cv_repetabilite: float | None
    cv_inter_series: float | None
    cv_fidelite_intermediaire: float | None
    ddl_repetabilite: int
    moyennes_series: dict[str, float]


@dataclass
class ResultatJustesse:
    cible: float
    moyenne: float
    biais: float                      # moyenne - cible
    biais_pourcent: float | None      # en % de la cible
    p_student: float | None           # test t : la moyenne diffère-t-elle de la cible ?


def _nettoyer(valeurs) -> np.ndarray:
    propres = []
    for v in valeurs:
        if v is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            propres.append(f)
    return np.array(propres, dtype=float)


def statistiques_serie(valeurs, alpha: float = 0.05) -> ResultatSerie:
    """Moyenne, écart-type et CV d'une série ; IC de l'écart-type par la loi du χ²
    (l'IC du CV en est déduit en divisant par la moyenne)."""
    x = _nettoyer(valeurs)
    n = len(x)
    if n == 0:
        raise ValueError("Aucune valeur numérique à analyser.")
    moyenne = float(x.mean())
    if n < 2:
        return ResultatSerie(n, moyenne, None, None, None, None, float(x.min()), float(x.max()))
    s = float(x.std(ddof=1))
    ddl = n - 1
    s_ic = (
        s * math.sqrt(ddl / sps.chi2.ppf(1 - alpha / 2, ddl)),
        s * math.sqrt(ddl / sps.chi2.ppf(alpha / 2, ddl)),
    )
    cv = cv_ic = None
    if moyenne != 0:
        cv = 100 * s / abs(moyenne)
        cv_ic = (100 * s_ic[0] / abs(moyenne), 100 * s_ic[1] / abs(moyenne))
    return ResultatSerie(n, moyenne, s, cv, s_ic, cv_ic, float(x.min()), float(x.max()))


def composantes_variance(series: dict[str, list[float]]) -> ResultatComposantes:
    """
    ANOVA à un facteur aléatoire (la série/le jour). Plans déséquilibrés acceptés
    (effectif moyen corrigé n0). Une composante inter-séries négative est ramenée à 0,
    comme le veut l'usage.
    """
    groupes = {nom: _nettoyer(v) for nom, v in series.items()}
    groupes = {nom: g for nom, g in groupes.items() if len(g) > 0}
    k = len(groupes)
    n_total = sum(len(g) for g in groupes.values())
    if k < 2:
        raise ValueError("Il faut au moins deux séries pour séparer les composantes intra- et inter-séries.")
    if n_total - k < 1:
        raise ValueError("Il faut au moins une série comportant plusieurs répétitions.")

    toutes = np.concatenate(list(groupes.values()))
    moyenne = float(toutes.mean())
    sc_intra = float(sum(np.sum((g - g.mean()) ** 2) for g in groupes.values()))
    sc_inter = float(sum(len(g) * (g.mean() - moyenne) ** 2 for g in groupes.values()))
    cm_intra = sc_intra / (n_total - k)
    cm_inter = sc_inter / (k - 1)
    n0 = (n_total - sum(len(g) ** 2 for g in groupes.values()) / n_total) / (k - 1)

    var_repetabilite = cm_intra
    var_inter = max(0.0, (cm_inter - cm_intra) / n0)
    s_r = math.sqrt(var_repetabilite)
    s_inter = math.sqrt(var_inter)
    s_fi = math.sqrt(var_repetabilite + var_inter)

    def cv(s: float) -> float | None:
        return 100 * s / abs(moyenne) if moyenne != 0 else None

    return ResultatComposantes(
        n_total=n_total, n_series=k, moyenne=moyenne,
        s_repetabilite=s_r, s_inter_series=s_inter, s_fidelite_intermediaire=s_fi,
        cv_repetabilite=cv(s_r), cv_inter_series=cv(s_inter), cv_fidelite_intermediaire=cv(s_fi),
        ddl_repetabilite=n_total - k,
        moyennes_series={nom: float(g.mean()) for nom, g in groupes.items()},
    )


def justesse(valeurs, cible: float) -> ResultatJustesse:
    """Biais de la moyenne des dosages par rapport à une valeur cible (matériau de
    référence, valeur assignée d'un EEQ, cible du fabricant...)."""
    x = _nettoyer(valeurs)
    if len(x) == 0:
        raise ValueError("Aucune valeur numérique à analyser.")
    moyenne = float(x.mean())
    biais = moyenne - cible
    p = None
    if len(x) >= 2 and x.std(ddof=1) > 0:
        p = float(sps.ttest_1samp(x, cible).pvalue)
    return ResultatJustesse(
        cible=cible, moyenne=moyenne, biais=biais,
        biais_pourcent=(100 * biais / cible) if cible else None, p_student=p,
    )


def conforme(cv: float | None, limite: float | None) -> bool | None:
    """True si le CV observé respecte la limite d'acceptation (None si l'un manque)."""
    if cv is None or limite is None or limite <= 0:
        return None
    return cv <= limite
