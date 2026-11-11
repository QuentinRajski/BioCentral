"""
Pipeline d'import d'un fichier Excel exporté par la machine, pour le module
Études de population (anciennement « Contrôle qualité », préfixe qc_ en base).

Règles appliquées (validées avec l'utilisateur sur le fichier réel LH) :
  - Colonnes ignorées à l'import : Patient (nom), Corres., Docteur
  - Lignes sans date de naissance : écartées (contrôle interne machine, pas un patient)
  - Colonne 8 de l'en-tête = nom du paramètre, valeur du résultat
  - "<X" / ">X"   -> statut sous_seuil / sur_seuil, valeur_numerique = seuil
  - "Res annulé", "VCOM" ou toute valeur non reconnue -> statut exclu
  - Valeur numérique normale -> statut valide

Corrections et ajouts de la v2 :
  - la feuille lue pour détecter le paramètre est TOUJOURS celle qui est
    importée (« Total » si elle existe, sinon la première) : la v1 détectait le
    paramètre sur la feuille active et importait la feuille « Total », ce qui
    pouvait diverger, et plantait sur un classeur multi-feuilles sans « Total » ;
  - un nombre stocké en texte (« 4,8 ») est un résultat valide, plus un exclu ;
  - un résultat numérique hors du domaine de mesure est classé sous/sur seuil
    dès l'import (même règle que lors d'une modification du domaine) ;
  - le sexe est normalisé (F, Femme, féminin… -> Féminin) ; une valeur
    inconnue rend la ligne incomplète au lieu de faire échouer tout l'import ;
  - les dates en texte (« 13/02/1989 ») sont lues ;
  - l'import est une transaction unique : en cas d'erreur, rien n'est écrit ;
  - les âges non couverts par les tranches sont comptés et signalés.
"""
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import openpyxl

from core.formatage import parse_date, parse_nombre

VALEURS_EXCLUES = {"res annulé", "res annule", "vcom"}
COLONNES_IGNOREES = {"Patient", "Corres.", "Docteur"}
NOM_FEUILLE_PRINCIPALE = "Total"
LIGNES_MAX_RECHERCHE_ENTETE = 5
SEXES = {
    "féminin": "Féminin", "feminin": "Féminin", "f": "Féminin", "femme": "Féminin", "fille": "Féminin",
    "masculin": "Masculin", "m": "Masculin", "h": "Masculin", "homme": "Masculin", "garçon": "Masculin",
    "garcon": "Masculin",
}
_RE_SEUIL = re.compile(r"^(<=?|≤|>=?|≥)\s*([\d.,]+)$")


@dataclass
class ImportSummary:
    parametre: str
    n_importes: int
    n_controle_machine: int
    n_incomplets: int
    n_hors_tranches: int = 0
    n_sous_seuil: int = 0
    n_sur_seuil: int = 0
    n_exclus: int = 0


@dataclass
class ApercuFichier:
    parametre: str
    feuille: str
    n_patients: int
    n_controle_machine: int
    n_incomplets: int
    age_min: int | None
    age_max: int | None
    n_feminin: int
    n_masculin: int
    date_min: str | None
    date_max: str | None
    domaine_suggere: tuple[float, float] | None
    ages: list[int] = field(default_factory=list)


# ------------------------------------------------------------------
# Lecture du classeur
# ------------------------------------------------------------------
def _age_at(naissance: date, prelevement: date) -> int:
    return prelevement.year - naissance.year - (
        (prelevement.month, prelevement.day) < (naissance.month, naissance.day)
    )


def normaliser_sexe(valeur) -> str | None:
    if valeur is None:
        return None
    return SEXES.get(str(valeur).strip().lower())


def _en_date(valeur) -> date | None:
    if isinstance(valeur, datetime):
        return valeur.date()
    if isinstance(valeur, date):
        return valeur
    d = parse_date(valeur)
    return d.date() if d else None


def _numero(valeur) -> str:
    if isinstance(valeur, float) and valeur.is_integer():
        return str(int(valeur))
    return str(valeur).strip()


