"""
Feuille de style partagée par toute l'application (socle commun).
Objectif : rendu plat, moderne, professionnel — pas l'esthétique "tableur" par défaut de Qt.
"""

STYLESHEET = """
QWidget {
    background-color: #F7F6F2;
    color: #2C2C2A;
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 13px;
}

QLabel {
    background-color: transparent;
}

#Sidebar {
    background-color: #F1EFE8;
    border-right: 1px solid #E1DFD5;
}

QPushButton {
    background-color: #FFFFFF;
    border: 1px solid #D3D1C7;
    border-radius: 8px;
    padding: 7px 16px;
}
QPushButton:hover {
    background-color: #F1EFE8;
    border-color: #B8B6AB;
}
QPushButton:pressed {
    background-color: #E1DFD5;
}
QPushButton#PrimaryButton {
    background-color: #0C447C;
    color: #FFFFFF;
    border: none;
    font-weight: 600;
    padding: 8px 20px;
}
QPushButton#PrimaryButton:hover {
    background-color: #135A9E;
}

QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox {
    border: 1px solid #D3D1C7;
    border-radius: 8px;
    padding: 6px 10px;
    background-color: #FFFFFF;
    min-height: 20px;
}
QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #378ADD;
}
QComboBox::drop-down {
    border: none;
    width: 22px;
}
QComboBox QAbstractItemView {
    border: 1px solid #D3D1C7;
    border-radius: 8px;
    background-color: #FFFFFF;
    selection-background-color: #E6F1FB;
    selection-color: #0C447C;
    outline: none;
}

/* --- Tableaux : le plus gros du travail de modernisation --- */
QTableWidget {
    background-color: #FFFFFF;
    border: none;
    gridline-color: transparent;
    selection-background-color: #E6F1FB;
    selection-color: #0C447C;
}
QTableWidget::item {
    padding: 9px 12px;
    border-bottom: 1px solid #EDEBE2;
}
QHeaderView::section {
    background-color: transparent;
    color: #5F5E5A;
    border: none;
    border-bottom: 1px solid #D3D1C7;
    padding: 9px 12px;
    font-weight: 600;
    font-size: 12px;
}
QHeaderView::section:horizontal { border-right: none; }
QTableCornerButton::section {
    background-color: transparent;
    border: none;
}

#Card {
    background-color: #FFFFFF;
    border: 1px solid #E1DFD5;
    border-radius: 12px;
}

#CardAccentBleu {
    background-color: #FFFFFF;
    border: 1px solid #E1DFD5;
    border-top: 3px solid #378ADD;
    border-radius: 12px;
}
#CardAccentVert {
    background-color: #FFFFFF;
    border: 1px solid #E1DFD5;
    border-top: 3px solid #6B9E7C;
    border-radius: 12px;
}
#CardAccentViolet {
    background-color: #FFFFFF;
    border: 1px solid #E1DFD5;
    border-top: 3px solid #7F77DD;
    border-radius: 12px;
}
#CardAccentRose {
    background-color: #FFFFFF;
    border: 1px solid #E1DFD5;
    border-top: 3px solid #D4537E;
    border-radius: 12px;
}

#ModuleCard {
    background-color: #FFFFFF;
    border: 1px solid #E1DFD5;
    border-radius: 12px;
}
#ModuleCard:hover {
    border: 1px solid #378ADD;
}

QLabel#Muted {
    color: #8A887E;
    font-size: 12px;
}
QLabel#Heading {
    font-size: 17px;
    font-weight: 600;
    color: #2C2C2A;
}
QLabel#TitrePage {
    font-size: 22px;
    font-weight: 700;
    color: #0C447C;
}
QLabel#TitreAccueil {
    font-size: 34px;
    font-weight: 700;
    color: #0C447C;
}

QListWidget {
    border: none;
    background: transparent;
    outline: none;
}
QListWidget::item {
    padding: 8px 10px;
    border-radius: 8px;
    margin: 1px 0;
    color: #5F5E5A;
}
QListWidget::item:selected {
    background-color: #E6F1FB;
    color: #0C447C;
    font-weight: 600;
}
QListWidget::item:hover:!selected {
    background-color: #EDEBE2;
}

QCheckBox {
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border: 1px solid #B8B6AB;
    border-radius: 4px;
    background-color: #FFFFFF;
}
QCheckBox::indicator:hover {
    border-color: #378ADD;
}
QCheckBox::indicator:checked {
    background-color: #0C447C;
    border-color: #0C447C;
}

QPushButton#BoutonAccueil {
    text-align: left;
    background-color: transparent;
    border: none;
    border-bottom: 1px solid #E1DFD5;
    border-radius: 0px;
    padding: 8px 4px 12px 4px;
    font-weight: 600;
    color: #2C2C2A;
}
QPushButton#BoutonAccueil:hover {
    color: #0C447C;
}

QPushButton#CarteModule {
    background-color: #FFFFFF;
    border: 1px solid #E1DFD5;
    border-top: 3px solid #378ADD;
    border-radius: 12px;
    font-size: 15px;
    font-weight: 600;
    color: #2C2C2A;
}
QPushButton#CarteModule:hover {
    background-color: #F7FBFF;
    border-color: #378ADD;
}
"""
