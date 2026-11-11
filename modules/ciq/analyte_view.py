"""
Page d'un analyte : cartes de Levey-Jennings de chaque niveau, carte normalisée
multi-niveaux, statistiques de la période, journal des passages avec les règles
de Westgard déclenchées, notes, exports.
"""
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel, QMenu,
    QSplitter, QTableWidget, QTextEdit, QToolButton, QVBoxLayout, QWidget,
)

from core import export, theme, ui, westgard
from core.formatage import datetime_fr, fmt, fmt_dec
from core.plot import PlotWidget

from . import logic
from .carte import COULEUR_STATUT, dessiner_levey_jennings, dessiner_z_multiniveaux
from .dialogs import AnalyteDialog, CiblesDialog, LotDialog, MesureDialog, SaisieSerieDialog

PERIODES = [("30 derniers jours", 30), ("3 derniers mois", 91), ("6 derniers mois", 182),
            ("12 derniers mois", 365), ("Tout l'historique", None)]
LIBELLE_STATUT = {westgard.OK: "Conforme", westgard.ALERTE: "Alerte", westgard.REJET: "Rejet", "exclue": "Exclue"}
BADGE_STATUT = {westgard.OK: "ok", westgard.ALERTE: "alerte", westgard.REJET: "rejet", "exclue": "neutre"}
LIGNES_STATS = [
    ("n", "Nombre de passages non exclus sur la période."),
    ("Moyenne", "Moyenne observée sur la période."),
    ("Écart-type", "Écart-type observé sur la période."),
    ("CV %", "Coefficient de variation = écart-type / moyenne × 100 (imprécision)."),
    ("Biais % / cible", "Écart relatif entre la moyenne observée et la moyenne cible du lot."),
    ("Sigma", ""),
    ("Alertes", "Passages ayant déclenché uniquement des règles d'alerte (1-2s, 7T)."),
    ("Rejets", "Passages ayant déclenché au moins une règle de rejet."),
]
COLONNES_JOURNAL = ["Date", "Niveau", "Valeur", "z", "Règles", "Statut", "Opérateur", "Commentaire"]


