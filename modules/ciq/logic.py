"""
Logique du module Contrôle interne de qualité (CIQ) : accès à la base (tables
ciq_*) et calculs d'une carte de contrôle de Levey-Jennings.

Ne dépend pas de PySide6 : tout ce qui est ici est testable sans interface.

Principes :
  - un analyte (ex. Glucose sur un automate) possède un ou plusieurs lots de
    contrôle (un par niveau de concentration), chacun avec sa moyenne et son
    écart-type cibles ;
  - si les cibles d'un lot ne sont pas encore renseignées, la carte utilise la
    moyenne et l'écart-type observés (cibles « provisoires », signalées comme
    telles) ;
  - les règles de Westgard sont évaluées sur tout l'historique du lot, dans
    l'ordre chronologique, même si l'écran n'en affiche qu'une période : une
    règle 10x peut ainsi être déclenchée par des points antérieurs à la période ;
  - une mesure exclue (erreur de manipulation documentée...) reste en base pour
    la traçabilité mais ne participe ni aux statistiques ni aux règles.
"""
import math
import random
import sqlite3
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from core import westgard
from core.formatage import parse_date, parse_nombre

FORMAT_DATE = "%Y-%m-%d %H:%M"
MESURES_MIN_CIBLES_PROVISOIRES = 2
MESURES_RECOMMANDEES_CIBLES = 20   # usage : au moins 20 valeurs pour établir moyenne et écart-type


# ------------------------------------------------------------------
# Structures
# ------------------------------------------------------------------
@dataclass
class Analyte:
    id: int
    nom: str
    unite: str
    automate: str
    erreur_totale_admissible: float | None
    regles: tuple[str, ...]
    notes: str

    @property
    def libelle(self) -> str:
        return f"{self.nom} — {self.automate}" if self.automate else self.nom


@dataclass
class Lot:
    id: int
    analyte_id: int
    niveau: str
    numero_lot: str
    cible_moyenne: float | None
    cible_ecart_type: float | None
    origine_cible: str
    date_peremption: str | None
    actif: bool

    @property
    def libelle(self) -> str:
        return f"{self.niveau} (lot {self.numero_lot})" if self.numero_lot else self.niveau

    @property
    def cibles_definies(self) -> bool:
        return self.cible_moyenne is not None and self.cible_ecart_type is not None and self.cible_ecart_type > 0


@dataclass
class Mesure:
    id: int
    lot_id: int
    date: str
    valeur: float
    operateur: str
    commentaire: str
    exclue: bool
    z: float | None = None
    regles: list[str] = field(default_factory=list)

    @property
    def statut(self) -> str:
        if self.exclue:
            return "exclue"
        return westgard.statut(self.regles)


@dataclass
class StatistiquesLot:
    n: int
    moyenne: float | None
    ecart_type: float | None
    cv: float | None
    biais_pourcent: float | None      # moyenne observée vs moyenne cible
    sigma: float | None
    n_alertes: int
    n_rejets: int


@dataclass
class CarteLot:
    """Tout ce qu'il faut pour dessiner la carte de Levey-Jennings d'un lot."""
    lot: Lot
    moyenne: float | None              # moyenne utilisée pour la carte (cible ou observée)
    ecart_type: float | None
    cibles_provisoires: bool
    mesures: list[Mesure]              # toutes les mesures du lot, ordre chronologique
    stats: StatistiquesLot


# ------------------------------------------------------------------
# Analytes
# ------------------------------------------------------------------
def _analyte(row) -> Analyte:
    return Analyte(row[0], row[1], row[2] or "", row[3] or "", row[4],
                   westgard.codes_valides(row[5]), row[6] or "")


_COLONNES_ANALYTE = "id, nom, unite, automate, erreur_totale_admissible, regles, notes"


def lister_analytes(conn: sqlite3.Connection) -> list[Analyte]:
    rows = conn.execute(f"SELECT {_COLONNES_ANALYTE} FROM ciq_analytes ORDER BY nom, automate").fetchall()
    return [_analyte(r) for r in rows]


def get_analyte(conn: sqlite3.Connection, analyte_id: int) -> Analyte | None:
    row = conn.execute(f"SELECT {_COLONNES_ANALYTE} FROM ciq_analytes WHERE id = ?", (analyte_id,)).fetchone()
    return _analyte(row) if row else None


