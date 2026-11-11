"""
Thèmes clair/sombre de l'application (socle commun).

Toute couleur utilisée quelque part dans l'appli — que ce soit via la feuille
de style Qt (QSS) ou codée en dur dans un widget (couleurs de graphique,
alternance de lignes d'un tableau...) — doit venir d'ici, jamais d'un code
hexadécimal recopié ailleurs. C'est ce qui permet à `ThemeManager.toggle()`
de changer instantanément TOUT l'habillage de l'appli, pas seulement les
widgets standards que Qt sait styliser tout seul via QSS.

Utilisation :
    from core import theme
    theme.palette()            -> dict de couleurs (str hexadécimales) du thème actif
    theme.qcolor("accent_text") -> la même couleur, déjà en QColor
    theme.ThemeManager.instance().toggle(conn)  -> bascule clair/sombre et persiste le choix
"""
from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication

from . import database

# Couleurs d'accent (bordures de carte, catégories de graphique) : suffisamment
# saturées pour rester lisibles sur fond clair comme sur fond sombre, donc
# communes aux deux thèmes plutôt que dupliquées dans chaque palette.
ACCENT_BLEU = "#378ADD"
ACCENT_VERT = "#6B9E7C"
ACCENT_VIOLET = "#7F77DD"
ACCENT_ROSE = "#D4537E"

PALETTES = {
    "light": {
        "bg": "#F7F6F2",
        "text": "#2C2C2A",
        "sidebar_bg": "#F1EFE8",
        "sidebar_border": "#E1DFD5",
        "btn_bg": "#FFFFFF",
        "btn_border": "#D3D1C7",
        "btn_hover_bg": "#F1EFE8",
        "btn_hover_border": "#B8B6AB",
        "btn_pressed_bg": "#E1DFD5",
        "primary_bg": "#0C447C",
        "primary_hover": "#135A9E",
        "primary_text": "#FFFFFF",
        "input_border": "#D3D1C7",
        "input_bg": "#FFFFFF",
        "focus_border": "#378ADD",
        "selection_bg": "#E6F1FB",
        "selection_text": "#0C447C",
        "table_bg": "#FFFFFF",
        "table_item_border": "#EDEBE2",
        "header_text": "#5F5E5A",
        "card_bg": "#FFFFFF",
        "card_border": "#E1DFD5",
        "card_hover_bg": "#F7FBFF",
        "muted": "#8A887E",
        "accent_text": "#0C447C",
        "list_hover_bg": "#EDEBE2",
        "scrollbar_handle": "#D3D1C7",
        "scrollbar_handle_hover": "#B8B6AB",
        "tooltip_bg": "#2C2C2A",
        "tooltip_text": "#F7F6F2",
        # Couleurs utilisées directement en code (tableaux, graphiques), pas via QSS.
        "table_row_pair": "#FFFFFF",
        "table_row_impair": "#FAF9F5",
        "table_highlight": "#FBEAEA",
    },
    "dark": {
        "bg": "#1E1F22",
        "text": "#E4E2DD",
        "sidebar_bg": "#202124",
        "sidebar_border": "#33343A",
        "btn_bg": "#2B2C30",
        "btn_border": "#3D3E44",
        "btn_hover_bg": "#34353B",
        "btn_hover_border": "#4A4B52",
        "btn_pressed_bg": "#3D3E44",
        "primary_bg": "#2F7DD1",
        "primary_hover": "#3E8EE0",
        "primary_text": "#FFFFFF",
        "input_border": "#3D3E44",
        "input_bg": "#2B2C30",
        "focus_border": "#4FA3EF",
        "selection_bg": "#234A6E",
        "selection_text": "#BFE0FF",
        "table_bg": "#232428",
        "table_item_border": "#303136",
        "header_text": "#9A9890",
        "card_bg": "#232428",
        "card_border": "#33343A",
        "card_hover_bg": "#26313F",
        "muted": "#8F8D86",
        "accent_text": "#5FA8E8",
        "list_hover_bg": "#2B2C30",
        "scrollbar_handle": "#3D3E44",
        "scrollbar_handle_hover": "#4A4B52",
        "tooltip_bg": "#3D3E44",
        "tooltip_text": "#E4E2DD",
        "table_row_pair": "#232428",
        "table_row_impair": "#28292E",
        "table_highlight": "#4A2C2C",
    },
}

