-- TP Discord J2 - Schéma PostgreSQL (source de vérité).
-- Exécution après 00_staging.sql, avant 02_chargement.sql.
-- Attention : recréer le schéma efface les données de app.*.
DROP SCHEMA IF EXISTS app CASCADE;
CREATE SCHEMA app;

CREATE TABLE app.utilisateur (
    id INTEGER PRIMARY KEY,
    pseudo VARCHAR(80) NOT NULL CHECK (length(trim(pseudo)) > 0),
    email VARCHAR(255) NOT NULL UNIQUE,
    cree_le TIMESTAMPTZ NOT NULL
);

CREATE TABLE app.serveur (
    id INTEGER PRIMARY KEY,
    nom VARCHAR(120) NOT NULL CHECK (length(trim(nom)) > 0),
    proprietaire_id INTEGER NOT NULL REFERENCES app.utilisateur(id),
    cree_le TIMESTAMPTZ NOT NULL,
    nb_membres INTEGER NOT NULL DEFAULT 0 CHECK (nb_membres >= 0)
);
-- Recherche de serveurs par propriétaire (clé étrangère non indexée automatiquement).
CREATE INDEX serveur_proprietaire_idx ON app.serveur(proprietaire_id);

CREATE TABLE app.salon (
    id INTEGER PRIMARY KEY,
    serveur_id INTEGER NOT NULL REFERENCES app.serveur(id) ON DELETE CASCADE,
    nom VARCHAR(120) NOT NULL,
    type VARCHAR(5) NOT NULL CHECK (type IN ('texte', 'vocal')),
    cree_le TIMESTAMPTZ NOT NULL,
    UNIQUE (serveur_id, nom)
);
-- UNIQUE(serveur_id,nom) sert aussi de préfixe d'index pour lister les salons d'un serveur.

CREATE TABLE app.membre (
    utilisateur_id INTEGER NOT NULL REFERENCES app.utilisateur(id),
    serveur_id INTEGER NOT NULL REFERENCES app.serveur(id) ON DELETE CASCADE,
    role VARCHAR(13) NOT NULL CHECK (role IN ('proprietaire','moderateur','membre')),
    rejoint_le TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (utilisateur_id, serveur_id)
);
-- R2 : retrouver rapidement tous les membres d'un serveur et les compter.
CREATE INDEX membre_serveur_idx ON app.membre(serveur_id, utilisateur_id);
-- Un rôle propriétaire par serveur. Le trigger différé vérifie que c'est bien serveur.proprietaire_id.
CREATE UNIQUE INDEX membre_un_proprietaire_idx ON app.membre(serveur_id) WHERE role = 'proprietaire';

CREATE TABLE app.message (
    id BIGINT PRIMARY KEY CHECK (id > 0), -- Snowflake : l'ordre des IDs est chronologique
    salon_id INTEGER NOT NULL REFERENCES app.salon(id),
    auteur_id INTEGER NOT NULL REFERENCES app.utilisateur(id),
    contenu TEXT NOT NULL,
    envoye_le TIMESTAMPTZ NOT NULL,
    modifie_le TIMESTAMPTZ,
    pieces_jointes JSONB,
    CONSTRAINT message_modification_apres_envoi CHECK (modifie_le IS NULL OR modifie_le >= envoye_le)
);
-- B1/R1 : 50 messages récents d'un salon, et pagination par id (pas OFFSET).
CREATE INDEX message_salon_id_desc_idx ON app.message(salon_id, id DESC);
-- FK auteur : lister les messages d'un auteur / améliorer suppressions et contrôles.
CREATE INDEX message_auteur_idx ON app.message(auteur_id);
-- R3 utilise le parcours par salon, mais envoye_le reste à filtrer : motif de la mesure EXPLAIN.

CREATE TABLE app.amitie (
    utilisateur_a INTEGER NOT NULL REFERENCES app.utilisateur(id),
    utilisateur_b INTEGER NOT NULL REFERENCES app.utilisateur(id),
    depuis TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (utilisateur_a, utilisateur_b),
    CHECK (utilisateur_a < utilisateur_b)
);
-- Les amitiés sont symétriques, B3/B3bis doivent chercher les deux orientations.
CREATE INDEX amitie_b_a_idx ON app.amitie(utilisateur_b, utilisateur_a);

CREATE TABLE app.presence (
    utilisateur_id INTEGER PRIMARY KEY REFERENCES app.utilisateur(id),
    vu_le TIMESTAMPTZ NOT NULL
);
-- La date est comparée à now()-interval '5 minutes' ; expiration PostgreSQL non automatique.
CREATE INDEX presence_vu_le_idx ON app.presence(vu_le);

-- Dénormalisation 1 : compteur incrémental, sans recalcul complet à chaque mutation.
CREATE FUNCTION app.maj_nb_membres() RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  IF TG_OP = 'INSERT' THEN
    UPDATE app.serveur SET nb_membres = nb_membres + 1 WHERE id = NEW.serveur_id;
    RETURN NEW;
  ELSIF TG_OP = 'DELETE' THEN
    UPDATE app.serveur SET nb_membres = nb_membres - 1 WHERE id = OLD.serveur_id;
    RETURN OLD;
  ELSIF NEW.serveur_id IS DISTINCT FROM OLD.serveur_id THEN
    UPDATE app.serveur SET nb_membres = nb_membres - 1 WHERE id = OLD.serveur_id;
    UPDATE app.serveur SET nb_membres = nb_membres + 1 WHERE id = NEW.serveur_id;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER membre_compteur AFTER INSERT OR DELETE OR UPDATE OF serveur_id ON app.membre
