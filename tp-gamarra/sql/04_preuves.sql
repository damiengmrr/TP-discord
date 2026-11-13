-- Mission 1 : exécuter APRÈS 02_chargement.sql.
-- Les violations sont capturées dans des sous-transactions PL/pgSQL : aucune donnée de test ne persiste.
\set ON_ERROR_STOP on
DO $$
DECLARE erreur text; vocal_id integer; non_membre integer; salon_texte integer;
        tmpid bigint; sid integer; owner_id integer; original integer; apres integer;
BEGIN
  IF (SELECT count(*) FROM app.utilisateur) = 0 OR
     (SELECT count(*) FROM app.message) = 0 THEN
    RAISE EXCEPTION 'Tables app.* vides : relancer sql/02_chargement.sql avant les preuves';
  END IF;
  SELECT id INTO vocal_id FROM app.salon WHERE type='vocal' ORDER BY id LIMIT 1;
  SELECT id,serveur_id INTO salon_texte,sid FROM app.salon WHERE type='texte' ORDER BY id LIMIT 1;
  SELECT id INTO non_membre FROM app.utilisateur
  WHERE NOT EXISTS(SELECT 1 FROM app.membre m WHERE m.serveur_id=sid AND m.utilisateur_id=app.utilisateur.id)
  ORDER BY id LIMIT 1;
  SELECT max(id)+1 INTO tmpid FROM app.message;
  SELECT proprietaire_id INTO owner_id FROM app.serveur WHERE id=sid;

  BEGIN
    INSERT INTO app.utilisateur VALUES (999999,'u-test','user1@exemple.fr',now());
    RAISE EXCEPTION 'ERREUR TEST: doublon email accepté';
  EXCEPTION WHEN unique_violation THEN
    GET STACKED DIAGNOSTICS erreur=MESSAGE_TEXT; RAISE NOTICE 'Preuve 1 email unique : %',erreur;
  END;
  BEGIN
    INSERT INTO app.membre VALUES (owner_id,sid,'admin',now());
    RAISE EXCEPTION 'ERREUR TEST: rôle admin accepté';
  EXCEPTION WHEN check_violation THEN
    GET STACKED DIAGNOSTICS erreur=MESSAGE_TEXT; RAISE NOTICE 'Preuve 2 rôle : %',erreur;
  END;
  BEGIN
    INSERT INTO app.salon VALUES (999999,sid,'invalide','video',now());
    RAISE EXCEPTION 'ERREUR TEST: type invalide accepté';
  EXCEPTION WHEN check_violation THEN
    GET STACKED DIAGNOSTICS erreur=MESSAGE_TEXT; RAISE NOTICE 'Preuve 3 type salon : %',erreur;
  END;
  BEGIN
    INSERT INTO app.salon SELECT 999998,serveur_id,nom,type,now() FROM app.salon WHERE id=salon_texte;
    RAISE EXCEPTION 'ERREUR TEST: doublon salon accepté';
  EXCEPTION WHEN unique_violation THEN
    GET STACKED DIAGNOSTICS erreur=MESSAGE_TEXT; RAISE NOTICE 'Preuve 4 nom salon : %',erreur;
  END;
  BEGIN
    INSERT INTO app.amitie VALUES (88,22,now());
    RAISE EXCEPTION 'ERREUR TEST: amitié à l’envers acceptée';
  EXCEPTION WHEN check_violation THEN
    GET STACKED DIAGNOSTICS erreur=MESSAGE_TEXT; RAISE NOTICE 'Preuve 5 ordre amitié : %',erreur;
  END;
  BEGIN
    INSERT INTO app.salon VALUES (999999,999999,'introuvable','texte',now());
    RAISE EXCEPTION 'ERREUR TEST: serveur manquant accepté';
  EXCEPTION WHEN foreign_key_violation THEN
    GET STACKED DIAGNOSTICS erreur=MESSAGE_TEXT; RAISE NOTICE 'Preuve 6 FK serveur : %',erreur;
  END;
  BEGIN
    INSERT INTO app.message VALUES (tmpid,vocal_id,owner_id,'interdit',now(),NULL,NULL);
    RAISE EXCEPTION 'ERREUR TEST: vocal accepté';
  EXCEPTION WHEN raise_exception THEN
    GET STACKED DIAGNOSTICS erreur=MESSAGE_TEXT;
    IF erreur NOT LIKE 'message_dans_salon_vocal:%' THEN RAISE; END IF;
    RAISE NOTICE 'Preuve 7 vocal : %',erreur;
  END;
  BEGIN
    INSERT INTO app.message VALUES (tmpid,salon_texte,non_membre,'interdit',now(),NULL,NULL);
    RAISE EXCEPTION 'ERREUR TEST: non-membre accepté';
  EXCEPTION WHEN raise_exception THEN
    GET STACKED DIAGNOSTICS erreur=MESSAGE_TEXT;
    IF erreur NOT LIKE 'auteur_non_membre:%' THEN RAISE; END IF;
    RAISE NOTICE 'Preuve 8 non-membre : %',erreur;
  END;

  -- Trigger compteur : insertion -> +1 ; suppression -> retour exact.
  SELECT nb_membres INTO original FROM app.serveur WHERE id=sid;
  INSERT INTO app.membre(utilisateur_id,serveur_id,role,rejoint_le) VALUES(non_membre,sid,'membre',now());
  SELECT nb_membres INTO apres FROM app.serveur WHERE id=sid;
  IF apres<>original+1 THEN RAISE EXCEPTION 'Compteur après insertion incorrect'; END IF;
  DELETE FROM app.membre WHERE utilisateur_id=non_membre AND serveur_id=sid;
  SELECT nb_membres INTO apres FROM app.serveur WHERE id=sid;
  IF apres<>original THEN RAISE EXCEPTION 'Compteur après suppression incorrect'; END IF;
  RAISE NOTICE 'Preuve 9 compteur: % -> % -> %',original,original+1,apres;
END $$;
-- Note : le trigger propriétaire est INITIALLY DEFERRED : pour prouver son refus au COMMIT,
-- exécuter séparément : BEGIN; DELETE FROM app.membre WHERE ...propriétaire...; COMMIT;
