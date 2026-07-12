-- Schéma SQLite — BioCentral
-- Une seule base pour toute l'application, partagée par tous les modules.
-- Convention : chaque module préfixe ses tables (ici "qc_" pour Contrôle Qualité)
-- afin qu'aucune collision ni interférence ne soit possible entre modules.
-- Chaque import est définitif : aucune mise à jour de ligne après insertion.

-- Métadonnées internes de l'application. Une ligne par module pour sa version de schéma,
-- afin que chaque module puisse migrer indépendamment des autres (ex. "qc_schema_version").
CREATE TABLE app_metadata (
    cle    TEXT PRIMARY KEY,
    valeur TEXT
);

-- ============================================================
-- Module Contrôle Qualité (préfixe qc_)
-- ============================================================

-- Un paramètre = un import (ex. "LH"). Nom détecté depuis la dernière colonne du fichier.
CREATE TABLE qc_parametres (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nom            TEXT NOT NULL UNIQUE,
    domaine_min    REAL,               -- domaine de mesure : borne basse (ex. 0.3 pour LH)
    domaine_max    REAL,               -- domaine de mesure : borne haute (ex. 250 pour LH)
    date_import    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fichier_source TEXT                -- nom du fichier Excel importé, pour traçabilité
);

-- Tranches d'âge définies par l'utilisateur à l'import, propres à chaque paramètre.
-- Communes aux deux sexes (le sexe est un filtre indépendant, pas une variante de tranche).
CREATE TABLE qc_tranches_age (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    parametre_id INTEGER NOT NULL REFERENCES qc_parametres(id) ON DELETE CASCADE,
    age_min      INTEGER NOT NULL,
    age_max      INTEGER NOT NULL,
    libelle      TEXT NOT NULL
);

-- Un échantillon = une ligne du fichier Excel importé (hors colonnes ignorées :
-- Patient, Corres., Docteur, et hors lignes de contrôle machine sans date de naissance).
CREATE TABLE qc_echantillons (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    parametre_id     INTEGER NOT NULL REFERENCES qc_parametres(id) ON DELETE CASCADE,
    numero_demande   TEXT NOT NULL,               -- identifiant affiché (jamais le nom du patient)
    sexe             TEXT NOT NULL CHECK (sexe IN ('Féminin','Masculin')),
    date_naissance   DATE NOT NULL,
    date_prelevement DATE NOT NULL,
    age_annees       INTEGER NOT NULL,             -- calculé une fois à l'import, figé
    tranche_age_id   INTEGER REFERENCES qc_tranches_age(id) ON DELETE CASCADE,

    valeur_affichee  TEXT NOT NULL,                -- texte exact d'origine : "4.8", "<0.3", "Res annulé"...
    valeur_numerique REAL,                         -- valeur utilisable en calcul (NULL si statut = 'exclu')
    statut           TEXT NOT NULL CHECK (statut IN ('valide','sous_seuil','sur_seuil','exclu'))
    -- valide      : résultat numérique normal -> inclus partout (n, moyenne, écart-type, médiane, percentiles)
    -- sous_seuil  : "<domaine_min" -> inclus dans n, médiane, percentiles (rang = domaine_min) ; exclu de moyenne/écart-type
    -- sur_seuil   : ">domaine_max" -> même règle que sous_seuil, côté haut
    -- exclu       : "Res annulé", "VCOM" -> absent de tous les calculs, y compris n (conservé en base uniquement pour traçabilité)
);

CREATE INDEX idx_qc_echantillons_parametre ON qc_echantillons(parametre_id);
CREATE INDEX idx_qc_echantillons_tranche   ON qc_echantillons(tranche_age_id);
CREATE INDEX idx_qc_echantillons_sexe      ON qc_echantillons(sexe);

INSERT INTO app_metadata (cle, valeur) VALUES ('qc_schema_version', '1');

-- ============================================================
-- Futurs modules : suivre le même principe, ex. pour un module "modx" :
--   CREATE TABLE modx_xxx (...);
--   INSERT INTO app_metadata (cle, valeur) VALUES ('modx_schema_version', '1');
-- ============================================================