def classify_value(raw, domaine_min: float | None = None, domaine_max: float | None = None):
    """Retourne (statut, valeur_numerique) pour une cellule de résultat brute."""
    domaine_valide = domaine_min is not None and domaine_max is not None and domaine_max > domaine_min

    def selon_domaine(v: float):
        if domaine_valide and v < domaine_min:
            return "sous_seuil", v
        if domaine_valide and v > domaine_max:
            return "sur_seuil", v
        return "valide", v

    if isinstance(raw, bool) or raw is None:
        return "exclu", None
    if isinstance(raw, (int, float)):
        return selon_domaine(float(raw))

    s = str(raw).strip()
    if s.lower() in VALEURS_EXCLUES:
        return "exclu", None
    m = _RE_SEUIL.match(s)
    if m:
        seuil = parse_nombre(m.group(2))
        if seuil is None:
            return "exclu", None
        return ("sous_seuil" if m.group(1) in ("<", "<=", "≤") else "sur_seuil"), seuil
    v = parse_nombre(s)
    if v is not None:
        return selon_domaine(v)
    # Valeur textuelle non reconnue : exclue par sécurité plutôt que de fausser les stats.
    return "exclu", None


def choisir_feuille(classeur):
    """Feuille à importer : « Total » si le classeur en a une, sinon la première."""
    if NOM_FEUILLE_PRINCIPALE in classeur.sheetnames:
        return classeur[NOM_FEUILLE_PRINCIPALE]
    return classeur[classeur.sheetnames[0]]


def _localiser_ligne_entete(sheet) -> int:
    """
    Retrouve la vraie ligne d'en-tête en cherchant "Sexe" en colonne C, plutôt
    que de supposer qu'elle est toujours en ligne 2. Si un futur export change de
    format, ce mécanisme s'adapte au lieu de lire une ligne de données comme en-tête.
    """
    for i, row in enumerate(
        sheet.iter_rows(min_row=1, max_row=LIGNES_MAX_RECHERCHE_ENTETE, values_only=True), start=1
    ):
        if len(row) > 2 and str(row[2]).strip() == "Sexe":
            return i
    raise ValueError(
        "Impossible de trouver la ligne d'en-tête (colonne « Sexe » introuvable en colonne C dans les "
        f"{LIGNES_MAX_RECHERCHE_ENTETE} premières lignes). Le format du fichier a peut-être changé."
    )


def detect_parametre(sheet) -> str:
    """
    Le paramètre est toujours à la position 8 (index 7) de la ligne d'en-tête,
    juste après les 7 colonnes fixes (Patient, Né(e) le, Sexe, N° demande, Date
    de prél., Corres., Docteur). On ne prend pas « la dernière cellule non vide » :
    certains fichiers ont une colonne d'annotation plus loin (ex. « Domaine de mesure »).
    """
    ligne_entete = _localiser_ligne_entete(sheet)
    header_row = next(sheet.iter_rows(min_row=ligne_entete, max_row=ligne_entete, values_only=True))
    if len(header_row) <= 7 or not header_row[7]:
        raise ValueError("Impossible de détecter le nom du paramètre en colonne 8 de l'en-tête.")
    return str(header_row[7]).strip()


def _domaine_annote(sheet, ligne_entete: int) -> tuple[float, float] | None:
    """Certains exports portent une colonne « Domaine de mesure » (ex. « 0,3 -250 ») :
    on la lit pour pré-remplir le domaine à l'écran d'import."""
    entete = next(sheet.iter_rows(min_row=ligne_entete, max_row=ligne_entete, values_only=True))
    for col, titre in enumerate(entete):
        if titre and "domaine" in str(titre).lower():
            for row in sheet.iter_rows(min_row=ligne_entete + 1, max_row=ligne_entete + 20, values_only=True):
                if col < len(row) and row[col]:
                    nombres = re.findall(r"\d+(?:[.,]\d+)?", str(row[col]))
                    if len(nombres) >= 2:
                        bas, haut = parse_nombre(nombres[0]), parse_nombre(nombres[1])
                        if bas is not None and haut is not None and haut > bas:
                            return bas, haut
    return None


def _ouvrir(filepath: Path):
    return openpyxl.load_workbook(filepath, data_only=True)


def lire_parametre(filepath: Path) -> str:
    """Nom du paramètre détecté dans la feuille qui sera importée."""
    return detect_parametre(choisir_feuille(_ouvrir(filepath)))


