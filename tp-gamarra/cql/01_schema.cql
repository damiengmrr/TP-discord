-- Cassandra : partition (salon_id, bucket de 10 jours), tri Snowflake décroissant.
CREATE KEYSPACE IF NOT EXISTS discord WITH replication = {'class':'SimpleStrategy','replication_factor':1};
USE discord;
CREATE TABLE IF NOT EXISTS messages_par_salon (
  salon_id int, bucket bigint, message_id bigint,
  auteur_id int, contenu text, envoye_le timestamp,
  modifie_le timestamp, pieces_jointes text,
  PRIMARY KEY ((salon_id,bucket), message_id)
) WITH CLUSTERING ORDER BY (message_id DESC)
  AND gc_grace_seconds = 864000;
-- Correctif optionnel : ne visiter que les buckets qui contiennent des messages.
CREATE TABLE IF NOT EXISTS fenetres_non_vides (
  salon_id int, bucket bigint,
  PRIMARY KEY (salon_id,bucket)
) WITH CLUSTERING ORDER BY (bucket DESC);
