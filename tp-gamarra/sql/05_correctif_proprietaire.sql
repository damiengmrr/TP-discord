-- Correctif applicable SANS supprimer app ni staging.
-- Après ce script, rejouer sql/02_chargement.sql (la transaction précédente a été annulée).
CREATE OR REPLACE FUNCTION app.verifier_proprietaire() RETURNS TRIGGER LANGUAGE plpgsql AS $$
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
