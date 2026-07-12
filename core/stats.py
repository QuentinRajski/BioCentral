"""
Calculs statistiques partagés. Respecte les règles validées avec l'utilisateur :

  - statut 'exclu' (Res annulé, VCOM...)      -> absent de tout calcul, y compris n
  - statut 'sous_seuil' / 'sur_seuil' (<0.3)  -> inclus dans n, médiane, percentiles
                                                  (rang = valeur_numerique = seuil) ;
                                                  exclu de la moyenne et de l'écart-type
  - statut 'valide'                           -> inclus partout

Ce module ne dépend ni de PySide6 ni de la base : il prend des lignes déjà
récupérées (parametre_id, tranche_age_id, sexe filtrés en amont par la requête SQL)
et rend un dict de résultats, réutilisable telle quelle par n'importe quel écran.
"""
import statistics
from dataclasses import dataclass, field

PERCENTILES = [2.5, 5, 10, 20, 25, 50, 75, 80, 90, 95, 97.5]


@dataclass
class StatResult:
    n: int
    moyenne: float | None
    ecart_type: float | None
    mediane: float | None
    minimum: float | None
    maximum: float | None
    cv: float | None = None
    percentiles: dict = field(default_factory=dict)


def _percentile(sorted_values: list[float], p: float) -> float:
    """Percentile par interpolation linéaire (méthode standard, équivalente à numpy.percentile)."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    k = (p / 100) * (len(sorted_values) - 1)
    f, c = int(k), min(int(k) + 1, len(sorted_values) - 1)
    if f == c:
        return sorted_values[f]
    return sorted_values[f] + (sorted_values[c] - sorted_values[f]) * (k - f)


def compute_stats(rows: list[tuple[float, str]]) -> StatResult | None:
    """rows : liste de (valeur_numerique, statut), déjà filtrée hors statut='exclu'."""
    if not rows:
        return None
    ranked = sorted(v for v, _ in rows)                     # médiane / percentiles
    calc = [v for v, s in rows if s == "valide"]             # moyenne / écart-type

    moyenne = round(statistics.mean(calc), 3) if calc else None
    ecart_type = round(statistics.stdev(calc), 3) if len(calc) > 1 else None
    cv = round(ecart_type / moyenne * 100, 2) if (ecart_type is not None and moyenne) else None

    return StatResult(
        n=len(rows),
        moyenne=moyenne,
        ecart_type=ecart_type,
        mediane=round(_percentile(ranked, 50), 3),
        minimum=round(min(ranked), 3),
        maximum=round(max(ranked), 3),
        cv=cv,
        percentiles={p: round(_percentile(ranked, p), 3) for p in PERCENTILES},
    )
