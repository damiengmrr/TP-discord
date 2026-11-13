# RUNBOOK — Incident `READ_TOO_MANY_TOMBSTONES` (Cassandra)

**Périmètre :** table `discord.messages_par_salon` ; environnement du TP uniquement. **Objectif exploitant :** rétablir la lecture d’un salon après des suppressions massives. Ne jamais utiliser la purge ci-dessous telle quelle en production.

## Symptôme et diagnostic

La lecture des 50 derniers messages échoue avec `READ_TOO_MANY_TOMBSTONES` : Cassandra doit traverser des marqueurs laissés par les suppressions avant d’atteindre le plus ancien message conservé. Le seuil protège le nœud contre des lectures trop lourdes.

**Preuve du 13/11/2026 :** avant suppression, **50 messages en 5 ms** ; après **119 999 suppressions ligne par ligne**, échec en **129 ms**, `code=1300`. Les logs indiquent `Read 0 live rows and 100001 tombstone cells` et `Scanned over 100001 tombstones ... query aborted`. Le script fourni tronque le message d’erreur à 160 caractères.

```bash
cd ~/Downloads/tp-gamarra
cd bench && python tombstones.py && cd ..
docker compose --profile colonne logs --no-color cassandra | grep -Ei 'tombstone|read.failure|abort'
```

## Deux actions correctives prouvées

**1. Supprimer la partition entière (si le métier autorise de tout supprimer).**

```bash
cd bench && python tombstones.py --reparer && cd ..
```

**Résultat mesuré :** 50 messages lus en **4 ms** avant, puis lecture réussie de **0 message en 33 ms** après. Une suppression de partition remplace les milliers de suppressions individuelles, mais **elle supprime aussi le message qu’on voulait conserver**. Ne pas appliquer si une conservation partielle est exigée.

**2. Purger les tombstones existantes (TP isolé seulement).** Recréer l’incident, puis :

```bash
cd bench && python tombstones.py && cd ..
docker compose --profile colonne exec -T cassandra cqlsh -e "ALTER TABLE discord.messages_par_salon WITH gc_grace_seconds = 0;"
docker compose --profile colonne exec -T cassandra nodetool flush discord messages_par_salon
docker compose --profile colonne exec -T cassandra nodetool compact discord messages_par_salon
docker compose --profile colonne exec -T cassandra cqlsh -e "SELECT message_id FROM discord.messages_par_salon WHERE salon_id=-1 AND bucket=0 LIMIT 50;"
# Rétablir immédiatement la protection :
docker compose --profile colonne exec -T cassandra cqlsh -e "ALTER TABLE discord.messages_par_salon WITH gc_grace_seconds = 864000;"
# Confirmer sa valeur :
docker compose --profile colonne exec -T cassandra cqlsh -e "SELECT gc_grace_seconds FROM system_schema.tables WHERE keyspace_name='discord' AND table_name='messages_par_salon';"
```

**Résultat mesuré :** nouvel échec en **85 ms** après recréation ; après compaction, le message **`message_id=1`** est retrouvé. La commande de restauration figure dans le Terminal, mais sa valeur finale doit encore être confirmée par la dernière requête ci-dessus.

## Risques et prévention

La purge immédiate supprime la protection temporelle utilisée pour laisser les réplicas se synchroniser. Sur un cluster réel, elle risque de faire **réapparaître des suppressions** si un réplica conserve une ancienne copie. Elle exige une stratégie de réparation/réplication contrôlée, jamais une action improvisée. Préférer les suppressions par partition quand elles sont justifiées métier, un suivi des fenêtres vides, la compaction et des alertes sur tombstones lues, échecs `READ_TOO_MANY_TOMBSTONES` et p95 de lecture par salon. **Responsable :** exploitant, avec validation métier de toute suppression totale.
