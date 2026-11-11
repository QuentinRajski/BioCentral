"""
Règles de Westgard pour l'interprétation des cartes de contrôle (Levey-Jennings).

Ce module ne dépend ni de PySide6 ni de la base : il prend des scores z
(écart à la cible exprimé en écarts-types) dans l'ordre chronologique et rend,
pour chaque point, la liste des règles qu'il déclenche.

Règles « intra-niveau » (sur les passages successifs d'un même lot) :
    1_2s   1 valeur au-delà de ±2 s                           -> alerte
    1_3s   1 valeur au-delà de ±3 s                           -> rejet (erreur aléatoire)
    2_2s   2 valeurs consécutives au-delà de 2 s, même côté   -> rejet (erreur systématique)
    R_4s   2 valeurs consécutives de part et d'autre de ±2 s  -> rejet (erreur aléatoire)
    4_1s   4 valeurs consécutives au-delà de 1 s, même côté   -> rejet (erreur systématique)
    10_x   10 valeurs consécutives du même côté de la cible   -> rejet (erreur systématique)
    7_T    7 valeurs consécutives strictement croissantes
           ou décroissantes (tendance)                        -> alerte (facultative)

Règles « inter-niveaux » (plusieurs niveaux passés dans la même série) :
    2_2s_inter  2 niveaux de la série au-delà de 2 s, même côté -> rejet (systématique)
    R_4s_inter  un niveau > +2 s et un autre < -2 s             -> rejet (aléatoire)

Une règle est attribuée au point qui la DÉCLENCHE, c'est-à-dire le dernier de
la séquence : c'est à ce passage que la série doit être rejetée.
"""
from dataclasses import dataclass
from typing import Hashable, Sequence

ALERTE = "alerte"
REJET = "rejet"
OK = "ok"


@dataclass(frozen=True)
class Regle:
    code: str
    libelle: str       # notation usuelle, affichée à l'utilisateur
    gravite: str       # ALERTE ou REJET
    nature: str        # type d'erreur évoqué
    description: str


REGLES: dict[str, Regle] = {
    r.code: r for r in (
        Regle("1_2s", "1-2s", ALERTE, "avertissement",
              "Une valeur au-delà de ±2 écarts-types. Simple alerte : vérifier les autres règles."),
        Regle("1_3s", "1-3s", REJET, "erreur aléatoire",
              "Une valeur au-delà de ±3 écarts-types."),
        Regle("2_2s", "2-2s", REJET, "erreur systématique",
              "Deux valeurs consécutives au-delà de 2 écarts-types, du même côté de la cible."),
        Regle("R_4s", "R-4s", REJET, "erreur aléatoire",
              "Deux valeurs consécutives de part et d'autre de ±2 écarts-types (étendue > 4 s)."),
        Regle("4_1s", "4-1s", REJET, "erreur systématique",
              "Quatre valeurs consécutives au-delà de 1 écart-type, du même côté de la cible."),
        Regle("10_x", "10x", REJET, "erreur systématique",
              "Dix valeurs consécutives du même côté de la cible."),
        Regle("7_T", "7T", ALERTE, "tendance",
              "Sept valeurs consécutives strictement croissantes ou décroissantes (dérive)."),
        Regle("2_2s_inter", "2-2s (inter-niveaux)", REJET, "erreur systématique",
              "Dans la même série, deux niveaux de contrôle au-delà de 2 écarts-types du même côté."),
        Regle("R_4s_inter", "R-4s (inter-niveaux)", REJET, "erreur aléatoire",
              "Dans la même série, un niveau au-delà de +2 s et un autre au-delà de -2 s."),
    )
}

# Jeu de règles « multi-règles de Westgard » classique, appliqué par défaut.
REGLES_PAR_DEFAUT: tuple[str, ...] = ("1_2s", "1_3s", "2_2s", "R_4s", "4_1s", "10_x")
REGLES_INTRA: tuple[str, ...] = ("1_2s", "1_3s", "2_2s", "R_4s", "4_1s", "10_x", "7_T")
REGLES_INTER: tuple[str, ...] = ("2_2s_inter", "R_4s_inter")
# Une règle inter-niveaux est active si sa version intra-niveau l'est.
_INTRA_DE_INTER = {"2_2s_inter": "2_2s", "R_4s_inter": "R_4s"}


def scores_z(valeurs: Sequence[float], moyenne: float, ecart_type: float) -> list[float]:
    """Écart de chaque valeur à la cible, en nombre d'écarts-types."""
    if ecart_type is None or ecart_type <= 0:
        raise ValueError("L'écart-type cible doit être strictement positif.")
    return [(v - moyenne) / ecart_type for v in valeurs]


