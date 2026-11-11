"""
Mise en forme et lecture des nombres et des dates, partagées par tous les modules.

Affichage : point décimal, comme dans les exports des automates et le reste de
l'application. Lecture : la virgule ET le point sont acceptés (un collage depuis
un Excel français donne « 4,8 »).
"""
import math
from datetime import date, datetime

TIRET = "—"


def fmt(valeur, chiffres: int = 4) -> str:
    """Nombre arrondi à `chiffres` chiffres significatifs, sans zéros inutiles ni
    notation scientifique. None / NaN -> « — »."""
    if valeur is None:
        return TIRET
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return str(valeur)
    if math.isnan(v) or math.isinf(v):
        return TIRET
    if v == 0:
        return "0"
    a = abs(v)
    if a >= 10 ** chiffres:
        return f"{v:.0f}"
    decimales = min(max(0, chiffres - 1 - math.floor(math.log10(a))), 8)
    texte = f"{v:.{decimales}f}"
    if "." in texte:
        texte = texte.rstrip("0").rstrip(".")
    return "0" if texte in ("-0", "") else texte


def fmt_dec(valeur, decimales: int = 2) -> str:
    """Nombre à nombre de décimales fixe (pourcentages, scores z...)."""
    if valeur is None:
        return TIRET
    try:
        v = float(valeur)
    except (TypeError, ValueError):
        return str(valeur)
    if math.isnan(v) or math.isinf(v):
        return TIRET
    return f"{v:.{decimales}f}"


def fmt_p(p) -> str:
    """Valeur p : « p < 0.0001 » en dessous du seuil d'affichage."""
    if p is None or (isinstance(p, float) and math.isnan(p)):
        return TIRET
    return "p < 0.0001" if p < 0.0001 else f"p = {p:.4f}"


def fmt_intervalle(bas, haut, chiffres: int = 4) -> str:
    if bas is None or haut is None:
        return TIRET
    return f"[{fmt(bas, chiffres)} ; {fmt(haut, chiffres)}]"


def parse_nombre(texte) -> float | None:
    """Lit un nombre saisi ou collé : accepte « 4,8 », « 4.8 », « 1 234,5 », les
    espaces insécables. Retourne None si ce n'est pas un nombre (cellule vide,
    « <0.3 », texte...)."""
    if texte is None:
        return None
    if isinstance(texte, bool):
        return None
    if isinstance(texte, (int, float)):
        v = float(texte)
        return None if math.isnan(v) or math.isinf(v) else v
    s = str(texte).strip().replace(" ", "").replace(" ", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        # « 1.234,5 » (français) ou « 1,234.5 » (anglais) : le dernier séparateur est la décimale
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    else:
        s = s.replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None
    return None if math.isnan(v) or math.isinf(v) else v


def date_fr(iso) -> str:
    """« AAAA-MM-JJ[ HH:MM[:SS]] » -> « JJ/MM/AAAA ». Tout autre texte est rendu tel quel."""
    if not iso:
        return ""
    texte = str(iso)
    try:
        annee, mois, jour = texte[:10].split("-")
        return f"{jour}/{mois}/{annee}"
    except ValueError:
        return texte


def datetime_fr(iso) -> str:
    """« AAAA-MM-JJ HH:MM » -> « JJ/MM/AAAA HH:MM » (l'heure est omise si absente ou 00:00)."""
    if not iso:
        return ""
    texte = str(iso).replace("T", " ")
    jour = date_fr(texte)
    heure = texte[11:16]
    return f"{jour} {heure}" if heure and heure != "00:00" else jour


def parse_date(valeur) -> datetime | None:
    """Lit une date venant d'Excel (datetime/date) ou d'un texte : « JJ/MM/AAAA »,
    « JJ/MM/AAAA HH:MM », « AAAA-MM-JJ », « AAAA-MM-JJ HH:MM[:SS] », « JJ-MM-AAAA »,
    « JJ.MM.AAAA », année sur 2 chiffres acceptée. Retourne None si illisible."""
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        return valeur
    if isinstance(valeur, date):
        return datetime(valeur.year, valeur.month, valeur.day)
    texte = str(valeur).strip().replace("T", " ")
    if not texte:
        return None
    formats = (
        "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d",
        "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y",
        "%d/%m/%y %H:%M", "%d/%m/%y",
        "%d-%m-%Y %H:%M", "%d-%m-%Y", "%d.%m.%Y %H:%M", "%d.%m.%Y",
    )
    for f in formats:
        try:
            return datetime.strptime(texte, f)
        except ValueError:
            continue
    return None