def _lignes_patients(sheet, ligne_entete: int):
    """Itère sur les lignes de données : (naissance, sexe, numero, prelevement, valeur) bruts."""
    for row in sheet.iter_rows(min_row=ligne_entete + 1, max_row=sheet.max_row, values_only=True):
        cellules = list(row) + [None] * 8
        if all(c is None or str(c).strip() == "" for c in cellules[:8]):
            continue  # ligne entièrement vide (fin de tableau, séparation)
        yield cellules[1], cellules[2], cellules[3], cellules[4], cellules[7]


def apercu_fichier(filepath: Path) -> ApercuFichier:
    """Lecture à blanc du fichier, sans rien écrire en base : ce qui sera importé."""
    feuille = choisir_feuille(_ouvrir(filepath))
    ligne_entete = _localiser_ligne_entete(feuille)
    parametre = detect_parametre(feuille)
    n = n_machine = n_incomplets = n_f = n_m = 0
    ages: list[int] = []
    dates: list[date] = []
    for naissance, sexe, _numero_, prelevement, valeur in _lignes_patients(feuille, ligne_entete):
        if naissance is None:
            n_machine += 1
            continue
        d_naissance, d_prelevement, s = _en_date(naissance), _en_date(prelevement), normaliser_sexe(sexe)
        if d_naissance is None or d_prelevement is None or s is None or valeur is None:
            n_incomplets += 1
            continue
        n += 1
        ages.append(_age_at(d_naissance, d_prelevement))
        dates.append(d_prelevement)
        n_f += s == "Féminin"
        n_m += s == "Masculin"
    return ApercuFichier(
        parametre=parametre, feuille=feuille.title, n_patients=n, n_controle_machine=n_machine,
        n_incomplets=n_incomplets, age_min=min(ages) if ages else None, age_max=max(ages) if ages else None,
        n_feminin=n_f, n_masculin=n_m,
        date_min=min(dates).isoformat() if dates else None, date_max=max(dates).isoformat() if dates else None,
        domaine_suggere=_domaine_annote(feuille, ligne_entete), ages=ages,
    )


# ------------------------------------------------------------------
# Tranches d'âge
# ------------------------------------------------------------------
def assign_tranche(age: int, tranches: list[tuple[int, int, int]]) -> int | None:
    """tranches : liste de (age_min, age_max, tranche_id). age_min inclus, age_max exclu."""
    for age_min, age_max, tid in tranches:
        if age_min <= age < age_max:
            return tid
    return None


def valider_tranches(tranches: list[tuple[int, int, str]]) -> list[str]:
    """Erreurs bloquantes : tranche vide ou inversée, chevauchement, libellé en double."""
    erreurs = []
    for age_min, age_max, libelle in tranches:
        if age_max <= age_min:
            erreurs.append(f"Tranche « {libelle} » : l'âge max ({age_max}) doit être supérieur à l'âge min ({age_min}).")
    ordonnees = sorted(tranches)
    for (a_min, a_max, a_lib), (b_min, _b_max, b_lib) in zip(ordonnees, ordonnees[1:]):
        if b_min < a_max:
            erreurs.append(f"Les tranches « {a_lib} » et « {b_lib} » se chevauchent : un patient de {b_min} ans "
                           "appartiendrait aux deux.")
    libelles = [l for *_, l in tranches]
    for l in sorted(set(libelles)):
        if libelles.count(l) > 1:
            erreurs.append(f"Le libellé « {l} » est utilisé par plusieurs tranches.")
    return erreurs


def ages_non_couverts(ages: list[int], tranches: list[tuple[int, int, str]]) -> list[int]:
    """Âges présents dans les données mais rattachés à aucune tranche."""
    return sorted({a for a in ages if not any(t_min <= a < t_max for t_min, t_max, _ in tranches)})


def libelle_tranche_auto(age_min: int, age_max: int) -> str:
    return f"{age_min} à {age_max} ans"


