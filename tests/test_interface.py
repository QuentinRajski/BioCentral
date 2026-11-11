"""
Test de fumée de l'interface : ouvre chaque module, charge les données de
démonstration et les exemples, change de thème et de période. Ne vérifie pas
le rendu au pixel près, mais attrape les plantages et erreurs Python dans les
écrans (exécuté sans fenêtre visible : QT_QPA_PLATFORM=offscreen).
"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from tests.outils import TestAvecBase

_app = QApplication.instance() or QApplication(sys.argv[:1])


class TestInterface(TestAvecBase):
    def setUp(self):
        super().setUp()
        self.erreurs = []
        self._ancien_hook = sys.excepthook
        sys.excepthook = lambda t, v, tb: self.erreurs.append(v)   # exceptions levées dans les slots Qt
        from core import theme, ui
        theme.ThemeManager.instance().load(self.conn)
        self._boites = {n: getattr(ui, n) for n in ("information", "alerte", "erreur", "confirmer")}
        for nom in ("information", "alerte", "erreur"):
            setattr(ui, nom, lambda *a, **k: None)
        ui.confirmer = lambda *a, **k: True
        from main import MainWindow
        self.fenetre = MainWindow(self.conn)
        self.fenetre.resize(1400, 900)
        self.fenetre.show()
        _app.processEvents()

    def tearDown(self):
        from core import ui
        for nom, f in self._boites.items():
            setattr(ui, nom, f)
        self.fenetre.close()
        self.fenetre.deleteLater()
        _app.processEvents()
        sys.excepthook = self._ancien_hook
        super().tearDown()

    def test_parcours_complet(self):
        from core import theme
        w = self.fenetre
        for module in ("qualite", "ciq", "validation"):
            w._ouvrir_module(module)
            _app.processEvents()

        ciq = w.modules["ciq"]
        ciq._charger_demo()
        _app.processEvents()
        vue = ciq.contenu.currentWidget()
        self.assertGreater(vue.journal.rowCount(), 50)
        vue.periode.setCurrentIndex(4)
        vue.case_inactifs.setChecked(True)
        vue._selectionner_mesure(vue.cartes[0].mesures[-1].id)
        _app.processEvents()

        validation = w.modules["validation"]
        validation.comparaison._charger_exemple()
        self.assertIsNotNone(validation.comparaison.analyse)
        validation.comparaison.enregistrer()
        validation.fidelite._charger_exemple()
        validation.fidelite.enregistrer()
        self.assertEqual(validation.liste.count(), 2)
        validation._ouvrir_etude(validation.liste.item(0))
        validation._afficher(validation.incertitude)
        validation.incertitude.champ_cv.setText("2.5")
        validation.incertitude.calculer()
        self.assertIsNotNone(validation.incertitude.resultat)

        theme.ThemeManager.instance().toggle(self.conn)
        _app.processEvents()
        theme.ThemeManager.instance().toggle(self.conn)
        w._retour_accueil()
        _app.processEvents()
        self.assertEqual(self.erreurs, [])