def enregistrer_analyte(conn, nom: str, unite: str = "", automate: str = "",
                        erreur_totale_admissible: float | None = None, regles=None,
                        notes: str = "", analyte_id: int | None = None) -> int:
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("Le nom de l'analyte est obligatoire.")
    texte_regles = ",".join(regles) if regles else None
    try:
        if analyte_id is None:
            cur = conn.execute(
                "INSERT INTO ciq_analytes (nom, unite, automate, erreur_totale_admissible, regles, notes) "
                "VALUES (?,?,?,?,?,?)",
                (nom, unite.strip(), automate.strip(), erreur_totale_admissible, texte_regles, notes),
            )
            analyte_id = cur.lastrowid
        else:
            conn.execute(
                "UPDATE ciq_analytes SET nom=?, unite=?, automate=?, erreur_totale_admissible=?, regles=?, notes=? "
                "WHERE id=?",
                (nom, unite.strip(), automate.strip(), erreur_totale_admissible, texte_regles, notes, analyte_id),
            )
    except sqlite3.IntegrityError:
        conn.rollback()
        raise ValueError(f"Un analyte « {nom} » existe déjà sur l'automate « {automate.strip() or '(aucun)'} ».") from None
    conn.commit()
    return analyte_id


def supprimer_analyte(conn, analyte_id: int) -> None:
    conn.execute("DELETE FROM ciq_analytes WHERE id = ?", (analyte_id,))
    conn.commit()


def enregistrer_notes(conn, analyte_id: int, notes: str) -> None:
    conn.execute("UPDATE ciq_analytes SET notes = ? WHERE id = ?", (notes, analyte_id))
    conn.commit()


# ------------------------------------------------------------------
# Lots
# ------------------------------------------------------------------
_COLONNES_LOT = ("id, analyte_id, niveau, numero_lot, cible_moyenne, cible_ecart_type, origine_cible, "
                 "date_peremption, actif")


def _lot(row) -> Lot:
    return Lot(row[0], row[1], row[2], row[3] or "", row[4], row[5], row[6] or "", row[7], bool(row[8]))


def lister_lots(conn, analyte_id: int, actifs_seulement: bool = False) -> list[Lot]:
    condition = " AND actif = 1" if actifs_seulement else ""
    rows = conn.execute(
        f"SELECT {_COLONNES_LOT} FROM ciq_lots WHERE analyte_id = ?{condition} ORDER BY actif DESC, niveau, id",
        (analyte_id,),
    ).fetchall()
    return [_lot(r) for r in rows]


def get_lot(conn, lot_id: int) -> Lot | None:
    row = conn.execute(f"SELECT {_COLONNES_LOT} FROM ciq_lots WHERE id = ?", (lot_id,)).fetchone()
    return _lot(row) if row else None


def enregistrer_lot(conn, analyte_id: int, niveau: str, numero_lot: str = "",
                    cible_moyenne: float | None = None, cible_ecart_type: float | None = None,
                    origine_cible: str = "", date_peremption: str | None = None, actif: bool = True,
                    lot_id: int | None = None) -> int:
    niveau = (niveau or "").strip()
    if not niveau:
        raise ValueError("Le niveau du contrôle est obligatoire (ex. « Niveau 1 », « Normal »).")
    if cible_ecart_type is not None and cible_ecart_type <= 0:
        raise ValueError("L'écart-type cible doit être strictement positif.")
    if (cible_moyenne is None) != (cible_ecart_type is None):
        raise ValueError("Renseignez la moyenne ET l'écart-type cibles, ou aucun des deux "
                         "(cibles provisoires calculées sur les données).")
    valeurs = (niveau, (numero_lot or "").strip(), cible_moyenne, cible_ecart_type, origine_cible,
               date_peremption, int(actif))
    if lot_id is None:
        cur = conn.execute(
            "INSERT INTO ciq_lots (niveau, numero_lot, cible_moyenne, cible_ecart_type, origine_cible, "
            "date_peremption, actif, analyte_id) VALUES (?,?,?,?,?,?,?,?)", valeurs + (analyte_id,))
        lot_id = cur.lastrowid
    else:
        conn.execute(
            "UPDATE ciq_lots SET niveau=?, numero_lot=?, cible_moyenne=?, cible_ecart_type=?, origine_cible=?, "
            "date_peremption=?, actif=? WHERE id=?", valeurs + (lot_id,))
    conn.commit()
    return lot_id


def supprimer_lot(conn, lot_id: int) -> None:
    conn.execute("DELETE FROM ciq_lots WHERE id = ?", (lot_id,))
    conn.commit()


