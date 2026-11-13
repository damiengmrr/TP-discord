-- Mission 2. Dans psql, \timing on (les durées dépendent de la machine).
\timing on
-- R1 : les 50 derniers messages, pseudo inclus. Passer le dernier ID de la page précédente
-- comme avant_id (ici NULL = première page). Sans OFFSET.
WITH params AS (SELECT 775::integer AS salon_id, NULL::bigint AS avant_id)
SELECT m.id,m.contenu,m.envoye_le,u.pseudo FROM app.message m
JOIN app.utilisateur u ON u.id=m.auteur_id CROSS JOIN params p
WHERE m.salon_id=p.salon_id AND (p.avant_id IS NULL OR m.id<p.avant_id)
ORDER BY m.id DESC LIMIT 50;
-- R2 : permission à tester pour chaque message envoyé.
-- L'identifiant de l'auteur est choisi parmi des membres effectifs (cas positif).
WITH echantillon AS (SELECT m.utilisateur_id AS uid, s.id AS salon_id
 FROM app.membre m JOIN app.salon s ON s.serveur_id=m.serveur_id
 WHERE s.type='texte' ORDER BY m.utilisateur_id,s.id LIMIT 1)
SELECT e.uid,e.salon_id,EXISTS (
 SELECT 1 FROM app.salon s JOIN app.membre m ON m.serveur_id=s.serveur_id
 WHERE s.id=e.salon_id AND s.type='texte' AND m.utilisateur_id=e.uid
) AS peut_ecrire FROM echantillon e;
-- R3 : octobre 2026 complet, serveur 118 ; une jointure et un filtre date.
SELECT (m.envoye_le AT TIME ZONE 'UTC')::date AS jour,
       COUNT(*)::bigint AS nb_messages, COUNT(DISTINCT m.auteur_id)::bigint AS nb_auteurs
FROM app.message m JOIN app.salon s ON s.id=m.salon_id
WHERE s.serveur_id=118
  AND m.envoye_le >= '2026-10-01T00:00:00Z'::timestamptz
  AND m.envoye_le < '2026-11-01T00:00:00Z'::timestamptz
GROUP BY 1 ORDER BY 1;
-- Mesure 3 : relever le nœud le plus coûteux, type de scan et Buffers.
EXPLAIN (ANALYZE, BUFFERS)
SELECT (m.envoye_le AT TIME ZONE 'UTC')::date AS jour,
       count(*),count(DISTINCT m.auteur_id)
FROM app.message m JOIN app.salon s ON s.id=m.salon_id
WHERE s.serveur_id=118
  AND m.envoye_le >= '2026-10-01T00:00:00Z'::timestamptz
  AND m.envoye_le < '2026-11-01T00:00:00Z'::timestamptz
GROUP BY 1 ORDER BY 1;
-- R3 dénormalisé : vue matérialisée, unique index (serveur_id,jour).
SELECT jour,nb_messages,nb_auteurs FROM app.activite_serveur_jour
WHERE serveur_id=118 AND jour>='2026-10-01' AND jour<'2026-11-01'
ORDER BY jour;
-- La commande suivante peut s'exécuter pendant la vie de la plateforme ;
-- elle doit rester hors transaction et après le premier REFRESH non concurrent.
REFRESH MATERIALIZED VIEW CONCURRENTLY app.activite_serveur_jour;
