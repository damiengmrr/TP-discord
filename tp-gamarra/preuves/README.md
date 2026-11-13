# Preuves réellement relevées — TP2 Discord

Les sorties proviennent des copier-coller de Terminal de l’étudiant du 13 novembre 2026.

- `chargement.txt` : extrait condensé des comptages PostgreSQL et invariants, avec mention de la condensation.
- `contraintes.txt` : les neuf preuves SQL (huit violations refusées et un compteur confirmé).
- `mesure0_csv.txt` : profilage des CSV.
- `requetes_sql.txt`, `explain_r3.txt` : chronométrages R1/R2/R3 et plan d’exécution.
- `benchmark.txt` : tableau des centiles transmis après `python bench.py --n 300`.
- `ttl.txt` : test d’expiration Redis.
- `tombstones_incident.txt`, `cassandra_logs.txt`, `tombstones_reparation1.txt`, `tombstones_reproduction2.txt`, `tombstones_reparation2.txt` : expérience de suppressions Cassandra et deux correctifs.
- `machine_et_gc_grace.txt` : matériel et retour à `gc_grace_seconds=864000`.
- `r1_trois_salons.txt` : mesures R1 sur salon chaud, moyen, clairsemé.
- `terminal_verifications_finales_13-11-2026.txt` : copier-coller complet fourni pour les dernières vérifications (certaines barres verticales sont échappées dans le format collé).

Les résumés ne sont pas des sorties de commande verbatim ; lorsqu'un extrait a été condensé, cela est annoncé. Les traces originales détaillées des derniers tests ont été conservées sans modification de leurs valeurs. Les tests Docker ont été exécutés sur le Mac de l’étudiant, **pas** dans l'environnement de préparation de l’archive.