def definir_cibles(conn, lot_id: int, moyenne: float, ecart_type: float, origine: str = "Laboratoire") -> None:
    if ecart_type is None or ecart_type <= 0:
        raise ValueError("L'écart-type cible doit être strictement positif.")
    conn.execute("UPDATE ciq_lots SET cible_moyenne=?, cible_ecart_type=?, origine_cible=? WHERE id=?",
                 (moyenne, ecart_type, origine, lot_id))
    conn.commit()


def cibles_depuis_donnees(conn, lot_id: int, nombre: int | None = None) -> tuple[float, float, int]:
    """Moyenne et écart-type des `nombre` premières mesures non exclues du lot
    (toutes si None). Sert à établir les cibles du laboratoire à partir d'une
    période probatoire. Retourne (moyenne, écart-type, effectif utilisé)."""
    valeurs = [m.valeur for m in lister_mesures(conn, lot_id) if not m.exclue]
    if nombre is not None:
        valeurs = valeurs[:nombre]
    if len(valeurs) < MESURES_MIN_CIBLES_PROVISOIRES:
        raise ValueError("Il faut au moins deux mesures non exclues pour calculer des cibles.")
    ecart_type = statistics.stdev(valeurs)
    if ecart_type <= 0:
        raise ValueError("Toutes les mesures sont identiques : l'écart-type est nul.")
    return statistics.mean(valeurs), ecart_type, len(valeurs)


# ------------------------------------------------------------------
# Mesures
# ------------------------------------------------------------------
def normaliser_date(valeur) -> str:
    """Date saisie ou importée -> « AAAA-MM-JJ HH:MM ». Lève ValueError si illisible."""
    d = parse_date(valeur)
    if d is None:
        raise ValueError(f"Date illisible : « {valeur} » (formats acceptés : JJ/MM/AAAA [HH:MM], AAAA-MM-JJ).")
    return d.strftime(FORMAT_DATE)


def lister_mesures(conn, lot_id: int) -> list[Mesure]:
    rows = conn.execute(
        "SELECT id, lot_id, date_mesure, valeur, operateur, commentaire, exclue FROM ciq_mesures "
        "WHERE lot_id = ? ORDER BY date_mesure, id", (lot_id,),
    ).fetchall()
    return [Mesure(r[0], r[1], r[2], r[3], r[4] or "", r[5] or "", bool(r[6])) for r in rows]


def ajouter_mesure(conn, lot_id: int, date, valeur: float, operateur: str = "", commentaire: str = "",
                   valider: bool = True) -> int:
    if valeur is None or not math.isfinite(float(valeur)):
        raise ValueError("La valeur du contrôle doit être un nombre.")
    cur = conn.execute(
        "INSERT INTO ciq_mesures (lot_id, date_mesure, valeur, operateur, commentaire) VALUES (?,?,?,?,?)",
        (lot_id, normaliser_date(date), float(valeur), (operateur or "").strip(), (commentaire or "").strip()),
    )
    if valider:
        conn.commit()
    return cur.lastrowid


def modifier_mesure(conn, mesure_id: int, date, valeur: float, operateur: str, commentaire: str) -> None:
    conn.execute(
        "UPDATE ciq_mesures SET date_mesure=?, valeur=?, operateur=?, commentaire=? WHERE id=?",
        (normaliser_date(date), float(valeur), (operateur or "").strip(), (commentaire or "").strip(), mesure_id),
    )
    conn.commit()


def definir_exclusion(conn, mesure_id: int, exclue: bool, motif: str | None = None) -> None:
    if motif is not None:
        conn.execute("UPDATE ciq_mesures SET exclue=?, commentaire=? WHERE id=?", (int(exclue), motif, mesure_id))
    else:
        conn.execute("UPDATE ciq_mesures SET exclue=? WHERE id=?", (int(exclue), mesure_id))
    conn.commit()


def supprimer_mesure(conn, mesure_id: int) -> None:
    conn.execute("DELETE FROM ciq_mesures WHERE id = ?", (mesure_id,))
    conn.commit()


@dataclass
class BilanImport:
    n_importees: int
    erreurs: list[str]


def importer_lignes(conn, lot_id: int, lignes: list[list]) -> BilanImport:
    """
    Importe des lignes [date, valeur, (opérateur), (commentaire)] dans un lot.
    Une ligne illisible est signalée et ignorée, les autres sont importées ; une
    ligne d'en-tête éventuelle (valeur non numérique en 1re ligne) est sautée.
    Tout est enregistré en une seule transaction.
    """
    erreurs: list[str] = []
    n = 0
    try:
        for numero, ligne in enumerate(lignes, start=1):
            cellules = list(ligne) + [None] * 4
            date_brute, valeur_brute = cellules[0], cellules[1]
            valeur = parse_nombre(valeur_brute)
            if numero == 1 and valeur is None and parse_date(date_brute) is None:
                continue  # en-tête
            if valeur is None:
                erreurs.append(f"Ligne {numero} : valeur « {valeur_brute} » non numérique.")
                continue
            try:
                ajouter_mesure(conn, lot_id, date_brute, valeur,
                               str(cellules[2] or ""), str(cellules[3] or ""), valider=False)
            except ValueError as e:
                erreurs.append(f"Ligne {numero} : {e}")
                continue
            n += 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return BilanImport(n, erreurs)


