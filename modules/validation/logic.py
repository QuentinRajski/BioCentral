"""
Enregistrement des études du module Validation de méthodes (tables vm_*), et
jeux de données d'exemple. Ne dépend pas de PySide6.
"""
import json
import random
from dataclasses import dataclass, field

TYPE_COMPARAISON = "comparaison"
TYPE_FIDELITE = "precision"
LIBELLES_TYPE = {TYPE_COMPARAISON: "Comparaison", TYPE_FIDELITE: "Fidélité"}


@dataclass
class Etude:
    id: int | None
    type: str
    titre: str
    analyte: str = ""
    unite: str = ""
    methode_x: str = ""
    methode_y: str = ""
    parametres: dict = field(default_factory=dict)
    notes: str = ""
    date_creation: str = ""
    # (identifiant, x, y) — pour une étude de fidélité : (série, valeur, None)
    donnees: list[tuple[str, float | None, float | None]] = field(default_factory=list)


def lister_etudes(conn) -> list[Etude]:
    rows = conn.execute(
        "SELECT id, type, titre, analyte, unite, methode_x, methode_y, parametres, notes, date_creation "
        "FROM vm_etudes ORDER BY date_creation DESC, id DESC").fetchall()
    return [_etude(r) for r in rows]


def _etude(r) -> Etude:
    try:
        parametres = json.loads(r[7]) if r[7] else {}
    except (TypeError, ValueError):
        parametres = {}
    return Etude(r[0], r[1], r[2], r[3] or "", r[4] or "", r[5] or "", r[6] or "", parametres, r[8] or "", r[9] or "")


def charger_etude(conn, etude_id: int) -> Etude | None:
    r = conn.execute(
        "SELECT id, type, titre, analyte, unite, methode_x, methode_y, parametres, notes, date_creation "
        "FROM vm_etudes WHERE id = ?", (etude_id,)).fetchone()
    if r is None:
        return None
    etude = _etude(r)
    etude.donnees = [tuple(d) for d in conn.execute(
        "SELECT identifiant, x, y FROM vm_donnees WHERE etude_id = ? ORDER BY ordre", (etude_id,)).fetchall()]
    return etude


def enregistrer_etude(conn, etude: Etude) -> int:
    """Crée ou remplace une étude et toutes ses données (une seule transaction)."""
    if not etude.titre.strip():
        raise ValueError("Donnez un titre à l'étude avant de l'enregistrer.")
    if etude.type not in LIBELLES_TYPE:
        raise ValueError(f"Type d'étude inconnu : {etude.type}")
    valeurs = (etude.type, etude.titre.strip(), etude.analyte.strip(), etude.unite.strip(),
               etude.methode_x.strip(), etude.methode_y.strip(),
               json.dumps(etude.parametres, ensure_ascii=False), etude.notes)
    try:
        if etude.id is None:
            etude.id = conn.execute(
                "INSERT INTO vm_etudes (type, titre, analyte, unite, methode_x, methode_y, parametres, notes) "
                "VALUES (?,?,?,?,?,?,?,?)", valeurs).lastrowid
        else:
            conn.execute(
                "UPDATE vm_etudes SET type=?, titre=?, analyte=?, unite=?, methode_x=?, methode_y=?, parametres=?, "
                "notes=? WHERE id=?", valeurs + (etude.id,))
            conn.execute("DELETE FROM vm_donnees WHERE etude_id = ?", (etude.id,))
        conn.executemany(
            "INSERT INTO vm_donnees (etude_id, ordre, identifiant, x, y) VALUES (?,?,?,?,?)",
            [(etude.id, i, ident, x, y) for i, (ident, x, y) in enumerate(etude.donnees)])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return etude.id


def supprimer_etude(conn, etude_id: int) -> None:
    conn.execute("DELETE FROM vm_etudes WHERE id = ?", (etude_id,))
    conn.commit()


# ------------------------------------------------------------------
# Jeux d'exemple (données fictives, pour découvrir les outils)
# ------------------------------------------------------------------
def exemple_comparaison(graine: int = 7) -> list[tuple[str, float, float]]:
    """50 échantillons de créatinine fictifs (µmol/L) répartis sur l'étendue de mesure,
    méthode évaluée avec un léger biais proportionnel (+3 %) et constant (+2 µmol/L)."""
    rng = random.Random(graine)
    lignes = []
    for i in range(50):
        vraie = rng.uniform(35, 650) if i % 5 else rng.uniform(40, 120)
        x = vraie * (1 + rng.gauss(0, 0.025))
        y = (2 + 1.03 * vraie) * (1 + rng.gauss(0, 0.025))
        lignes.append((f"E{i + 1:03d}", round(x, 1), round(y, 1)))
    return lignes


def exemple_fidelite(graine: int = 11) -> list[tuple[str, float]]:
    """Plan 5 jours × 5 répétitions (type CLSI EP15) sur un contrôle de TSH fictif."""
    rng = random.Random(graine)
    lignes = []
    for jour in range(1, 6):
        effet_jour = rng.gauss(0, 0.035)
        for _ in range(5):
            lignes.append((f"Jour {jour}", round(2.10 + effet_jour + rng.gauss(0, 0.045), 3)))
    return lignes