def evaluer(z: Sequence[float], regles: Sequence[str] = REGLES_PAR_DEFAUT) -> list[list[str]]:
    """Pour chaque point (ordre chronologique), codes des règles qu'il déclenche."""
    actives = set(regles)
    resultat: list[list[str]] = []
    for i, zi in enumerate(z):
        violations: list[str] = []
        if "1_3s" in actives and abs(zi) > 3:
            violations.append("1_3s")
        elif "1_2s" in actives and abs(zi) > 2:
            violations.append("1_2s")
        if i >= 1:
            precedent = z[i - 1]
            if "2_2s" in actives and ((zi > 2 and precedent > 2) or (zi < -2 and precedent < -2)):
                violations.append("2_2s")
            if "R_4s" in actives and ((zi > 2 and precedent < -2) or (zi < -2 and precedent > 2)):
                violations.append("R_4s")
        if "4_1s" in actives and i >= 3:
            fenetre = z[i - 3:i + 1]
            if all(v > 1 for v in fenetre) or all(v < -1 for v in fenetre):
                violations.append("4_1s")
        if "10_x" in actives and i >= 9:
            fenetre = z[i - 9:i + 1]
            if all(v > 0 for v in fenetre) or all(v < 0 for v in fenetre):
                violations.append("10_x")
        if "7_T" in actives and i >= 6:
            fenetre = z[i - 6:i + 1]
            pas = [b - a for a, b in zip(fenetre, fenetre[1:])]
            if all(p > 0 for p in pas) or all(p < 0 for p in pas):
                violations.append("7_T")
        resultat.append(violations)
    return resultat


def evaluer_inter_niveaux(
    series: dict[Hashable, dict[Hashable, float]], regles: Sequence[str] = REGLES_PAR_DEFAUT,
) -> dict[Hashable, list[str]]:
    """
    Règles inter-niveaux. `series` associe à chaque clé de série (un passage
    où plusieurs niveaux ont été mesurés ensemble) un dict {niveau: score z}.
    Retourne, pour chaque série en infraction, les codes des règles déclenchées.
    Une série ne comptant qu'un seul niveau n'est jamais concernée.
    """
    actives = {code for code, intra in _INTRA_DE_INTER.items() if intra in set(regles)}
    resultat: dict[Hashable, list[str]] = {}
    for cle, z_par_niveau in series.items():
        valeurs = list(z_par_niveau.values())
        if len(valeurs) < 2:
            continue
        violations = []
        if "2_2s_inter" in actives and (
            sum(1 for v in valeurs if v > 2) >= 2 or sum(1 for v in valeurs if v < -2) >= 2
        ):
            violations.append("2_2s_inter")
        if "R_4s_inter" in actives and max(valeurs) > 2 and min(valeurs) < -2:
            violations.append("R_4s_inter")
        if violations:
            resultat[cle] = violations
    return resultat


def statut(violations: Sequence[str]) -> str:
    """OK, ALERTE (uniquement des règles d'avertissement) ou REJET."""
    if any(REGLES[c].gravite == REJET for c in violations if c in REGLES):
        return REJET
    return ALERTE if violations else OK


def libelles(violations: Sequence[str]) -> str:
    """« 1-3s, 2-2s » — texte court pour un tableau ou une info-bulle."""
    return ", ".join(REGLES[c].libelle if c in REGLES else c for c in violations)


def cles_de_serie(dates_iso: Sequence[str]) -> list[tuple[str, int]]:
    """
    Associe à chaque mesure d'un lot (dates ISO « AAAA-MM-JJ HH:MM », ordre
    chronologique) la clé de la série à laquelle elle appartient : (jour, rang
    du passage dans la journée). Deux niveaux mesurés le même jour au même rang
    sont considérés comme passés dans la même série.
    """
    cles = []
    compte: dict[str, int] = {}
    for d in dates_iso:
        jour = str(d)[:10]
        rang = compte.get(jour, 0)
        compte[jour] = rang + 1
        cles.append((jour, rang))
    return cles


def codes_valides(texte: str | None) -> tuple[str, ...]:
    """Lit la liste de règles enregistrée pour un analyte (« 1_2s,1_3s,... »).
    None, vide ou illisible -> règles par défaut."""
    if not texte:
        return REGLES_PAR_DEFAUT
    codes = tuple(c.strip() for c in texte.split(",") if c.strip() in REGLES_INTRA)
    return codes or REGLES_PAR_DEFAUT