class AnalyteView(QWidget):
    modifie = Signal()      # nom/automate changé ou analyte supprimé : la coquille rafraîchit sa liste
    supprime = Signal()

    def __init__(self, conn, analyte_id: int):
        super().__init__()
        self.conn = conn
        self.analyte_id = analyte_id
        self.analyte = logic.get_analyte(conn, analyte_id)
        self.cartes: list[logic.CarteLot] = []
        self.plots: dict[int, PlotWidget] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 16, 24, 16)
        root.setSpacing(12)

        # --- En-tête ---
        entete = QHBoxLayout()
        self.titre = ui.titre_page("")
        entete.addWidget(self.titre)
        self.badge_global = ui.badge("", "neutre")
        entete.addWidget(self.badge_global)
        entete.addStretch()
        entete.addWidget(ui.bouton("+ Saisir un passage", self._saisir, principal=True))
        entete.addWidget(ui.bouton("Saisie en série / import…", self._saisie_serie))
        self.btn_menu = QToolButton()
        self.btn_menu.setObjectName("ToggleTheme")
        self.btn_menu.setFixedSize(34, 34)
        self.btn_menu.setText("⚙")
        self.btn_menu.setToolTip("Réglages et exports")
        self.btn_menu.setCursor(Qt.PointingHandCursor)
        self.btn_menu.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(self.btn_menu)
        menu.addAction("✎ Modifier l'analyte et ses règles…", self._modifier_analyte)
        menu.addAction("+ Ajouter un lot de contrôle…", self._ajouter_lot)
        menu.addSeparator()
        menu.addAction("⬇ Rapport PDF de la période…", self._exporter_pdf)
        menu.addAction("⬇ Données de la période (Excel)…", self._exporter_excel)
        menu.addSeparator()
        menu.addAction("🗑 Supprimer cet analyte…", self._supprimer_analyte)
        self.btn_menu.setMenu(menu)
        entete.addWidget(self.btn_menu)
        root.addLayout(entete)

        # --- Filtres ---
        filtres = QHBoxLayout()
        self.sous_titre = ui.texte_discret("", retour_ligne=False)
        filtres.addWidget(self.sous_titre)
        filtres.addStretch()
        filtres.addWidget(ui.texte_discret("Période", retour_ligne=False))
        self.periode = QComboBox()
        for libelle, jours in PERIODES:
            self.periode.addItem(libelle, jours)
        self.periode.setCurrentIndex(1)
        self.periode.currentIndexChanged.connect(self.rafraichir)
        filtres.addWidget(self.periode)
        self.case_inactifs = QCheckBox("Lots inactifs")
        self.case_inactifs.setToolTip("Afficher aussi les lots qui ne sont plus en cours d'utilisation")
        self.case_inactifs.toggled.connect(self.rafraichir)
        filtres.addWidget(self.case_inactifs)
        root.addLayout(filtres)

        # --- Corps : cartes (gauche) | journal + statistiques (droite) ---
        separateur = QSplitter(Qt.Horizontal)
        separateur.setChildrenCollapsible(False)

        self.colonne_cartes = QVBoxLayout()
        self.colonne_cartes.setContentsMargins(0, 0, 6, 0)
        self.colonne_cartes.setSpacing(12)
        conteneur_cartes = QWidget()
        conteneur_cartes.setLayout(self.colonne_cartes)
        separateur.addWidget(ui.zone_defilante(conteneur_cartes))

        droite = QWidget()
        colonne_droite = QVBoxLayout(droite)
        colonne_droite.setContentsMargins(6, 0, 0, 0)
        colonne_droite.setSpacing(10)

        carte_stats, layout_stats = ui.carte_titree("Statistiques de la période")
        # Une colonne par niveau, une ligne par indicateur : reste lisible dans une colonne étroite.
        self.table_stats = QTableWidget(len(LIGNES_STATS), 1)
        ui.styliser_table(self.table_stats, 28)
        self.table_stats.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table_stats.setSelectionMode(QAbstractItemView.NoSelection)
        self.table_stats.setFocusPolicy(Qt.NoFocus)
        layout_stats.addWidget(self.table_stats)
        layout_stats.addWidget(ui.texte_discret(
            "Biais : moyenne observée vs moyenne cible. Sigma = (ETa − |biais|) / CV, si une erreur totale "
            "admissible est renseignée pour l'analyte."))
        colonne_droite.addWidget(carte_stats)

        carte_journal, layout_journal = ui.carte_titree("Journal des passages (clic droit : exclure, modifier, supprimer)")
        self.journal = QTableWidget(0, len(COLONNES_JOURNAL))
        self.journal.setHorizontalHeaderLabels(COLONNES_JOURNAL)
        ui.styliser_table(self.journal, 30)
        self.journal.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.journal.horizontalHeader().setSectionResizeMode(len(COLONNES_JOURNAL) - 1, QHeaderView.Stretch)
        self.journal.setSelectionMode(QAbstractItemView.SingleSelection)
        self.journal.setContextMenuPolicy(Qt.CustomContextMenu)
        self.journal.customContextMenuRequested.connect(self._menu_journal)
        self.journal.itemDoubleClicked.connect(lambda _: self._modifier_mesure_selectionnee())
        self.journal.itemSelectionChanged.connect(self._sur_selection_journal)
        layout_journal.addWidget(self.journal, 1)
        colonne_droite.addWidget(carte_journal, 1)

        carte_regles, layout_regles = ui.carte_titree("Règles actives")
        self.label_regles = ui.texte_discret()
        layout_regles.addWidget(self.label_regles)
        colonne_droite.addWidget(carte_regles)

        carte_notes, layout_notes = ui.carte_titree("Notes (actions correctives, changements de réactif…)")
        self.notes = QTextEdit()
        self.notes.setFixedHeight(80)
        self.notes.setPlaceholderText("Enregistré automatiquement.")
        self.notes.setPlainText(self.analyte.notes if self.analyte else "")
        self._minuteur_notes = QTimer(self)
        self._minuteur_notes.setSingleShot(True)
        self._minuteur_notes.timeout.connect(
            lambda: logic.enregistrer_notes(self.conn, self.analyte_id, self.notes.toPlainText()))
        self.notes.textChanged.connect(lambda: self._minuteur_notes.start(600))
        layout_notes.addWidget(self.notes)
        colonne_droite.addWidget(carte_notes)

        # Colonne de droite défilante : sur un écran avec mise à l'échelle 125-150 %,
        # ses cartes ne tiennent pas toutes en hauteur et se chevauchaient.
        self.journal.setMinimumHeight(300)
        zone_droite = ui.zone_defilante(droite)
        separateur.addWidget(zone_droite)
        separateur.setStretchFactor(0, 3)
        separateur.setStretchFactor(1, 2)
        separateur.widget(0).setMinimumWidth(420)
        zone_droite.setMinimumWidth(380)
        # Répartition initiale 60/40 (sinon Qt part des tailles « idéales » des
        # tableaux, très larges, et écrase les cartes de contrôle).
        separateur.setSizes([600, 400])
        root.addWidget(separateur, 1)

        theme.ThemeManager.instance().changed.connect(self._sur_theme)
        self.rafraichir()

    # ------------------------------------------------------------------
    def _periode(self) -> tuple[str | None, str | None]:
        return logic.debut_periode(self.periode.currentData()), None

    def _lots_affiches(self) -> list[logic.Lot]:
        return logic.lister_lots(self.conn, self.analyte_id, actifs_seulement=not self.case_inactifs.isChecked())

    def _sur_theme(self, _nom=None):
        self.rafraichir()

    def rafraichir(self):
        self.analyte = logic.get_analyte(self.conn, self.analyte_id)
        if self.analyte is None:
            return
        a = self.analyte
        self.titre.setText(a.nom)
        details = [d for d in (a.automate, a.unite and f"unité : {a.unite}",
                               a.erreur_totale_admissible is not None and f"ETa : {fmt(a.erreur_totale_admissible)} %")
                   if d]
        self.sous_titre.setText(" · ".join(details))
        self.label_regles.setText("  ·  ".join(
            f"{westgard.REGLES[c].libelle} ({'rejet' if westgard.REGLES[c].gravite == westgard.REJET else 'alerte'})"
            for c in a.regles))
        self.label_regles.setToolTip("\n".join(f"{westgard.REGLES[c].libelle} : {westgard.REGLES[c].description}"
                                               for c in a.regles))

        debut, fin = self._periode()
        lots = self._lots_affiches()
        self.cartes = logic.calculer_cartes(self.conn, a, lots, debut, fin)
        self._remplir_cartes(debut, fin)
        self._remplir_stats()
        self._remplir_journal(debut, fin)
        self._mettre_a_jour_badge()

    def _mettre_a_jour_badge(self):
        """Statut de la dernière série : rejet si un niveau du dernier jour de passage est en rejet."""
        dernieres = [c.mesures[-1] for c in self.cartes if c.mesures]
        if not dernieres:
            ui.definir_badge(self.badge_global, "Aucun passage", "neutre")
            return
        jour = max(m.date for m in dernieres)[:10]
        du_jour = [m for c in self.cartes for m in c.mesures if m.date[:10] == jour and not m.exclue]
        statuts = {m.statut for m in du_jour}
        statut = westgard.REJET if westgard.REJET in statuts else westgard.ALERTE if westgard.ALERTE in statuts else westgard.OK
        texte = {westgard.OK: "Dernière série conforme", westgard.ALERTE: "Dernière série : alerte",
                 westgard.REJET: "Dernière série REJETÉE"}[statut]
        ui.definir_badge(self.badge_global, f"{texte} ({datetime_fr(jour)})", BADGE_STATUT[statut])

    def _remplir_cartes(self, debut, fin):
        ui.vider_layout(self.colonne_cartes)
        self.plots = {}
        if not self.cartes:
            vide = ui.carte_titree("")[0]
            layout = vide.layout()
            layout.addWidget(ui.sous_titre("Aucun lot de contrôle pour cet analyte"))
            layout.addWidget(ui.texte_discret(
                "Ajoutez un lot (un par niveau de concentration) pour commencer à saisir des passages."))
            layout.addWidget(ui.bouton("+ Ajouter un lot de contrôle", self._ajouter_lot, principal=True),
                             alignment=Qt.AlignLeft)
            self.colonne_cartes.addWidget(vide)
            self.colonne_cartes.addStretch()
            return

        if len(self.cartes) > 1:
            carte_z, layout_z = ui.carte_titree("Tous les niveaux — scores z (écart à la cible en écarts-types)",
                                                "CardAccentViolet")
            plot_z = PlotWidget()
            plot_z.setMinimumHeight(230)
            dessiner_z_multiniveaux(plot_z, self.cartes, debut, fin)
            plot_z.point_clique.connect(self._selectionner_mesure)
            layout_z.addWidget(plot_z)
            self.colonne_cartes.addWidget(carte_z)
            self.plots[-1] = plot_z

        unite = self.analyte.unite
        for carte in self.cartes:
            lot = carte.lot
            if carte.moyenne is None:
                cible = "cibles non définies — au moins deux passages sont nécessaires"
            else:
                cible = f"{'cible provisoire' if carte.cibles_provisoires else 'cible'} {fmt(carte.moyenne)} ± {fmt(carte.ecart_type)} {unite}"
                if lot.origine_cible and not carte.cibles_provisoires:
                    cible += f" ({lot.origine_cible.lower()})"
            titre = f"{lot.libelle} — {cible}" + ("" if lot.actif else "  [lot inactif]")
            accent = "CardAccentBleu" if lot.actif else "Card"
            bloc, layout = ui.carte_titree(titre, accent)
            liens = QHBoxLayout()
            liens.setSpacing(4)
            for texte, action in (("Modifier le lot", lambda _=False, l=lot: self._modifier_lot(l)),
                                  ("Établir les cibles à partir des données", lambda _=False, l=lot: self._etablir_cibles(l)),
                                  ("Supprimer le lot", lambda _=False, l=lot: self._supprimer_lot(l))):
                lien = ui.bouton(texte, action)
                lien.setObjectName("LienDiscret")
                lien.setCursor(Qt.PointingHandCursor)
                liens.addWidget(lien)
            liens.addStretch()
            if carte.cibles_provisoires and carte.moyenne is not None:
                liens.addWidget(ui.badge("Cibles provisoires", "alerte"))
            layout.addLayout(liens)
            plot = PlotWidget()
            plot.setMinimumHeight(250)
            dessiner_levey_jennings(plot, carte, unite, debut, fin)
            plot.point_clique.connect(self._selectionner_mesure)
            layout.addWidget(plot)
            self.colonne_cartes.addWidget(bloc)
            self.plots[lot.id] = plot
        self.colonne_cartes.addWidget(ui.texte_discret(
            "Points : bleu = conforme · orange = alerte (1-2s, 7T) · rouge = rejet · creux = mesure exclue. "
            "Survolez un point pour son détail, cliquez-le pour le retrouver dans le journal."))
        self.colonne_cartes.addStretch()

    def _remplir_stats(self):
        self.table_stats.setColumnCount(len(self.cartes) + 1)
        self.table_stats.setHorizontalHeaderLabels(["Indicateur"] + [c.lot.niveau for c in self.cartes])
        self.table_stats.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        for ligne, (libelle, infobulle) in enumerate(LIGNES_STATS):
            fond = ui.couleur_ligne(ligne)
            self.table_stats.setItem(ligne, 0, ui.cellule(libelle, fond=fond, infobulle=infobulle))
            for col, carte in enumerate(self.cartes, start=1):
                s = carte.stats
                valeurs = {
                    "n": str(s.n), "Moyenne": fmt(s.moyenne), "Écart-type": fmt(s.ecart_type),
                    "CV %": fmt_dec(s.cv, 2),
                    "Biais % / cible": fmt_dec(s.biais_pourcent, 2) if s.biais_pourcent is not None else "—",
                    "Sigma": fmt_dec(s.sigma, 1), "Alertes": str(s.n_alertes), "Rejets": str(s.n_rejets),
                }
                texte = valeurs[libelle]
                info = _interpretation_sigma(s.sigma) if libelle == "Sigma" else infobulle
                surligne = (libelle == "Rejets" and s.n_rejets > 0) or (
                    libelle == "Sigma" and s.sigma is not None and s.sigma < 3)
                self.table_stats.setItem(ligne, col, ui.cellule(
                    texte, droite=True, infobulle=info, fond=ui.couleur_ligne(ligne, surlignee=surligne)))
        ui.ajuster_hauteur_table(self.table_stats)

    def _mesures_periode(self, debut, fin) -> list[tuple[logic.Mesure, logic.CarteLot]]:
        lignes = [(m, c) for c in self.cartes for m in c.mesures if logic.dans_periode(m.date, debut, fin)]
        lignes.sort(key=lambda mc: (mc[0].date, mc[0].id), reverse=True)
        return lignes

    def _remplir_journal(self, debut, fin):
        lignes = self._mesures_periode(debut, fin)
        self.journal.setSortingEnabled(False)
        self.journal.setRowCount(len(lignes))
        for i, (m, carte) in enumerate(lignes):
            statut = m.statut
            fond = ui.couleur_ligne(i, surlignee=statut == westgard.REJET, avertissement=statut == westgard.ALERTE)
            couleur_statut = theme.qcolor(COULEUR_STATUT[statut]) if statut != westgard.OK else None
            infobulle = "\n".join(f"{westgard.REGLES[c].libelle} : {westgard.REGLES[c].description}"
                                  for c in m.regles if c in westgard.REGLES)
            cellules = [
                ui.cellule(datetime_fr(m.date), m.date, fond=fond, donnee=m.id),
                ui.cellule(carte.lot.niveau, fond=fond),
                ui.cellule(fmt(m.valeur), m.valeur, droite=True, fond=fond),
                ui.cellule(f"{m.z:+.2f}" if m.z is not None else "—", m.z if m.z is not None else 0, droite=True, fond=fond),
                ui.cellule(westgard.libelles(m.regles), fond=fond, infobulle=infobulle),
                ui.cellule(LIBELLE_STATUT[statut], fond=fond, couleur=couleur_statut),
                ui.cellule(m.operateur, fond=fond),
                ui.cellule(m.commentaire, fond=fond, infobulle=m.commentaire),
            ]
            for col, item in enumerate(cellules):
                self.journal.setItem(i, col, item)
        self.journal.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Journal : sélection et menu contextuel
    # ------------------------------------------------------------------
    def _mesure_selectionnee(self) -> logic.Mesure | None:
        ligne = self.journal.currentRow()
        if ligne < 0 or self.journal.item(ligne, 0) is None:
            return None
        mesure_id = self.journal.item(ligne, 0).data(Qt.UserRole)
        for carte in self.cartes:
            for m in carte.mesures:
                if m.id == mesure_id:
                    return m
        return None

    def _sur_selection_journal(self):
        m = self._mesure_selectionnee()
        for plot in self.plots.values():
            plot.selectionner(m.id if m else None)

    def _selectionner_mesure(self, mesure_id):
        for ligne in range(self.journal.rowCount()):
            item = self.journal.item(ligne, 0)
            if item is not None and item.data(Qt.UserRole) == mesure_id:
                self.journal.selectRow(ligne)
                self.journal.scrollToItem(item, QAbstractItemView.PositionAtCenter)
                return

    def _menu_journal(self, position):
        m = self._mesure_selectionnee()
        if m is None:
            return
        menu = QMenu(self)
        if m.exclue:
            menu.addAction("↩ Réintégrer dans les calculs", lambda: self._exclure(m, False))
        else:
            menu.addAction("⊘ Exclure des calculs…", lambda: self._exclure(m, True))
        menu.addAction("✎ Modifier…", self._modifier_mesure_selectionnee)
        menu.addSeparator()
        menu.addAction("🗑 Supprimer…", lambda: self._supprimer_mesure(m))
        menu.exec(self.journal.viewport().mapToGlobal(position))

    def _exclure(self, m: logic.Mesure, exclure: bool):
        motif = None
        if exclure:
            motif, ok = QInputDialog.getText(
                self, "Exclure la mesure",
                "Motif de l'exclusion (conservé pour la traçabilité) :", text=m.commentaire)
            if not ok:
                return
        logic.definir_exclusion(self.conn, m.id, exclure, motif)
        self.rafraichir()

    def _modifier_mesure_selectionnee(self):
        m = self._mesure_selectionnee()
        if m is None:
            return
        lots = [c.lot for c in self.cartes]
        if MesureDialog(self.conn, self.analyte, lots, m.lot_id, m, self).exec():
            self.rafraichir()

    def _supprimer_mesure(self, m: logic.Mesure):
        if ui.confirmer(self, "Supprimer la mesure",
                        f"Supprimer définitivement le passage du {datetime_fr(m.date)} ({fmt(m.valeur)}) ?\n\n"
                        "Pour écarter une mesure tout en gardant sa trace, préférez « Exclure des calculs ».",
                        "Supprimer", danger=True):
            logic.supprimer_mesure(self.conn, m.id)
            self.rafraichir()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _lots_pour_saisie(self) -> list[logic.Lot] | None:
        lots = logic.lister_lots(self.conn, self.analyte_id, actifs_seulement=True)
        if not lots:
            ui.alerte(self, "Aucun lot actif", "Ajoutez d'abord un lot de contrôle (menu ⚙ › Ajouter un lot).")
            return None
        return lots

    def _saisir(self):
        lots = self._lots_pour_saisie()
        if lots and MesureDialog(self.conn, self.analyte, lots, parent=self).exec():
            self.rafraichir()

    def _saisie_serie(self):
        lots = self._lots_pour_saisie()
        if not lots:
            return
        dialogue = SaisieSerieDialog(self.conn, self.analyte, lots, parent=self)
        if dialogue.exec():
            self.rafraichir()
            if dialogue.bilan and not dialogue.bilan.erreurs:
                ui.information(self, "Import terminé", f"{dialogue.bilan.n_importees} passage(s) importé(s).")

    def _modifier_analyte(self):
        if AnalyteDialog(self.conn, self.analyte, self).exec():
            self.rafraichir()
            self.modifie.emit()

    def _ajouter_lot(self):
        if LotDialog(self.conn, self.analyte, parent=self).exec():
            self.rafraichir()
            self.modifie.emit()

    def _modifier_lot(self, lot: logic.Lot):
        if LotDialog(self.conn, self.analyte, lot, self).exec():
            self.rafraichir()

    def _etablir_cibles(self, lot: logic.Lot):
        if CiblesDialog(self.conn, lot, self.analyte.unite, self).exec():
            self.rafraichir()

    def _supprimer_lot(self, lot: logic.Lot):
        n = len(logic.lister_mesures(self.conn, lot.id))
        if ui.confirmer(self, "Supprimer le lot",
                        f"Supprimer le lot « {lot.libelle} » et ses {n} passage(s) ?\n\nCette action est définitive. "
                        "Pour un lot épuisé ou périmé, préférez « Modifier le lot » et décochez « Lot en cours "
                        "d'utilisation » : son historique reste consultable.", "Supprimer", danger=True):
            logic.supprimer_lot(self.conn, lot.id)
            self.rafraichir()

    def _supprimer_analyte(self):
        if ui.confirmer(self, "Supprimer l'analyte",
                        f"Supprimer « {self.analyte.libelle} », tous ses lots et tous ses passages ?\n\n"
                        "Cette action est définitive (une sauvegarde automatique de la base est faite chaque jour).",
                        "Supprimer", danger=True):
            logic.supprimer_analyte(self.conn, self.analyte_id)
            self.supprime.emit()

    # ------------------------------------------------------------------
    # Exports
    # ------------------------------------------------------------------
    def _exporter_excel(self):
        chemin = ui.demander_fichier_enregistrement(self, "Exporter les passages", f"CIQ_{self.analyte.nom}.xlsx",
                                                    "Fichiers Excel (*.xlsx)")
        if not chemin:
            return
        debut, fin = self._periode()
        lignes = [[m.date, carte.lot.niveau, carte.lot.numero_lot, m.valeur,
                   round(m.z, 3) if m.z is not None else None, westgard.libelles(m.regles),
                   LIBELLE_STATUT[m.statut], m.operateur, m.commentaire]
                  for m, carte in reversed(self._mesures_periode(debut, fin))]
        stats = [[c.lot.libelle, c.moyenne, c.ecart_type, "provisoire" if c.cibles_provisoires else "définie",
                  c.stats.n, c.stats.moyenne, c.stats.ecart_type, c.stats.cv, c.stats.biais_pourcent, c.stats.sigma,
                  c.stats.n_alertes, c.stats.n_rejets] for c in self.cartes]
        try:
            export.exporter_excel(chemin, [
                ("Passages", ["Date", "Niveau", "Lot", "Valeur", "z", "Règles", "Statut", "Opérateur", "Commentaire"], lignes),
                ("Statistiques", ["Lot", "Moyenne cible", "Écart-type cible", "Cibles", "n", "Moyenne", "Écart-type",
                                  "CV %", "Biais %", "Sigma", "Alertes", "Rejets"], stats),
            ])
        except Exception as e:
            ui.erreur(self, "Échec de l'export", f"Impossible d'exporter : {e}")
            return
        ui.information(self, "Export terminé", f"Fichier enregistré : {chemin.name}")

    def _exporter_pdf(self):
        chemin = ui.demander_fichier_enregistrement(self, "Rapport CIQ", f"Rapport_CIQ_{self.analyte.nom}.pdf",
                                                    "Documents PDF (*.pdf)")
        if not chemin:
            return
        a = self.analyte
        debut, fin = self._periode()
        images, corps = {}, []
        corps.append(f"<p>{export.echapper(self.sous_titre.text())}<br>Période : "
                     f"{export.echapper(self.periode.currentText().lower())}"
                     + (f" (depuis le {datetime_fr(debut)})" if debut else "") + "<br>Règles actives : "
                     + export.echapper(westgard.libelles(a.regles)) + "</p>")
        corps.append("<h2>Statistiques</h2>")
        corps.append(export.table_html(
            ["Niveau", "Cible", "n", "Moyenne", "Écart-type", "CV %", "Biais %", "Sigma", "Alertes", "Rejets"],
            [[c.lot.libelle,
              (f"{fmt(c.moyenne)} ± {fmt(c.ecart_type)}" + (" (prov.)" if c.cibles_provisoires else "")) if c.moyenne is not None else "—",
              c.stats.n, fmt(c.stats.moyenne), fmt(c.stats.ecart_type), fmt_dec(c.stats.cv, 2),
              fmt_dec(c.stats.biais_pourcent, 2), fmt_dec(c.stats.sigma, 1), c.stats.n_alertes,
              (c.stats.n_rejets, "rejet" if c.stats.n_rejets else "")] for c in self.cartes],
            alignement_droite={2, 3, 4, 5, 6, 7, 8, 9}))
        corps.append("<h2>Cartes de contrôle</h2>")
        for cle, plot in self.plots.items():
            nom = f"carte_{cle}.png"
            images[nom] = plot.image(900, 330)
            libelle = "Tous les niveaux (scores z)" if cle == -1 else next(c.lot.libelle for c in self.cartes if c.lot.id == cle)
            corps.append(f"<p><b>{export.echapper(libelle)}</b></p>" + export.image_html(nom, 660))
        hors = [(m, c) for m, c in self._mesures_periode(debut, fin) if m.regles or m.exclue]
        corps.append("<h2>Passages en alerte, en rejet ou exclus</h2>")
        if hors:
            corps.append(export.table_html(
                ["Date", "Niveau", "Valeur", "z", "Règles", "Statut", "Commentaire"],
                [[datetime_fr(m.date), c.lot.niveau, fmt(m.valeur), f"{m.z:+.2f}" if m.z is not None else "—",
                  westgard.libelles(m.regles), (LIBELLE_STATUT[m.statut], m.statut if m.statut != "exclue" else ""),
                  m.commentaire] for m, c in hors], alignement_droite={2, 3}))
        else:
            corps.append("<p>Aucun passage en alerte ou en rejet sur la période.</p>")
        if a.notes:
            corps.append("<h2>Notes</h2><p>" + export.echapper(a.notes).replace("\n", "<br>") + "</p>")
        corps.append("<p class='note'>Visa du biologiste : ______________________ &nbsp;&nbsp; Date : ____________</p>")
        try:
            export.exporter_pdf(chemin, f"Contrôle interne de qualité — {a.nom}", "".join(corps), images,
                                sous_titre=a.automate)
        except Exception as e:
            ui.erreur(self, "Échec de l'export", f"Impossible de créer le PDF : {e}")
            return
        ui.information(self, "Rapport créé", f"Rapport enregistré : {chemin.name}")


def _interpretation_sigma(sigma: float | None) -> str:
    if sigma is None:
        return "Renseignez l'erreur totale admissible de l'analyte pour calculer le sigma."
    if sigma >= 6:
        return "≥ 6 sigma : performance de classe mondiale — une règle 1-3s avec 2 niveaux suffit."
    if sigma >= 4:
        return "4 à 6 sigma : bonne performance — règles 1-3s / 2-2s / R-4s recommandées."
    if sigma >= 3:
        return "3 à 4 sigma : performance limite — multi-règles complètes et contrôles plus fréquents."
    return "< 3 sigma : performance insuffisante — améliorer la méthode ; contrôle très strict nécessaire."