# ------------------------------------------------------------------
# Import
# ------------------------------------------------------------------
def import_file(
    conn,
    filepath: Path,
    domaine_min: float,
    domaine_max: float,
    tranches: list[tuple[int, int, str]],
    replace_existing: bool = False,
    unite: str | None = None,
) -> ImportSummary:
    """
    Pipeline complet : lit le fichier, crée le paramètre et ses tranches d'âge,
    insère les échantillons. Une seule transaction : si quoi que ce soit échoue,
    la base reste exactement dans son état précédent.

    Si le paramètre existe déjà :
      - replace_existing=False (par défaut) -> lève ValueError, à l'appelant de
        vérifier au préalable via parametre_existe() et de confirmer avec l'utilisateur ;
      - replace_existing=True -> l'ancien paramètre et toutes ses données
        (tranches, échantillons) sont supprimés avant l'import (ON DELETE CASCADE).
        L'intervalle de référence à vérifier, les notes et l'unité sont conservés.
    """
    erreurs = valider_tranches(tranches)
    if erreurs:
        raise ValueError("\n".join(erreurs))
    filepath = Path(filepath)
    sheet = choisir_feuille(_ouvrir(filepath))
    ligne_entete = _localiser_ligne_entete(sheet)
    parametre = detect_parametre(sheet)

    try:
        anciens = None
        if parametre_existe(conn, parametre):
            if not replace_existing:
                raise ValueError(f"Le paramètre « {parametre} » existe déjà.")
            ancien_id, notes, ancienne_unite = conn.execute(
                "SELECT id, notes, unite FROM qc_parametres WHERE nom = ?", (parametre,)).fetchone()
            intervalles = conn.execute(
                "SELECT tranche_libelle, sexe, borne_basse, borne_haute, source FROM qc_intervalles_reference "
                "WHERE parametre_id = ?", (ancien_id,)).fetchall()
            anciens = (notes, ancienne_unite, intervalles)
            conn.execute("DELETE FROM qc_parametres WHERE id = ?", (ancien_id,))

        cur = conn.execute(
            "INSERT INTO qc_parametres (nom, domaine_min, domaine_max, fichier_source, unite, notes) VALUES (?,?,?,?,?,?)",
            (parametre, domaine_min, domaine_max, filepath.name,
             unite if unite is not None else (anciens[1] if anciens else None),
             anciens[0] if anciens else None),
        )
        parametre_id = cur.lastrowid
        if anciens:
            conn.executemany(
                "INSERT INTO qc_intervalles_reference (parametre_id, tranche_libelle, sexe, borne_basse, borne_haute, "
                "source) VALUES (?,?,?,?,?,?)", [(parametre_id,) + tuple(r) for r in anciens[2]])

        tranche_ids = []
        for age_min, age_max, libelle in tranches:
            c = conn.execute(
                "INSERT INTO qc_tranches_age (parametre_id, age_min, age_max, libelle) VALUES (?,?,?,?)",
                (parametre_id, age_min, age_max, libelle),
            )
            tranche_ids.append((age_min, age_max, c.lastrowid))

        resume = ImportSummary(parametre, 0, 0, 0)
        for naissance, sexe, numero, prelevement, valeur in _lignes_patients(sheet, ligne_entete):
            if naissance is None:
                resume.n_controle_machine += 1
                continue
            d_naissance, d_prelevement, s = _en_date(naissance), _en_date(prelevement), normaliser_sexe(sexe)
            if d_naissance is None or d_prelevement is None or s is None or valeur is None or numero is None:
                resume.n_incomplets += 1
                continue

            age = _age_at(d_naissance, d_prelevement)
            statut, valeur_num = classify_value(valeur, domaine_min, domaine_max)
            tranche_id = assign_tranche(age, tranche_ids)
            resume.n_hors_tranches += tranche_id is None
            resume.n_sous_seuil += statut == "sous_seuil"
            resume.n_sur_seuil += statut == "sur_seuil"
            resume.n_exclus += statut == "exclu"
            texte_valeur = str(valeur)   # texte exact d'origine, comme en v1 (« 0.3 », « 6 », « <0.3 »)
            conn.execute(
                """INSERT INTO qc_echantillons
                   (parametre_id, numero_demande, sexe, date_naissance, date_prelevement,
                    age_annees, tranche_age_id, valeur_affichee, valeur_numerique, statut)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (parametre_id, _numero(numero), s, d_naissance.isoformat(), d_prelevement.isoformat(),
                 age, tranche_id, texte_valeur.strip(), valeur_num, statut),
            )
            resume.n_importes += 1

        if resume.n_importes == 0:
            raise ValueError("Aucun échantillon exploitable dans ce fichier (dates, sexe ou résultat manquants).")
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return resume


# ------------------------------------------------------------------
# Paramètres déjà importés
# ------------------------------------------------------------------
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
    courant, qui peut avoir déjà été modifié par un précédent réglage des bornes.
    """
    try:
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
            if _RE_SEUIL.match(texte):
                continue  # annotation explicite de la machine, jamais reclassée
            valeur = parse_nombre(texte)
            if valeur is None:
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
    except Exception:
        conn.rollback()
        raise


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
    réattribués aux nouvelles tranches à partir de leur âge déjà calculé et figé.

    Ordre précis pour ne jamais perdre de données : on détache d'abord les
    échantillons (tranche_age_id -> NULL), puis seulement on supprime les
    anciennes tranches — sinon ON DELETE CASCADE supprimerait les échantillons.
    """
    erreurs = valider_tranches(tranches)
    if erreurs:
        raise ValueError("\n".join(erreurs))
    try:
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
    except Exception:
        conn.rollback()
        raise


def supprimer_parametre(conn, parametre_id: int) -> None:
    conn.execute("DELETE FROM qc_parametres WHERE id = ?", (parametre_id,))
    conn.commit()


def get_unite(conn, parametre_id: int) -> str:
    row = conn.execute("SELECT unite FROM qc_parametres WHERE id = ?", (parametre_id,)).fetchone()
    return (row[0] or "") if row else ""


def definir_unite(conn, parametre_id: int, unite: str) -> None:
    conn.execute("UPDATE qc_parametres SET unite = ? WHERE id = ?", ((unite or "").strip() or None, parametre_id))
    conn.commit()


# ------------------------------------------------------------------
# Intervalles de référence à vérifier
# ------------------------------------------------------------------
def get_intervalle_reference(conn, parametre_id: int, tranche_libelle: str = "", sexe: str = ""):
    """(borne_basse, borne_haute, source) le plus spécifique disponible pour ce
    filtre : tranche + sexe, sinon tranche seule, sinon sexe seul, sinon global."""
    for t, s in ((tranche_libelle, sexe), (tranche_libelle, ""), ("", sexe), ("", "")):
        row = conn.execute(
            "SELECT borne_basse, borne_haute, source, tranche_libelle, sexe FROM qc_intervalles_reference "
            "WHERE parametre_id = ? AND tranche_libelle = ? AND sexe = ?", (parametre_id, t or "", s or "")).fetchone()
        if row:
            return row
    return None


def lister_intervalles_reference(conn, parametre_id: int) -> list[tuple]:
    return conn.execute(
        "SELECT tranche_libelle, sexe, borne_basse, borne_haute, source FROM qc_intervalles_reference "
        "WHERE parametre_id = ? ORDER BY tranche_libelle, sexe", (parametre_id,)).fetchall()


def enregistrer_intervalles_reference(conn, parametre_id: int, lignes: list[tuple]) -> None:
    """Remplace tous les intervalles du paramètre par `lignes` :
    (tranche_libelle, sexe, borne_basse, borne_haute, source)."""
    vus = set()
    for tranche, sexe, bas, haut, _source in lignes:
        if bas is None and haut is None:
            raise ValueError("Chaque intervalle doit avoir au moins une borne.")
        if bas is not None and haut is not None and haut <= bas:
            raise ValueError(f"Borne haute ≤ borne basse pour « {tranche or 'toutes tranches'} / {sexe or 'tous'} ».")
        cle = (tranche or "", sexe or "")
        if cle in vus:
            raise ValueError(f"Deux intervalles portent sur « {tranche or 'toutes tranches'} / {sexe or 'tous'} ».")
        vus.add(cle)
    try:
        conn.execute("DELETE FROM qc_intervalles_reference WHERE parametre_id = ?", (parametre_id,))
        conn.executemany(
            "INSERT INTO qc_intervalles_reference (parametre_id, tranche_libelle, sexe, borne_basse, borne_haute, source) "
            "VALUES (?,?,?,?,?,?)",
            [(parametre_id, t or "", s or "", b, h, src) for t, s, b, h, src in lignes])
        conn.commit()
    except Exception:
        conn.rollback()
        raise
