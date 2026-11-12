"""
Point d'entrée de l'application. Lance la fenêtre principale sur la page d'accueil,
et bascule vers le module choisi via un QStackedWidget — voir la conversation de
conception pour le détail de cette architecture (coquille + modules indépendants).
"""
import sys
import logging
from pathlib import Path

# Doit être importé avant PySide6 : sur certaines machines (conflit de DLL Windows
# entre Qt et le runtime CUDA/MKL de PyTorch), charger Qt en premier fait planter
# (accès mémoire invalide) tout chargement ultérieur de sentence-transformers dans
# le module Base de connaissances. Importer torch ici, une seule fois, avant Qt,
# fixe l'ordre de chargement des DLL pour toute la durée du processus.
#
# v2 : cet import est devenu facultatif. Sans PyTorch installé, l'application
# démarre quand même (en v1 elle plantait au lancement) ; seul le module Base de
# connaissances est alors indisponible, avec un message explicite.
try:
    import torch  # noqa: F401
except Exception:  # ImportError, ou DLL manquante / incompatible
    torch = None

from PySide6.QtWidgets import QApplication, QMainWindow, QStackedWidget, QMessageBox
from PySide6.QtGui import QIcon, QGuiApplication
from PySide6.QtCore import Qt

from core import database
from core import theme
from core.chemins import ressource
from core.logs import configurer_logs, installer_gestionnaire_erreurs_global, LOG_PATH
from home import HomePage
from modules.qualite.shell import QualiteModule
from modules.ciq.shell import CIQModule
from modules.validation.shell import ValidationModule
from modules.connaissances.shell import ConnaissancesModule

ICON_PATH = ressource("assets", "icon.ico" if sys.platform == "win32" else "icon.png")


def _corriger_icone_barre_des_taches_windows():
    """Tant que l'appli tourne via 'python main.py' (pas encore empaquetée en .exe),
    Windows affiche l'icône de l'interpréteur Python dans la barre des tâches au lieu
    de la nôtre. Lui donner un identifiant d'application propre corrige ça. Une fois
    empaquetée avec PyInstaller (--icon=assets/icon.ico), l'exécutable aura de toute
    façon sa propre icône et cet appel devient superflu mais reste inoffensif."""
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("biocentral.qualite.app")
        except Exception:
            pass


def _dimensionner_fenetre(window: QMainWindow) -> None:
    """Taille et taille minimale calculées à partir de l'écran réel du poste, pas de
    valeurs fixes : sur un petit écran (portable), la fenêtre restaurée (touche
    « rétablir ») ne dépasse jamais l'espace disponible ; sur un grand écran, elle
    ne reste pas plaquée à une taille ridiculement petite. L'application s'ouvre de
    toute façon maximisée par défaut (voir main()) : ceci ne joue que lorsque
    l'utilisateur quitte le plein écran."""
    ecran = QGuiApplication.primaryScreen()
    disponible = ecran.availableGeometry() if ecran else None
    if disponible is None:
        window.resize(1200, 800)
        return
    largeur = min(1200, int(disponible.width() * 0.85))
    hauteur = min(800, int(disponible.height() * 0.85))
    window.resize(largeur, hauteur)
    window.setMinimumSize(min(1000, disponible.width()), min(650, disponible.height()))


class MainWindow(QMainWindow):
    def __init__(self, conn):
        super().__init__()
        self.setWindowTitle("BioCentral")
        _dimensionner_fenetre(self)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.home = HomePage(conn)
        self.home.module_selected.connect(self._ouvrir_module)
        self.home.demande_fermeture.connect(self._fermer_apres_import)
        self.stack.addWidget(self.home)

        self.modules = {}
        self.conn = conn

    MODULES_DISPONIBLES = {
        "qualite": QualiteModule,
        "ciq": CIQModule,
        "validation": ValidationModule,
        "connaissances": ConnaissancesModule,
    }

    def _ouvrir_module(self, module_id: str):
        if module_id not in self.modules:
            classe_module = self.MODULES_DISPONIBLES.get(module_id)
            if classe_module is None:
                return  # futur module non encore implémenté
            if module_id == "connaissances" and torch is None:
                QMessageBox.warning(
                    self, "Module indisponible",
                    "La Base de connaissances nécessite PyTorch et sentence-transformers, qui ne sont pas "
                    "installés (ou pas chargeables) sur ce poste.\n\n"
                    "Installez-les avec : pip install -r requirements.txt\n\n"
                    "Les autres modules fonctionnent normalement.")
                return
            module_widget = classe_module(self.conn)
            module_widget.retour_accueil.connect(self._retour_accueil)
            self.modules[module_id] = module_widget
            self.stack.addWidget(module_widget)
        self.stack.setCurrentWidget(self.modules[module_id])

    def _retour_accueil(self):
        self.stack.setCurrentWidget(self.home)

    def _fermer_apres_import(self):
        QApplication.instance().quit()


