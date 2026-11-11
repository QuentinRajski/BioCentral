-- Schéma SQLite — BioCentral
-- Une seule base pour toute l'application, partagée par tous les modules.
-- Convention : chaque module préfixe ses tables afin qu'aucune collision ni
-- interférence ne soit possible entre modules :
--   qc_   Études de population (historiquement « Contrôle qualité »)
--   ciq_  Contrôle interne de qualité (Levey-Jennings, règles de Westgard)
--   vm_   Validation de méthodes (comparaison de méthodes, fidélité)
--   kb_   Base de connaissances
--
-- Ce fichier sert à créer une base NEUVE. Une base existante est mise à niveau
-- par les migrations de core/database.py : toute modification faite ici doit y
-- être reportée (tests/test_database.py vérifie que les deux restent alignés).

-- Métadonnées internes de l'application. Une ligne par module pour sa version de schéma,
-- afin que chaque module puisse migrer indépendamment des autres (ex. "qc_schema_version").
CREATE TABLE app_metadata (
    cle    TEXT PRIMARY KEY,
    valeur TEXT
);

-- ============================================================
-- Module Études de population (préfixe qc_)
-- ============================================================

-- Un paramètre = un import (ex. "LH"). Nom détecté depuis la colonne 8 du fichier.
CREATE TABLE qc_parametres (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    nom            TEXT NOT NULL UNIQUE,
    domaine_min    REAL,               -- domaine de mesure : borne basse (ex. 0.3 pour LH)
    domaine_max    REAL,               -- domaine de mesure : borne haute (ex. 250 pour LH)
    date_import    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    fichier_source TEXT,               -- nom du fichier Excel importé, pour traçabilité
    notes          TEXT,               -- commentaires libres de l'utilisateur sur ce paramètre
    unite          TEXT                -- unité d'expression des résultats (facultatif, ex. "UI/L")
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

-- Intervalle de référence à vérifier (fournisseur, littérature...) pour un paramètre,
-- éventuellement propre à une tranche d'âge et/ou à un sexe ('' = tous).
-- La tranche est repérée par son libellé et non par son id : modifier les tranches
-- d'un paramètre recrée leurs lignes, un id ne survivrait pas à cette opération.
CREATE TABLE qc_intervalles_reference (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    parametre_id    INTEGER NOT NULL REFERENCES qc_parametres(id) ON DELETE CASCADE,
    tranche_libelle TEXT NOT NULL DEFAULT '',
    sexe            TEXT NOT NULL DEFAULT '',
    borne_basse     REAL,
    borne_haute     REAL,
    source          TEXT,
    UNIQUE (parametre_id, tranche_libelle, sexe)
);

INSERT INTO app_metadata (cle, valeur) VALUES ('qc_schema_version', '3');

-- ============================================================
-- Module Contrôle interne de qualité (préfixe ciq_)
-- ============================================================

-- Un analyte suivi sur un automate donné (ex. "Glucose" sur "Cobas c501").
CREATE TABLE ciq_analytes (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    nom                      TEXT NOT NULL,
    unite                    TEXT NOT NULL DEFAULT '',
    automate                 TEXT NOT NULL DEFAULT '',
    erreur_totale_admissible REAL,     -- % (facultatif) : sert au calcul du nombre de sigma
    regles                   TEXT,     -- règles de Westgard actives, séparées par des virgules (NULL = règles par défaut)
    notes                    TEXT,
    date_creation            TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (nom, automate)
);

-- Un lot de contrôle = un niveau de concentration d'un analyte, avec ses valeurs cibles.
-- Cibles NULL = pas encore établies (période probatoire) : la carte utilise alors la
-- moyenne et l'écart-type observés, et le signale clairement.
CREATE TABLE ciq_lots (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    analyte_id       INTEGER NOT NULL REFERENCES ciq_analytes(id) ON DELETE CASCADE,
    niveau           TEXT NOT NULL,            -- "Niveau 1", "Normal", "Pathologique"...
    numero_lot       TEXT NOT NULL DEFAULT '',
    cible_moyenne    REAL,
    cible_ecart_type REAL,
    origine_cible    TEXT,                     -- "Fabricant", "Laboratoire"...
    date_peremption  DATE,
    actif            INTEGER NOT NULL DEFAULT 1,
    date_creation    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Un passage de contrôle. Une mesure « exclue » reste en base (traçabilité) mais ne
-- participe ni aux statistiques ni à l'évaluation des règles de Westgard.
CREATE TABLE ciq_mesures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    lot_id      INTEGER NOT NULL REFERENCES ciq_lots(id) ON DELETE CASCADE,
    date_mesure TEXT NOT NULL,                 -- ISO "AAAA-MM-JJ HH:MM"
    valeur      REAL NOT NULL,
    operateur   TEXT,
    commentaire TEXT,
    exclue      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_ciq_lots_analyte ON ciq_lots(analyte_id);
CREATE INDEX idx_ciq_mesures_lot  ON ciq_mesures(lot_id, date_mesure);

INSERT INTO app_metadata (cle, valeur) VALUES ('ciq_schema_version', '1');

-- ============================================================
-- Module Validation de méthodes (préfixe vm_)
-- ============================================================

-- Une étude enregistrée : comparaison de deux méthodes (x = méthode de comparaison,
-- y = méthode évaluée) ou étude de fidélité (x = valeur mesurée, identifiant = série).
CREATE TABLE vm_etudes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    type          TEXT NOT NULL CHECK (type IN ('comparaison','precision')),
    titre         TEXT NOT NULL,
    analyte       TEXT NOT NULL DEFAULT '',
    unite         TEXT NOT NULL DEFAULT '',
    methode_x     TEXT NOT NULL DEFAULT '',
    methode_y     TEXT NOT NULL DEFAULT '',
    parametres    TEXT,                        -- JSON : limites d'acceptation, options d'analyse
    notes         TEXT,
    date_creation TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE vm_donnees (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    etude_id    INTEGER NOT NULL REFERENCES vm_etudes(id) ON DELETE CASCADE,
    ordre       INTEGER NOT NULL,
    identifiant TEXT,
    x           REAL,
    y           REAL
);

CREATE INDEX idx_vm_donnees_etude ON vm_donnees(etude_id, ordre);

INSERT INTO app_metadata (cle, valeur) VALUES ('vm_schema_version', '1');

-- ============================================================
-- Module Base de connaissances (préfixe kb_)
-- ============================================================

CREATE TABLE kb_documents (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    titre          TEXT NOT NULL,          -- nom du livre/document, éditable
    fichier_source TEXT NOT NULL,          -- nom du fichier PDF importé
    nombre_pages   INTEGER,
    date_import    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE kb_passages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id  INTEGER NOT NULL REFERENCES kb_documents(id) ON DELETE CASCADE,
    page         INTEGER NOT NULL,
    ordre        INTEGER NOT NULL,        -- position du passage dans le document
    texte        TEXT NOT NULL,           -- texte brut du passage
    embedding    BLOB NOT NULL            -- vecteur numpy sérialisé (float32)
);

CREATE INDEX idx_kb_passages_document ON kb_passages(document_id);

INSERT INTO app_metadata (cle, valeur) VALUES ('kb_schema_version', '1');

-- ============================================================
-- Futurs modules : suivre le même principe, ex. pour un module "modx" :
--   CREATE TABLE modx_xxx (...);
--   INSERT INTO app_metadata (cle, valeur) VALUES ('modx_schema_version', '1');
-- ============================================================