# ------------------------------------------------------------------
# Calculs de la carte
# ------------------------------------------------------------------
def _stats(valeurs: list[float], moyenne_cible: float | None, eta: float | None) -> tuple:
    n = len(valeurs)
    if n == 0:
        return 0, None, None, None, None, None
    moyenne = statistics.mean(valeurs)
    ecart_type = statistics.stdev(valeurs) if n > 1 else None
    cv = 100 * ecart_type / abs(moyenne) if (ecart_type is not None and moyenne) else None
    biais = 100 * (moyenne - moyenne_cible) / moyenne_cible if moyenne_cible else None
    sig = None
    if eta is not None and cv:
        sig = (eta - abs(biais or 0.0)) / cv
    return n, moyenne, ecart_type, cv, biais, sig


def calculer_cartes(conn, analyte: Analyte, lots: list[Lot] | None = None,
                    debut: str | None = None, fin: str | None = None) -> list[CarteLot]:
    """
    Construit une carte par lot : scores z, règles de Westgard (intra- et
    inter-niveaux, sur tout l'historique) puis statistiques sur la période
    [debut ; fin] (dates ISO, bornes incluses, None = pas de borne).
    """
    if lots is None:
        lots = lister_lots(conn, analyte.id)
    cartes: list[CarteLot] = []
    serie_par_mesure: dict[int, tuple] = {}
    z_par_serie: dict[tuple, dict[int, float]] = {}

    for lot in lots:
        mesures = lister_mesures(conn, lot.id)
        retenues = [m for m in mesures if not m.exclue]
        if lot.cibles_definies:
            moyenne, ecart_type, provisoire = lot.cible_moyenne, lot.cible_ecart_type, False
        elif len(retenues) >= MESURES_MIN_CIBLES_PROVISOIRES and statistics.stdev([m.valeur for m in retenues]) > 0:
            moyenne = statistics.mean(m.valeur for m in retenues)
            ecart_type = statistics.stdev(m.valeur for m in retenues)
            provisoire = True
        else:
            moyenne, ecart_type, provisoire = None, None, True

        if ecart_type:
            z = westgard.scores_z([m.valeur for m in retenues], moyenne, ecart_type)
            for m, zi, regles in zip(retenues, z, westgard.evaluer(z, analyte.regles)):
                m.z, m.regles = zi, list(regles)
            for m, cle in zip(retenues, westgard.cles_de_serie([m.date for m in retenues])):
                serie_par_mesure[m.id] = cle
                z_par_serie.setdefault(cle, {})[lot.id] = m.z
        cartes.append(CarteLot(lot, moyenne, ecart_type, provisoire, mesures, None))

    # Règles inter-niveaux : attribuées à chaque mesure de la série concernée.
    violations_inter = westgard.evaluer_inter_niveaux(z_par_serie, analyte.regles)
    if violations_inter:
        for carte in cartes:
            for m in carte.mesures:
                cle = serie_par_mesure.get(m.id)
                if cle in violations_inter:
                    m.regles += [c for c in violations_inter[cle] if c not in m.regles]

    for carte in cartes:
        periode = [m for m in carte.mesures if dans_periode(m.date, debut, fin)]
        valeurs = [m.valeur for m in periode if not m.exclue]
        n, moyenne, ecart_type, cv, biais, sig = _stats(
            valeurs, carte.lot.cible_moyenne if carte.lot.cibles_definies else None,
            analyte.erreur_totale_admissible)
        carte.stats = StatistiquesLot(
            n=n, moyenne=moyenne, ecart_type=ecart_type, cv=cv, biais_pourcent=biais, sigma=sig,
            n_alertes=sum(1 for m in periode if m.statut == westgard.ALERTE),
            n_rejets=sum(1 for m in periode if m.statut == westgard.REJET),
        )
    return cartes


def dans_periode(date_iso: str, debut: str | None, fin: str | None) -> bool:
    jour = date_iso[:10]
    return (debut is None or jour >= debut[:10]) and (fin is None or jour <= fin[:10])


