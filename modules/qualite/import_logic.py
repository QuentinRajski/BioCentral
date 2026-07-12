"""
Pipeline d'import d'un fichier Excel exporté par la machine, pour le module Contrôle Qualité.

Règles appliquées (validées avec l'utilisateur sur le fichier réel LH) :
  - Colonnes ignorées à l'import : Patient (nom), Corres., Docteur
  - Lignes sans date de naissance : écartées (contrôle interne machine, pas un patient)
  - Dernière colonne du fichier = nom du paramètre, valeur du résultat
  - "<X" / ">X"   -> statut sous_seuil / sur_seuil, valeur_numerique = seuil
  - "Res annulé", "VCOM" ou toute valeur non reconnue -> statut exclu
  - Valeur numérique normale -> statut valide
"""
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import openpyxl

VALEURS_EXCLUES = {"res annulé", "vcom"}
COLONNES_IGNOREES = {"Patient", "Corres.", "Docteur"}


@dataclass
class ImportSummary:
    parametre: str
    n_importes: int
    n_controle_machine: int
    n_incomplets: int


def _age_at(naissance: date, prelevement: date) -> int:
    return prelevement.year - naissance.year - (
        (prelevement.month, prelevement.day) < (naissance.month, naissance.day)
    )


def classify_value(raw, domaine_min: float | None, domaine_max: float | None):
    """Retourne (statut, valeur_numerique) pour une cellule de résultat brute."""
    if isinstance(raw, (int, float)):
        return "valide", float(raw)

    s = str(raw).strip()
    if s.lower() in VALEURS_EXCLUES:
        return "exclu", None

    m = re.match(r"^<\s*([\d.,]+)$", s)
    if m:
        return "sous_seuil", float(m.group(1).replace(",", "."))

    m = re.match(r"^>\s*([\d.,]+)$", s)
    if m:
        return "sur_seuil", float(m.group(1).replace(",", "."))

    # Valeur textuelle non reconnue : exclue par sécurité plutôt que de fausser les stats.
    return "exclu", None


LIGNES_MAX_RECHERCHE_ENTETE = 5


def _localiser_ligne_entete(sheet) -> int:
    """
    Retrouve la vraie ligne d'en-tête en cherchant "Sexe" en colonne C, plutôt
    que de supposer qu'elle est toujours en ligne 2 (ce qui suppose qu'il y a
    toujours une ligne de titre au-dessus). Si un futur export change de format
    et que cette ligne de titre disparaît, ce mécanisme s'adapte automatiquement
    au lieu de lire silencieusement une ligne de données comme si c'était l'en-tête.
    """
    for i, row in enumerate(
        sheet.iter_rows(min_row=1, max_row=LIGNES_MAX_RECHERCHE_ENTETE, values_only=True), start=1
    ):
        if len(row) > 2 and str(row[2]).strip() == "Sexe":
            return i
    raise ValueError(
        "Impossible de trouver la ligne d'en-tête (colonne « Sexe » introuvable dans les "
        f"{LIGNES_MAX_RECHERCHE_ENTETE} premières lignes). Le format du fichier a peut-être changé."
    )


def detect_parametre(sheet) -> str:
    """
    Le paramètre est toujours à la position 8 (index 7) de la ligne d'en-tête,
    juste après les 7 colonnes fixes (Patient, Né(e) le, Sexe, N° demande, Date
    de prél., Corres., Docteur). On ne prend pas "la dernière cellule non vide"
    telle quelle : certains fichiers ont une colonne d'annotation isolée plus
    loin (ex. "Domaine de mesure"), qui n'est pas le paramètre.
    """
    ligne_entete = _localiser_ligne_entete(sheet)
    header_row = next(sheet.iter_rows(min_row=ligne_entete, max_row=ligne_entete, values_only=True))
    if len(header_row) <= 7 or not header_row[7]:
        raise ValueError("Impossible de détecter le nom du paramètre en colonne 8 de l'en-tête.")
    return str(header_row[7]).strip()


