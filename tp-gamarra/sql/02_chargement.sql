-- Lecture staging -> app, transaction atomique ; relancer après la régénération des CSV.
\set ON_ERROR_STOP on
BEGIN;
TRUNCATE app.message, app.amitie, app.presence, app.membre, app.salon,
         app.serveur, app.utilisateur CASCADE;
INSERT INTO app.utilisateur(id,pseudo,email,cree_le)
SELECT id::integer,pseudo,email,cree_le::timestamptz FROM staging.utilisateurs;
INSERT INTO app.serveur(id,nom,proprietaire_id,cree_le)
SELECT id::integer,nom,proprietaire_id::integer,cree_le::timestamptz FROM staging.serveurs;
INSERT INTO app.salon(id,serveur_id,nom,type,cree_le)
SELECT id::integer,serveur_id::integer,nom,type,cree_le::timestamptz FROM staging.salons;
INSERT INTO app.membre(utilisateur_id,serveur_id,role,rejoint_le)
SELECT utilisateur_id::integer,serveur_id::integer,role,rejoint_le::timestamptz FROM staging.membres;
INSERT INTO app.message(id,salon_id,auteur_id,contenu,envoye_le,modifie_le,pieces_jointes)
SELECT id::bigint,salon_id::integer,auteur_id::integer,contenu,envoye_le::timestamptz,
       NULLIF(modifie_le,'')::timestamptz,NULLIF(pieces_jointes,'')::jsonb
FROM staging.messages;
INSERT INTO app.amitie(utilisateur_a,utilisateur_b,depuis)
SELECT utilisateur_a::integer,utilisateur_b::integer,depuis::timestamptz FROM staging.amities;
COMMIT;
REFRESH MATERIALIZED VIEW app.activite_serveur_jour;
ANALYZE app.utilisateur;
ANALYZE app.serveur;
ANALYZE app.salon;
ANALYZE app.membre;
ANALYZE app.message;
ANALYZE app.amitie;
-- Mesure 1 : toute différence entre staging et app est une erreur.
WITH comparaison AS (
SELECT 'utilisateurs' AS tab, (SELECT count(*) FROM staging.utilisateurs) AS staging,
       (SELECT count(*) FROM app.utilisateur) AS app
UNION ALL SELECT 'serveurs',(SELECT count(*) FROM staging.serveurs),(SELECT count(*) FROM app.serveur)
UNION ALL SELECT 'salons',(SELECT count(*) FROM staging.salons),(SELECT count(*) FROM app.salon)
UNION ALL SELECT 'membres',(SELECT count(*) FROM staging.membres),(SELECT count(*) FROM app.membre)
UNION ALL SELECT 'messages',(SELECT count(*) FROM staging.messages),(SELECT count(*) FROM app.message)
UNION ALL SELECT 'amities',(SELECT count(*) FROM staging.amities),(SELECT count(*) FROM app.amitie)
)
SELECT *,CASE WHEN staging=app THEN 'OK' ELSE 'ERREUR' END AS verdict FROM comparaison ORDER BY tab;
-- Invariants (résultat attendu : 0 et 0).
SELECT count(*) AS proprietaires_invalides FROM app.serveur s
WHERE NOT EXISTS (SELECT 1 FROM app.membre m WHERE m.serveur_id=s.id
                  AND m.utilisateur_id=s.proprietaire_id AND m.role='proprietaire');
SELECT count(*) AS messages_dans_salons_vocaux FROM app.message m
JOIN app.salon s ON s.id=m.salon_id WHERE s.type <> 'texte';
SELECT count(*) AS compteurs_faux FROM app.serveur s
WHERE s.nb_membres <> (SELECT count(*) FROM app.membre m WHERE m.serveur_id=s.id);
