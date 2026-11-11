"""
Dessin des cartes de contrôle sur un PlotWidget :
  - carte de Levey-Jennings d'un lot (valeurs brutes, passages équidistants) ;
  - carte normalisée multi-niveaux (scores z en fonction du temps), qui permet
    de voir d'un coup d'œil si les niveaux dérivent ensemble (erreur
    systématique) ou séparément.
"""
from datetime import datetime, timedelta

from core import westgard
from core.formatage import datetime_fr, fmt
from core.plot import PlotWidget

from .logic import CarteLot, Mesure, dans_periode

COULEUR_STATUT = {
    westgard.OK: "accent_graph",
    westgard.ALERTE: "statut_alerte",
    westgard.REJET: "statut_rejet",
    "exclue": "statut_neutre",
}
COULEURS_NIVEAUX = ["accent_graph", "graph_secondaire", "graph_tertiaire", "statut_ok", "statut_alerte"]
FORMES_NIVEAUX = ["o", "s", "^", "o", "s"]


def infobulle_mesure(m: Mesure, unite: str = "", niveau: str = "") -> str:
    lignes = []
    if niveau:
        lignes.append(niveau)
    lignes.append(f"{datetime_fr(m.date)} — {fmt(m.valeur)} {unite}".strip())
    if m.z is not None:
        lignes.append(f"z = {m.z:+.2f}")
    if m.exclue:
        lignes.append("Mesure exclue des calculs")
    elif m.regles:
        lignes.append("Règles : " + westgard.libelles(m.regles))
    if m.operateur:
        lignes.append(f"Opérateur : {m.operateur}")
    if m.commentaire:
        lignes.append(f"« {m.commentaire} »")
    return "\n".join(lignes)


def _graduations_dates(mesures: list[Mesure], maximum: int = 8) -> tuple[list[int], list[str]]:
    """Quelques graduations réparties sur l'axe des passages, étiquetées par leur date."""
    n = len(mesures)
    if n == 0:
        return [], []
    pas = max(1, round(n / maximum))
    positions = list(range(0, n, pas))
    # « JJ/MM/AA » : assez court pour ne pas se chevaucher sur une carte étroite
    return [p + 1 for p in positions], [datetime_fr(mesures[p].date)[:6] + mesures[p].date[2:4] for p in positions]


def dessiner_levey_jennings(plot: PlotWidget, carte: CarteLot, unite: str = "",
                            debut: str | None = None, fin: str | None = None) -> None:
    plot.effacer()
    plot.titre_y = unite
    plot.titre_x = ""
    mesures = [m for m in carte.mesures if dans_periode(m.date, debut, fin)]
    if not mesures:
        plot.message_vide = "Aucun passage sur la période sélectionnée"
        return
    moyenne, s = carte.moyenne, carte.ecart_type
    xs = list(range(1, len(mesures) + 1))

    if moyenne is not None and s:
        plot.ajouter_bande_h(moyenne - 2 * s, moyenne + 2 * s, "statut_ok", 16)
        plot.ajouter_bande_h(moyenne + 2 * s, moyenne + 3 * s, "statut_alerte", 22)
        plot.ajouter_bande_h(moyenne - 3 * s, moyenne - 2 * s, "statut_alerte", 22)
        for k, couleur, epaisseur in ((3, "statut_rejet", 1.2), (2, "statut_alerte", 1.2), (1, "muted", 0.8)):
            for signe in (1, -1):
                plot.ajouter_repere_h(moyenne + signe * k * s, couleur, epaisseur, tirets=True,
                                      etiquette=f"{'+' if signe > 0 else '−'}{k}s  {fmt(moyenne + signe * k * s)}")
        plot.ajouter_repere_h(moyenne, "text", 1.2, tirets=False, etiquette=f"Moy.  {fmt(moyenne)}")
        # marge visuelle au-delà de ±3 s, sans écraser une valeur très éloignée
        valeurs = [m.valeur for m in mesures]
        plot.definir_limites(ymin=min(min(valeurs), moyenne - 3.6 * s) - 0.02 * s,
                             ymax=max(max(valeurs), moyenne + 3.6 * s) + 0.02 * s)

    retenues = [(x, m) for x, m in zip(xs, mesures) if not m.exclue]
    plot.ajouter_ligne([x for x, _ in retenues], [m.valeur for _, m in retenues], "accent_graph", 1.1)
    plot.ajouter_points(
        xs, [m.valeur for m in mesures],
        couleurs=[COULEUR_STATUT.get(m.statut, "accent_graph") for m in mesures],
        creux=[m.exclue for m in mesures],
        taille=7.5,
        infobulles=[infobulle_mesure(m, unite) for m in mesures],
        ids=[m.id for m in mesures],
    )
    positions, etiquettes = _graduations_dates(mesures)
    plot.definir_graduations_x(positions, etiquettes)
    plot.definir_limites(xmin=0.3, xmax=len(mesures) + 0.7)


