# Journal du premier essai sur Mac — 13/11/2026

Source : sortie Terminal fournie par l'étudiant. Ceci **n'est pas** un benchmark réussi.

- Génération/profilage CSV : 5000 utilisateurs, 150 serveurs, 974 salons, 7984 membres, 300000 messages, 15000 amitiés. Salon chaud 775 (12952), moyen 424 (90), clairsemé 340 (2).
- Docker : PostgreSQL 16, MongoDB 7, Neo4j 5 et Redis 7 ont démarré.
- `sql/00_staging.sql` : import CSV effectué (`COPY 300000` pour les messages).
- `sql/02_chargement.sql` : échec au `COMMIT`, `ERROR: record "old" has no field "serveur_id"` dans `app.verifier_proprietaire()`. La transaction a été annulée : les 0 lignes vues ensuite ne sont **pas** des observations du comportement normal des moteurs.
- `sql/04_preuves.sql` : arrêt sur `ERREUR TEST: doublon email accepté`, faute de données chargées.
- R1/R2/R3 : 0 ligne (résultats non exploitables). La vue matérialisée n'a pas été peuplée.
- `load_nosql.py` : MongoDB a reçu 0 message (source PostgreSQL vide), puis `NoHostAvailable` sur Cassandra au démarrage. `verifier.py` et `bench.py` ont échoué pour la même raison : **aucune latence mesurée**.
- Test Redis TTL : `t=0s Redis present: True TTL: 2`, puis `t=3s Redis present: False TTL: -2`. C'est une observation valide de l'expiration Redis ; la comparaison avec PostgreSQL doit être refaite après chargement des données.

Correctif : `sql/05_correctif_proprietaire.sql`, puis rechargement de `sql/02_chargement.sql` et attente CQL avec `bench/wait_for_cassandra.py`. Ne reporter les temps de performance qu'après les `assert` de cohérence.