_TEMPLATE = """
QWidget {{
    background-color: {bg};
    color: {text};
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}}

QLabel {{
    background-color: transparent;
}}

#Sidebar {{
    background-color: {sidebar_bg};
    border-right: 1px solid {sidebar_border};
}}

QPushButton {{
    background-color: {btn_bg};
    border: 1px solid {btn_border};
    border-radius: 8px;
    padding: 7px 16px;
}}
QPushButton:hover {{
    background-color: {btn_hover_bg};
    border-color: {btn_hover_border};
}}
QPushButton:pressed {{
    background-color: {btn_pressed_bg};
}}
QPushButton#PrimaryButton {{
    background-color: {primary_bg};
    color: {primary_text};
    border: none;
    font-weight: 600;
    padding: 8px 20px;
}}
QPushButton#PrimaryButton:hover {{
    background-color: {primary_hover};
}}

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QTextEdit {{
    border: 1px solid {input_border};
    border-radius: 8px;
    padding: 6px 10px;
    background-color: {input_bg};
    min-height: 20px;
}}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
    border: 1px solid {focus_border};
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    border: 1px solid {input_border};
    border-radius: 8px;
    background-color: {input_bg};
    selection-background-color: {selection_bg};
    selection-color: {selection_text};
    outline: none;
}}

/* --- Tableaux : le plus gros du travail de modernisation --- */
QTableWidget {{
    background-color: {table_bg};
    border: none;
    gridline-color: transparent;
    selection-background-color: {selection_bg};
    selection-color: {selection_text};
}}
QTableWidget::item {{
    padding: 9px 12px;
    border-bottom: 1px solid {table_item_border};
}}
QHeaderView::section {{
    background-color: transparent;
    color: {header_text};
    border: none;
    border-bottom: 1px solid {btn_border};
    padding: 9px 12px;
    font-weight: 600;
    font-size: 12px;
}}
QHeaderView::section:horizontal {{ border-right: none; }}
QTableCornerButton::section {{
    background-color: transparent;
    border: none;
}}

#Card {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 12px;
}}

#CardAccentBleu {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-top: 3px solid """ + ACCENT_BLEU + """;
    border-radius: 12px;
}}
#CardAccentVert {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-top: 3px solid """ + ACCENT_VERT + """;
    border-radius: 12px;
}}
#CardAccentViolet {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-top: 3px solid """ + ACCENT_VIOLET + """;
    border-radius: 12px;
}}
#CardAccentRose {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-top: 3px solid """ + ACCENT_ROSE + """;
    border-radius: 12px;
}}

#ModuleCard {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 12px;
}}
#ModuleCard:hover {{
    border: 1px solid """ + ACCENT_BLEU + """;
}}

QLabel#Muted {{
    color: {muted};
    font-size: 12px;
}}
QLabel#Heading {{
    font-size: 17px;
    font-weight: 600;
    color: {text};
}}
QLabel#TitrePage {{
    font-size: 22px;
    font-weight: 700;
    color: {accent_text};
}}
QLabel#TitreAccueil {{
    font-size: 34px;
    font-weight: 700;
    color: {accent_text};
}}

QListWidget {{
    border: none;
    background: transparent;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: 8px;
    margin: 1px 0;
    color: {header_text};
}}
QListWidget::item:selected {{
    background-color: {selection_bg};
    color: {selection_text};
    font-weight: 600;
}}
QListWidget::item:hover:!selected {{
    background-color: {list_hover_bg};
}}

QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {btn_hover_border};
    border-radius: 4px;
    background-color: {input_bg};
}}
QCheckBox::indicator:hover {{
    border-color: {focus_border};
}}
QCheckBox::indicator:checked {{
    background-color: {primary_bg};
    border-color: {primary_bg};
}}

QPushButton#BoutonAccueil {{
    text-align: left;
    background-color: transparent;
    border: none;
    border-bottom: 1px solid {card_border};
    border-radius: 0px;
    padding: 8px 4px 12px 4px;
    font-weight: 600;
    color: {text};
}}
QPushButton#BoutonAccueil:hover {{
    color: {accent_text};
}}
QPushButton#BoutonAccueil:checked {{
    color: {accent_text};
    border-bottom: 2px solid {accent_text};
}}

QAbstractButton#ToggleTheme {{
    background-color: transparent;
    border: 1px solid {btn_border};
    border-radius: 17px;
    font-size: 15px;
    padding: 0px;
}}
QAbstractButton#ToggleTheme:hover {{
    background-color: {btn_hover_bg};
    border-color: {btn_hover_border};
}}
QToolButton#ToggleTheme::menu-indicator {{
    image: none;
    width: 0px;
}}

QMenu {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-radius: 8px;
    padding: 4px;
}}
QMenu::item {{
    padding: 6px 16px;
    border-radius: 6px;
    color: {text};
}}
QMenu::item:selected {{
    background-color: {selection_bg};
    color: {selection_text};
}}
QMenu::separator {{
    height: 1px;
    background: {card_border};
    margin: 4px 8px;
}}

QLabel#SectionSidebar {{
    color: {muted};
    font-size: 11px;
    font-weight: 700;
    padding: 4px 2px 2px 2px;
}}

QLabel#Breadcrumb {{
    color: {muted};
    font-size: 12px;
    padding: 10px 20px;
    border-bottom: 1px solid {card_border};
}}

QPushButton#CarteModule {{
    background-color: {card_bg};
    border: 1px solid {card_border};
    border-top: 3px solid """ + ACCENT_BLEU + """;
    border-radius: 12px;
    font-size: 16px;
    font-weight: 700;
    color: {text};
}}
QPushButton#CarteModule:hover {{
    background-color: {card_hover_bg};
    border-left-color: """ + ACCENT_BLEU + """;
    border-right-color: """ + ACCENT_BLEU + """;
    border-bottom-color: """ + ACCENT_BLEU + """;
}}

QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {scrollbar_handle};
    border-radius: 5px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {scrollbar_handle_hover};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
    margin: 0;
}}
QScrollBar::handle:horizontal {{
    background: {scrollbar_handle};
    border-radius: 5px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {scrollbar_handle_hover};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}

QToolTip {{
    background-color: {tooltip_bg};
    color: {tooltip_text};
    border: 1px solid {card_border};
    padding: 4px 6px;
}}
"""


