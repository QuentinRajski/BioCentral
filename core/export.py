"""
Exports communs à tous les modules : classeur Excel (openpyxl) et rapport PDF.

Le rapport PDF est produit par Qt lui-même (QTextDocument -> QPdfWriter) : pas
de dépendance supplémentaire, et le résultat est un vrai PDF texte (on peut y
chercher et copier), pas une capture d'écran.
"""
import html
import re
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QImage, QPageLayout, QPageSize, QPdfWriter, QTextDocument

from core.version import VERSION

_CSS = """
body  { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; color: #2C2C2A; }
h1    { font-size: 17pt; color: #0C447C; margin-bottom: 2px; }
h2    { font-size: 12pt; color: #0C447C; margin-top: 14px; margin-bottom: 4px; }
p     { margin-top: 3px; margin-bottom: 3px; }
.sous { color: #5F5E5A; font-size: 10pt; }
.pied { color: #8A887E; font-size: 8pt; margin-top: 14px; }
.note { color: #5F5E5A; font-size: 9pt; }
table { border-collapse: collapse; margin-top: 4px; margin-bottom: 6px; }
th    { background-color: #EEF4FA; color: #0C447C; font-weight: bold; padding: 4px 8px;
        border: 1px solid #C9D6E3; font-size: 9pt; }
td    { padding: 3px 8px; border: 1px solid #DAD8CE; font-size: 9pt; }
.ok     { color: #1E7D52; font-weight: bold; }
.alerte { color: #B07209; font-weight: bold; }
.rejet  { color: #C0392B; font-weight: bold; }
"""


def echapper(texte) -> str:
    return html.escape("" if texte is None else str(texte))


def table_html(entetes: list[str], lignes: list[list], alignement_droite: set[int] | None = None) -> str:
    """Tableau HTML simple. Les cellules sont échappées ; une cellule peut être un
    tuple (texte, classe_css) pour la colorer (ex. ("Rejet", "rejet"))."""
    droite = alignement_droite or set()
    morceaux = ["<table cellspacing='0'><tr>"]
    morceaux += [f"<th>{echapper(e)}</th>" for e in entetes]
    morceaux.append("</tr>")
    for ligne in lignes:
        morceaux.append("<tr>")
        for i, valeur in enumerate(ligne):
            classe = ""
            if isinstance(valeur, tuple):
                valeur, classe = valeur
            attributs = f" class='{classe}'" if classe else ""
            if i in droite:
                attributs += " align='right'"
            morceaux.append(f"<td{attributs}>{echapper(valeur)}</td>")
        morceaux.append("</tr>")
    morceaux.append("</table>")
    return "".join(morceaux)


def liste_html(elements: list[str]) -> str:
    if not elements:
        return ""
    return "<ul>" + "".join(f"<li>{echapper(e)}</li>" for e in elements) + "</ul>"


def image_html(nom: str, largeur: int = 640) -> str:
    """Balise d'une image passée dans le dict `images` de exporter_pdf."""
    return f"<p><img src='{nom}' width='{largeur}'></p>"


def exporter_pdf(chemin: Path, titre: str, corps_html: str, images: dict[str, QImage] | None = None,
                 sous_titre: str = "", paysage: bool = False) -> None:
    """Écrit un rapport PDF A4. `corps_html` est du HTML simple (h2, p, table, img)."""
    document = QTextDocument()
    for nom, image in (images or {}).items():
        document.addResource(QTextDocument.ImageResource, QUrl(nom), image)
    document.setDefaultStyleSheet(_CSS)
    pied = f"BioCentral {VERSION} — document édité le {datetime.now():%d/%m/%Y à %H:%M}"
    document.setHtml(
        f"<html><body><h1>{echapper(titre)}</h1>"
        + (f"<p class='sous'>{echapper(sous_titre)}</p>" if sous_titre else "")
        + corps_html
        + f"<p class='pied'>{echapper(pied)}</p></body></html>"
    )
    ecrivain = QPdfWriter(str(chemin))
    ecrivain.setPageSize(QPageSize(QPageSize.A4))
    ecrivain.setPageOrientation(QPageLayout.Landscape if paysage else QPageLayout.Portrait)
    ecrivain.setPageMargins(QMarginsF(14, 14, 14, 14), QPageLayout.Millimeter)
    ecrivain.setResolution(96)
    ecrivain.setTitle(titre)
    ecrivain.setCreator(f"BioCentral {VERSION}")
    document.print_(ecrivain)


def _nom_feuille(nom: str) -> str:
    return re.sub(r"[\[\]:*?/\\]", "-", nom)[:31] or "Feuille"


def exporter_excel(chemin: Path, feuilles: list[tuple[str, list[str], list[list]]]) -> None:
    """Écrit un classeur : une feuille par (nom, en-têtes, lignes). Les nombres
    restent des nombres (triables et calculables dans Excel), en-têtes en gras,
    volets figés et largeurs de colonnes ajustées au contenu."""
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    classeur = openpyxl.Workbook()
    classeur.remove(classeur.active)
    for nom, entetes, lignes in feuilles:
        feuille = classeur.create_sheet(_nom_feuille(nom))
        feuille.append(entetes)
        for cellule in feuille[1]:
            cellule.font = Font(bold=True, color="0C447C")
            cellule.fill = PatternFill("solid", fgColor="EEF4FA")
            cellule.alignment = Alignment(vertical="center")
        for ligne in lignes:
            feuille.append(list(ligne))
        feuille.freeze_panes = "A2"
        for index, entete in enumerate(entetes, start=1):
            longueurs = [len(str(entete))] + [
                len(str(l[index - 1])) for l in lignes if index - 1 < len(l) and l[index - 1] is not None
            ]
            feuille.column_dimensions[get_column_letter(index)].width = min(max(longueurs) + 2, 60)
    if not classeur.sheetnames:
        classeur.create_sheet("Feuille")
    classeur.save(chemin)


def lire_tableau(chemin: Path) -> list[list]:
    """Lit la première feuille d'un .xlsx ou un fichier .csv/.txt et rend ses lignes
    (valeurs brutes pour Excel, textes pour CSV). Les lignes entièrement vides sont
    ignorées. Séparateur CSV détecté : point-virgule, tabulation, sinon virgule."""
    chemin = Path(chemin)
    if chemin.suffix.lower() in (".xlsx", ".xlsm"):
        import openpyxl
        classeur = openpyxl.load_workbook(chemin, data_only=True, read_only=True)
        try:
            feuille = classeur[classeur.sheetnames[0]]
            lignes = [list(l) for l in feuille.iter_rows(values_only=True)]
        finally:
            classeur.close()
    else:
        import csv
        brut = chemin.read_bytes()
        for encodage in ("utf-8-sig", "cp1252"):
            try:
                texte = brut.decode(encodage)
                break
            except UnicodeDecodeError:
                continue
        else:
            texte = brut.decode("latin-1")
        premiere = texte.splitlines()[0] if texte.splitlines() else ""
        separateur = ";" if ";" in premiere else "\t" if "\t" in premiere else ","
        lignes = [l for l in csv.reader(texte.splitlines(), delimiter=separateur)]
    return [l for l in lignes if any(c is not None and str(c).strip() != "" for c in l)]