def assign_tranche(age: int, tranches: list[tuple[int, int, int]]) -> int | None:
    """tranches : liste de (age_min, age_max, tranche_id). age_max exclusif, sauf borne haute ouverte."""
    for age_min, age_max, tid in tranches:
        if age_min <= age < age_max:
            return tid
    return None


def import_file(
    conn,
    filepath: Path,
    domaine_min: float,
    domaine_max: float,
    tranches: list[tuple[int, int, str]],
    replace_existing: bool = False,
) -> ImportSummary:
    """
    Pipeline complet : lit le fichier, crée le paramètre et ses tranches d'âge,
    insère les échantillons valides.

    Si le paramètre existe déjà :
      - replace_existing=False (par défaut) -> lève ValueError, à l'appelant de
        vérifier au préalable via parametre_existe() et de confirmer avec l'utilisateur.
      - replace_existing=True -> l'ancien paramètre et toutes ses données
        (tranches, échantillons) sont supprimés avant l'import, proprement,
        grâce à ON DELETE CASCADE défini dans le schéma.
    """
    wb = openpyxl.load_workbook(filepath, data_only=True)
    sheet = wb[wb.sheetnames[0]] if len(wb.sheetnames) == 1 else wb["Total"]
    ligne_entete = _localiser_ligne_entete(sheet)
    parametre = detect_parametre(sheet)

    if parametre_existe(conn, parametre):
        if not replace_existing:
            raise ValueError(f"Le paramètre « {parametre} » existe déjà.")
        conn.execute("DELETE FROM qc_parametres WHERE nom = ?", (parametre,))

    cur = conn.execute(
        "INSERT INTO qc_parametres (nom, domaine_min, domaine_max, fichier_source) VALUES (?,?,?,?)",
        (parametre, domaine_min, domaine_max, filepath.name),
    )
    parametre_id = cur.lastrowid

    tranche_ids = []
    for age_min, age_max, libelle in tranches:
        c = conn.execute(
            "INSERT INTO qc_tranches_age (parametre_id, age_min, age_max, libelle) VALUES (?,?,?,?)",
            (parametre_id, age_min, age_max, libelle),
        )
        tranche_ids.append((age_min, age_max, c.lastrowid))

    n_importes = n_controle_machine = n_incomplets = 0

    for row in sheet.iter_rows(min_row=ligne_entete + 1, max_row=sheet.max_row, values_only=True):
        naissance, sexe, numero, prelevement, valeur = row[1], row[2], row[3], row[4], row[7]

        if naissance is None:
            n_controle_machine += 1
            continue
        if sexe is None or prelevement is None or valeur is None or not hasattr(prelevement, "year"):
            n_incomplets += 1
            continue

        age = _age_at(naissance.date() if hasattr(naissance, "date") else naissance,
                       prelevement.date() if hasattr(prelevement, "date") else prelevement)
        statut, valeur_num = classify_value(valeur, domaine_min, domaine_max)
        tranche_id = assign_tranche(age, tranche_ids)

        conn.execute(
            """INSERT INTO qc_echantillons
               (parametre_id, numero_demande, sexe, date_naissance, date_prelevement,
                age_annees, tranche_age_id, valeur_affichee, valeur_numerique, statut)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                parametre_id, str(numero), sexe,
                naissance.date().isoformat() if hasattr(naissance, "date") else naissance.isoformat(),
                prelevement.date().isoformat() if hasattr(prelevement, "date") else prelevement.isoformat(),
                age, tranche_id, str(valeur), valeur_num, statut,
            ),
        )
        n_importes += 1

    conn.commit()
    return ImportSummary(parametre, n_importes, n_controle_machine, n_incomplets)


def get_domaine_mesure(conn, parametre_id: int) -> tuple[float, float]:
    row = conn.execute(
        "SELECT domaine_min, domaine_max FROM qc_parametres WHERE id = ?", (parametre_id,)
    ).fetchone()
    return (row[0], row[1]) if row else (0.0, 0.0)


def modifier_domaine_mesure(conn, parametre_id: int, nouveau_min: float, nouveau_max: float) -> None:
    """
    Change les bornes du domaine de mesure d'un paramètre déjà importé.

    Ne touche qu'aux échantillons dont la valeur brute d'origine est un nombre
    simple (pas une annotation explicite de la machine comme "<0.3" ou
    "Res annulé") : si ce nombre sort des nouvelles bornes, son statut passe à
    sous_seuil/sur_seuil, sinon à valide. L'éligibilité se base sur le texte
    brut d'origine (valeur_affichee), qui ne change jamais — pas sur le statut
    courant, qui lui peut avoir déjà été modifié par un précédent réglage des
    bornes. C'est ce qui permet de changer les bornes plusieurs fois de suite :
    une version précédente basée sur le statut courant ne reclassait plus une
    ligne une fois qu'elle avait été touchée une première fois.
    """
    conn.execute(
        "UPDATE qc_parametres SET domaine_min = ?, domaine_max = ? WHERE id = ?",
        (nouveau_min, nouveau_max, parametre_id),
    )
    rows = conn.execute(
        "SELECT id, valeur_affichee, statut FROM qc_echantillons WHERE parametre_id = ?",
        (parametre_id,),
    ).fetchall()
    for echantillon_id, affichee, statut_actuel in rows:
        if statut_actuel == "exclu":
            continue  # Res annulé, VCOM... jamais reclassé
        texte = str(affichee).strip()
        if texte.startswith("<") or texte.startswith(">"):
            continue  # annotation explicite de la machine, jamais reclassée
        try:
            valeur = float(texte.replace(",", "."))
        except ValueError:
            continue
        if valeur < nouveau_min:
            nouveau_statut = "sous_seuil"
        elif valeur > nouveau_max:
            nouveau_statut = "sur_seuil"
        else:
            nouveau_statut = "valide"
        if nouveau_statut != statut_actuel:
            conn.execute(
                "UPDATE qc_echantillons SET statut = ? WHERE id = ?", (nouveau_statut, echantillon_id)
            )
    conn.commit()


def parametre_existe(conn, nom: str) -> bool:
    return conn.execute("SELECT 1 FROM qc_parametres WHERE nom = ?", (nom,)).fetchone() is not None


def get_tranches(conn, parametre_id: int) -> list[tuple[int, int, str]]:
    rows = conn.execute(
        "SELECT age_min, age_max, libelle FROM qc_tranches_age WHERE parametre_id = ? ORDER BY age_min",
        (parametre_id,),
    ).fetchall()
    return [(r[0], r[1], r[2]) for r in rows]


def modifier_tranches(conn, parametre_id: int, tranches: list[tuple[int, int, str]]) -> None:
    """
    Remplace les tranches d'âge d'un paramètre déjà importé, SANS toucher aux
    échantillons eux-mêmes ni réimporter le fichier Excel : ils sont simplement
    réattribués aux nouvelles tranches à partir de leur âge déjà calculé et figé
    à l'import.

    Étapes, dans cet ordre précis pour ne jamais perdre de données : on détache
    d'abord les échantillons de leurs tranches actuelles (tranche_age_id -> NULL),
    puis seulement on supprime les anciennes tranches — sinon la suppression
    d'une tranche encore référencée supprimerait aussi les échantillons via
    ON DELETE CASCADE.
    """
    conn.execute("UPDATE qc_echantillons SET tranche_age_id = NULL WHERE parametre_id = ?", (parametre_id,))
    conn.execute("DELETE FROM qc_tranches_age WHERE parametre_id = ?", (parametre_id,))

    tranche_ids = []
    for age_min, age_max, libelle in tranches:
        c = conn.execute(
            "INSERT INTO qc_tranches_age (parametre_id, age_min, age_max, libelle) VALUES (?,?,?,?)",
            (parametre_id, age_min, age_max, libelle),
        )
        tranche_ids.append((age_min, age_max, c.lastrowid))

    echantillons = conn.execute(
        "SELECT id, age_annees FROM qc_echantillons WHERE parametre_id = ?", (parametre_id,)
    ).fetchall()
    for echantillon_id, age in echantillons:
        tid = assign_tranche(age, tranche_ids)
        conn.execute("UPDATE qc_echantillons SET tranche_age_id = ? WHERE id = ?", (tid, echantillon_id))

    conn.commit()