def stylesheet(name: str) -> str:
    return _TEMPLATE.format(**PALETTES[name])


def palette(name: str | None = None) -> dict:
    """Palette du thème donné, ou du thème actif si non précisé."""
    return PALETTES[name or ThemeManager.instance().name]


def qcolor(cle: str, name: str | None = None) -> QColor:
    """Raccourci pour obtenir une couleur de la palette active directement en QColor —
    pratique pour les widgets qui peignent eux-mêmes (QPainter) au lieu de passer par QSS."""
    return QColor(palette(name)[cle])


class ThemeManager(QObject):
    """Point d'accès unique au thème actif. Toute l'appli partage la même instance
    (voir `instance()`) afin qu'un changement de thème déclenché depuis n'importe
    quel bouton (accueil ou barre latérale d'un module) se propage partout."""

    changed = Signal(str)  # émis avec le nom du nouveau thème ("light" / "dark")

    _instance: "ThemeManager | None" = None

    def __init__(self):
        super().__init__()
        self._name = "light"

    @classmethod
    def instance(cls) -> "ThemeManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @property
    def name(self) -> str:
        return self._name

    def load(self, conn) -> None:
        """Au démarrage : applique la préférence enregistrée (rien n'écoute encore
        `changed` à ce stade, donc pas besoin de l'émettre)."""
        self._name = database.get_theme_preference(conn)
        self._appliquer()

    def set(self, name: str, conn=None) -> None:
        if name not in PALETTES or name == self._name:
            return
        self._name = name
        self._appliquer()
        if conn is not None:
            database.set_theme_preference(conn, name)
        self.changed.emit(self._name)

    def toggle(self, conn=None) -> None:
        self.set("dark" if self._name == "light" else "light", conn)

    def _appliquer(self) -> None:
        app = QApplication.instance()
        if app is not None:
            app.setStyleSheet(stylesheet(self._name))