def dessiner_z_multiniveaux(plot: PlotWidget, cartes: list[CarteLot],
                            debut: str | None = None, fin: str | None = None) -> None:
    """Tous les niveaux sur une même carte, en scores z, en fonction du temps."""
    plot.effacer()
    plot.titre_y = "Score z (écarts-types)"
    plot.titre_x = ""
    origine = None
    toutes: list[tuple[float, Mesure, CarteLot]] = []
    for carte in cartes:
        for m in carte.mesures:
            if m.z is None or not dans_periode(m.date, debut, fin):
                continue
            instant = datetime.strptime(m.date, "%Y-%m-%d %H:%M")
            origine = instant if origine is None or instant < origine else origine
            toutes.append((0.0, m, carte))
    if not toutes:
        plot.message_vide = "Aucun passage évaluable sur la période (cibles manquantes ?)"
        return

    def jours(m: Mesure) -> float:
        return (datetime.strptime(m.date, "%Y-%m-%d %H:%M") - origine).total_seconds() / 86400

    plot.ajouter_bande_h(-2, 2, "statut_ok", 16)
    plot.ajouter_bande_h(2, 3, "statut_alerte", 22)
    plot.ajouter_bande_h(-3, -2, "statut_alerte", 22)
    for k, couleur in ((3, "statut_rejet"), (2, "statut_alerte"), (1, "muted")):
        plot.ajouter_repere_h(k, couleur, 1.0, etiquette=f"+{k}s")
        plot.ajouter_repere_h(-k, couleur, 1.0, etiquette=f"−{k}s")
    plot.ajouter_repere_h(0, "text", 1.2, tirets=False, etiquette="cible")

    for i, carte in enumerate(cartes):
        points = [m for m in carte.mesures if m.z is not None and dans_periode(m.date, debut, fin)]
        if not points:
            continue
        couleur = COULEURS_NIVEAUX[i % len(COULEURS_NIVEAUX)]
        xs = [jours(m) for m in points]
        plot.ajouter_ligne(xs, [m.z for m in points], couleur, 1.0)
        plot.ajouter_points(
            xs, [m.z for m in points], couleur=couleur, forme=FORMES_NIVEAUX[i % len(FORMES_NIVEAUX)],
            contour=None, taille=7,
            couleurs=[couleur if m.statut == westgard.OK else COULEUR_STATUT[m.statut] for m in points],
            infobulles=[infobulle_mesure(m, niveau=carte.lot.libelle) for m in points],
            ids=[m.id for m in points], nom=carte.lot.libelle,
        )
    etendue = max(jours(m) for _, m, _ in toutes)
    pas = next((p for p in (1, 2, 7, 14, 30, 61, 91, 182, 365, 730) if etendue / p <= 7), 730)
    positions = [k * pas for k in range(int(etendue // pas) + 1)]
    plot.definir_graduations_x(positions, [(origine + timedelta(days=p)).strftime("%d/%m/%y") for p in positions])
    zs = [m.z for _, m, _ in toutes]
    plot.definir_limites(xmin=-0.02 * max(etendue, 1), xmax=etendue + 0.02 * max(etendue, 1),
                         ymin=min(-3.6, min(zs) - 0.2), ymax=max(3.6, max(zs) + 0.2))