def main():
    configurer_logs()
    installer_gestionnaire_erreurs_global()
    _corriger_icone_barre_des_taches_windows()

    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setStyleSheet(theme.stylesheet("light"))  # thème par défaut, avant de connaître la préférence enregistrée
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))

    try:
        conn = database.get_connection()
    except Exception:
        logging.exception("Échec au tout premier démarrage (connexion à la base)")
        QMessageBox.critical(
            None, "Impossible de démarrer",
            "BioCentral n'a pas pu accéder à sa base de données.\n\n"
            f"Détails enregistrés dans :\n{LOG_PATH}\n\n"
            "Transmettez ce fichier pour obtenir de l'aide.",
        )
        sys.exit(1)

    theme.ThemeManager.instance().load(conn)
    database.sauvegarde_quotidienne(conn)  # ne lève jamais : un échec est seulement consigné dans le log

    window = MainWindow(conn)
    if ICON_PATH.exists():
        window.setWindowIcon(QIcon(str(ICON_PATH)))
    window.showMaximized()

    if "--autotest" in sys.argv:
        _programmer_autotest(app, window)
    sys.exit(app.exec())


def _programmer_autotest(app: QApplication, window: "MainWindow") -> None:
    """
    `BioCentral --autotest` : ouvre chaque module puis quitte, avec le code de
    sortie 0 si aucune erreur n'est survenue (1 sinon). Sert à vérifier un
    exécutable fraîchement construit, sur Windows comme sur Mac (intégration
    continue), sans clic humain. Le résultat est aussi écrit dans le log.
    """
    from PySide6.QtCore import QTimer
    erreurs: list[str] = []

    def noter(type_exc, valeur, tb):
        import traceback
        erreurs.append("".join(traceback.format_exception(type_exc, valeur, tb)))
        logging.error("Autotest — erreur :\n%s", erreurs[-1])

    sys.excepthook = noter  # pas de boîte de dialogue bloquante pendant l'autotest

    def parcourir():
        modules = [m for m in MainWindow.MODULES_DISPONIBLES if m != "connaissances" or torch is not None]
        for module_id in modules:
            try:
                window._ouvrir_module(module_id)
                app.processEvents()
                window._retour_accueil()
                app.processEvents()
            except Exception:
                noter(*sys.exc_info())
        try:
            _autotest_calculs_et_exports(window)
        except Exception:
            noter(*sys.exc_info())
        logging.info("Autotest : %d module(s) ouverts, %d erreur(s)", len(modules), len(erreurs))
        print(f"AUTOTEST {'OK' if not erreurs else 'ECHEC'} : {len(modules)} modules, {len(erreurs)} erreur(s)",
              flush=True)
        app.exit(1 if erreurs else 0)

    QTimer.singleShot(1500, parcourir)


def _autotest_calculs_et_exports(window: "MainWindow") -> None:
    """Sollicite scipy, numpy, openpyxl et l'écriture PDF de Qt : ce sont les parties
    qu'un empaquetage incomplet casse en premier. N'écrit rien dans la base de
    données (fichiers dans un dossier temporaire supprimé ensuite)."""
    import shutil
    import tempfile
    from core import comparaison_methodes, export, fidelite, intervalle_reference, westgard
    from modules.validation import logic as validation

    paires = validation.exemple_comparaison()
    analyse = comparaison_methodes.analyser([x for _, x, _ in paires], [y for _, _, y in paires])
    assert analyse.passing_bablok is not None and analyse.deming is not None
    serie = validation.exemple_fidelite()
    fidelite.composantes_variance({s: [v for s2, v in serie if s2 == s] for s, _ in serie})
    assert intervalle_reference.estimer(range(150)).ic_basse is not None
    assert westgard.evaluer([0.1, 2.5, 3.2])[-1]

    vue = window.modules["validation"].comparaison
    vue._charger_exemple()
    dossier = Path(tempfile.mkdtemp(prefix="biocentral_autotest_"))
    try:
        export.exporter_pdf(dossier / "test.pdf", "Autotest", "<p>Graphique</p>" + export.image_html("g.png"),
                            {"g.png": vue.plot_regression.image(600, 300)})
        export.exporter_excel(dossier / "test.xlsx", [("Test", ["x", "y"], [[1, 2.5]])])
        assert (dossier / "test.pdf").stat().st_size > 1000 and (dossier / "test.xlsx").exists()
        assert export.lire_tableau(dossier / "test.xlsx")[1] == [1, 2.5]
    finally:
        shutil.rmtree(dossier, ignore_errors=True)
        vue.nouvelle()


if __name__ == "__main__":
    main()