def debut_periode(jours: int | None) -> str | None:
    """Date ISO de début d'une période glissante de `jours` jours (None = tout l'historique)."""
    if jours is None:
        return None
    return (datetime.now() - timedelta(days=jours)).strftime("%Y-%m-%d")


@dataclass
class LigneSynthese:
    analyte: Analyte
    lot: Lot
    derniere_date: str | None
    dernier_statut: str           # "ok", "alerte", "rejet", "exclue", "aucune"
    dernieres_regles: list[str]
    n_periode: int
    cv: float | None
    sigma: float | None
    n_rejets_periode: int
    cibles_provisoires: bool


def synthese(conn, jours: int | None = 30) -> list[LigneSynthese]:
    """Une ligne par lot actif de chaque analyte : dernier passage, statut, CV et
    nombre de rejets sur la période — pour la vue d'ensemble du module."""
    debut = debut_periode(jours)
    lignes = []
    for analyte in lister_analytes(conn):
        lots = lister_lots(conn, analyte.id, actifs_seulement=True)
        for carte in calculer_cartes(conn, analyte, lots, debut=debut):
            derniere = carte.mesures[-1] if carte.mesures else None
            lignes.append(LigneSynthese(
                analyte=analyte, lot=carte.lot,
                derniere_date=derniere.date if derniere else None,
                dernier_statut=derniere.statut if derniere else "aucune",
                dernieres_regles=derniere.regles if derniere else [],
                n_periode=carte.stats.n, cv=carte.stats.cv, sigma=carte.stats.sigma,
                n_rejets_periode=carte.stats.n_rejets, cibles_provisoires=carte.cibles_provisoires,
            ))
    return lignes


# ------------------------------------------------------------------
# Données de démonstration
# ------------------------------------------------------------------
def creer_donnees_demo(conn, graine: int = 2026) -> int:
    """Crée deux analytes fictifs avec deux niveaux chacun et ~3 mois de passages,
    dont quelques anomalies volontaires (dérive, valeur aberrante) pour montrer
    le déclenchement des règles. Retourne l'id du premier analyte créé."""
    rng = random.Random(graine)
    debut = datetime.now().replace(hour=8, minute=0, second=0, microsecond=0) - timedelta(days=89)
    definitions = [
        ("Glucose (démo)", "mmol/L", "Automate A", 6.9,
         [("Niveau 1", "GLU-2401", 5.50, 0.12), ("Niveau 2", "GLU-2402", 16.20, 0.32)]),
        ("TSH (démo)", "mUI/L", "Automate B", 23.7,
         [("Niveau 1", "TSH-118", 0.95, 0.045), ("Niveau 2", "TSH-119", 9.80, 0.42)]),
    ]
    premier = None
    try:
        for nom, unite, automate, eta, niveaux in definitions:
            existant = conn.execute("SELECT id FROM ciq_analytes WHERE nom = ? AND automate = ?",
                                    (nom, automate)).fetchone()
            if existant:
                premier = premier or existant[0]
                continue
            cur = conn.execute(
                "INSERT INTO ciq_analytes (nom, unite, automate, erreur_totale_admissible, notes) VALUES (?,?,?,?,?)",
                (nom, unite, automate, eta, "Données fictives générées pour la démonstration."))
            analyte_id = cur.lastrowid
            premier = premier or analyte_id
            for index, (niveau, numero, moyenne, ecart_type) in enumerate(niveaux):
                lot_id = conn.execute(
                    "INSERT INTO ciq_lots (analyte_id, niveau, numero_lot, cible_moyenne, cible_ecart_type, "
                    "origine_cible) VALUES (?,?,?,?,?,?)",
                    (analyte_id, niveau, numero, moyenne, ecart_type, "Fabricant")).lastrowid
                for jour in range(90):
                    if rng.random() < 0.12:
                        continue  # jours sans passage (week-ends...)
                    instant = debut + timedelta(days=jour, minutes=rng.randint(0, 50) + 10 * index)
                    z = rng.gauss(0, 1)
                    if 55 <= jour <= 62:
                        z = 1.3 + abs(rng.gauss(0, 0.4))      # dérive : déclenche 4-1s
                    if jour == 30 and index == 0:
                        z = 3.4                                # valeur aberrante : déclenche 1-3s
                    conn.execute(
                        "INSERT INTO ciq_mesures (lot_id, date_mesure, valeur, operateur) VALUES (?,?,?,?)",
                        (lot_id, instant.strftime(FORMAT_DATE), round(moyenne + z * ecart_type, 3),
                         rng.choice(["AB", "CD", "EF"])))
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return premier