FOR EACH ROW EXECUTE FUNCTION app.maj_nb_membres();

-- Propriétaire = membre avec rôle propriétaire ; vérification différée pour permettre le chargement
-- dans la même transaction (on charge les serveurs AVANT leurs membres).
CREATE FUNCTION app.verifier_proprietaire() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
  sid INTEGER;
  ancien_sid INTEGER;
BEGIN
  -- IMPORTANT : OLD/NEW ne possèdent pas les mêmes colonnes dans serveur et membre.
  -- Des IF distincts empêchent PostgreSQL d'évaluer OLD.serveur_id sur app.serveur.
  IF TG_TABLE_NAME = 'serveur' THEN
    IF TG_OP = 'DELETE' THEN
      RETURN NULL;
    END IF;
    sid := NEW.id;
  ELSIF TG_TABLE_NAME = 'membre' THEN
    IF TG_OP = 'DELETE' THEN
      sid := OLD.serveur_id;
    ELSE
      sid := NEW.serveur_id;
      IF TG_OP = 'UPDATE' THEN
        IF OLD.serveur_id IS DISTINCT FROM NEW.serveur_id THEN
          ancien_sid := OLD.serveur_id;
        END IF;
      END IF;
    END IF;
  ELSE
    RAISE EXCEPTION 'Table non prise en charge : %', TG_TABLE_NAME;
  END IF;

  -- Le propriétaire doit toujours être membre de son serveur avec le bon rôle.
  IF EXISTS (SELECT 1 FROM app.serveur s WHERE s.id = sid AND NOT EXISTS (
    SELECT 1 FROM app.membre m
    WHERE m.serveur_id = s.id AND m.utilisateur_id = s.proprietaire_id
      AND m.role = 'proprietaire'
  )) THEN
    RAISE EXCEPTION 'proprietaire_non_membre: serveur %', sid;
  END IF;

  -- Si un membre change de serveur, on recontrôle aussi celui qu'il quitte.
  IF ancien_sid IS NOT NULL THEN
    IF EXISTS (SELECT 1 FROM app.serveur s WHERE s.id = ancien_sid AND NOT EXISTS (
      SELECT 1 FROM app.membre m
      WHERE m.serveur_id = s.id AND m.utilisateur_id = s.proprietaire_id
        AND m.role = 'proprietaire'
    )) THEN
      RAISE EXCEPTION 'proprietaire_non_membre: serveur %', ancien_sid;
    END IF;
  END IF;
  RETURN NULL;
END $$;
CREATE CONSTRAINT TRIGGER verifier_proprietaire_serveur
AFTER INSERT OR UPDATE OF proprietaire_id ON app.serveur
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.verifier_proprietaire();
CREATE CONSTRAINT TRIGGER verifier_proprietaire_membre
AFTER INSERT OR UPDATE OR DELETE ON app.membre
DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION app.verifier_proprietaire();

-- Interdit d'envoyer dans un salon vocal ou sans être membre du serveur.
-- Le trigger est volontairement sur le chemin d'écriture (coût d'une vérification indexée).
CREATE FUNCTION app.verifier_message() RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE sid INTEGER; stype TEXT;
BEGIN
  SELECT serveur_id, type INTO sid, stype FROM app.salon WHERE id = NEW.salon_id;
  IF sid IS NULL THEN
    -- La FK officielle émettra l'erreur de référence manquante.
    RETURN NEW;
  END IF;
  IF stype <> 'texte' THEN
    RAISE EXCEPTION 'message_dans_salon_vocal: salon %', NEW.salon_id;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM app.membre WHERE serveur_id = sid AND utilisateur_id = NEW.auteur_id) THEN
    RAISE EXCEPTION 'auteur_non_membre: utilisateur %, serveur %', NEW.auteur_id, sid;
  END IF;
  RETURN NEW;
END $$;
CREATE TRIGGER autoriser_message BEFORE INSERT OR UPDATE OF salon_id, auteur_id ON app.message
FOR EACH ROW EXECUTE FUNCTION app.verifier_message();

-- Dénormalisation 2 : tableau de bord quotidien ; rafraîchissement explicite (pas à chaque message).
-- Fuseau UTC, identique dans R3 et le benchmark (octobre 2026 = [01/10, 01/11[).
CREATE MATERIALIZED VIEW app.activite_serveur_jour AS
SELECT s.serveur_id, (m.envoye_le AT TIME ZONE 'UTC')::date AS jour,
       COUNT(*)::bigint AS nb_messages, COUNT(DISTINCT m.auteur_id)::bigint AS nb_auteurs
FROM app.message m JOIN app.salon s ON s.id = m.salon_id
GROUP BY s.serveur_id, (m.envoye_le AT TIME ZONE 'UTC')::date
WITH NO DATA;
-- Requis pour REFRESH MATERIALIZED VIEW CONCURRENTLY, et B4 par serveur/période.
CREATE UNIQUE INDEX activite_serveur_jour_unique ON app.activite_serveur_jour(serveur_id, jour);
