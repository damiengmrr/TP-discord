# TP2 Discord — Gamarra Damien (B3 Ynov Montpellier)

Suite du TP1 : construire le schéma de la plateforme miniature, migrer ses messages, comparer les moteurs et confronter les choix aux mesures. Les documents et schémas du TP1 sont dans le dépôt d'origine : <https://github.com/damiengmrr/TP-discord>.

**Correctif 13/11/2026 :** le trigger `verifier_proprietaire` a été réparé : il ne doit plus utiliser
`OLD.serveur_id` sur la table `serveur`. Les scripts `bench/` vérifient désormais que PostgreSQL
contient les messages avant de commencer une migration. `wait_for_cassandra.py` vérifie une vraie
connexion CQL avant les tests.

### Si les premiers essais ont échoué sur `record "old" has no field "serveur_id"`

Depuis `tp-gamarra/` sur le Mac, ne pas réinstaller Python ni supprimer les volumes Docker.
Mettre à jour les scripts avec cette archive, puis :

```bash
# Correctif non destructif : il remplace uniquement la fonction PostgreSQL concernée.
docker compose exec -T postgres psql -U tp -d discord -v ON_ERROR_STOP=1 < sql/05_correctif_proprietaire.sql
# Rejouer le chargement annulé lors de la première tentative.
docker compose exec -T postgres psql -U tp -d discord -v ON_ERROR_STOP=1 < sql/02_chargement.sql
# Le tableau de comptages doit montrer 300000 messages et les décomptes sans différence.
docker compose exec -T postgres psql -U tp -d discord -v ON_ERROR_STOP=1 < sql/04_preuves.sql
docker compose exec -T postgres psql -U tp -d discord -v ON_ERROR_STOP=1 < sql/03_requetes.sql
# Pour les moteurs NoSQL :
docker compose --profile colonne up -d
cd bench
python wait_for_cassandra.py
python load_nosql.py
python verifier.py
python ttl.py
python bench.py --n 300 | tee ../preuves/benchmark.txt
cd ..
```

**N'exécutez pas** `docker compose down -v` avant d'avoir terminé : cette commande efface les volumes du TP.

**État au 13/11/2026 :** l’étudiant a exécuté les bases Docker sur son Mac, corrigé le trigger, rempli les six tables (300 000 messages), vérifié huit règles, migré vers les moteurs NoSQL, relevé le benchmark et terminé les deux réparations tombstones. Les **résultats réels** sont intégrés dans `MESURES.md` et `preuves/`. La machine a été identifiée : **MacBook Pro, Apple M3 Pro, 36 Go RAM, macOS 26.5.1** ; l'allocation effective de Docker Desktop demeure non mesurée. Le réglage Cassandra `gc_grace_seconds` a été recontrôlé à **864000** secondes.

## Prérequis sur Mac

- Docker Desktop démarré (au moins **5 Go** alloués à Docker).
- Python **3.9+**, terminal, et les ports 5432, 27017, 6379, 7687, 7474, 9042 libres.
- Dans le dossier `tp-gamarra/`, lancer :

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cd data && python generate_data.py && cd ..
docker compose up -d
docker compose ps
```

## Missions 0 à 2 : PostgreSQL

```bash
# Mesure 0, calcul reproductible directement depuis les CSV
python bench/profil_csv.py
# PostgreSQL : importer les six CSV puis créer et remplir app.*
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U tp -d discord < sql/00_staging.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U tp -d discord < sql/01_schema.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U tp -d discord < sql/02_chargement.sql
# PREUVES / chrono : copier les NOTICE et EXPLAIN dans MESURES.md
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U tp -d discord < sql/04_preuves.sql
docker compose exec -T postgres psql -v ON_ERROR_STOP=1 -U tp -d discord < sql/03_requetes.sql
```

Le fichier `01_schema.sql` supprime l'ancien schéma `app` ; ne pas le relancer sur une base où des données importantes auraient été saisies. Le `02_chargement.sql` recharge les tables et réinitialise les données d'exercice.

## Missions 3 et 5 : MongoDB, Cassandra, Redis, Neo4j

```bash
docker compose --profile colonne up -d
# Cassandra peut mettre du temps à initialiser son premier keyspace.
docker compose --profile colonne ps
cd bench
python wait_for_cassandra.py
python load_nosql.py
python verifier.py
python ttl.py
python bench.py --n 300 | tee ../preuves/benchmark.txt
cd ..
```

`load_nosql.py` crée lui-même les tables Cassandra (même schéma que `cql/01_schema.cql`) et initialise Redis et Neo4j. `verifier.py` dénombre les lignes Cassandra **en les relisant par fenêtre** (pas de `SELECT count(*)` global). `bench.py` interrompt les mesures si les réponses divergent entre les moteurs. Des tests de cache Redis (B1, B4) et d’appartenance (H5) ont été ajoutés pour confronter les hypothèses spécifiques du TP1.

## Mission 4 : incident Cassandra

**À faire sur le jeu d'essai seulement ; pas sur une base de production.**

```bash
cd bench
python tombstones.py | tee ../preuves/tombstones_incident.txt
cd ..
docker compose --profile colonne logs cassandra > preuves/cassandra_logs.txt
cd bench
python tombstones.py --reparer | tee ../preuves/tombstones_reparation.txt
cd ..
```

Pour le **deuxième correctif** (purger les marqueurs existants), suivre attentivement `RUNBOOK_tombstones.md`, puis conserver la sortie et restaurer `gc_grace_seconds=864000`.

## Fin de TP (mise à jour après exécution)

Les durées, le plan EXPLAIN, les trois mesures R1 avec jointure auteur, les caractéristiques du Mac et les verdicts sont **déjà renseignés**. Les preuves des dernières vérifications se trouvent dans `preuves/r1_trois_salons.txt`, `preuves/machine_et_gc_grace.txt` et `preuves/terminal_verifications_finales_13-11-2026.txt`. Seule l'allocation effective de RAM à Docker Desktop n'a pas été relevée.

```bash
system_profiler SPHardwareDataType | grep -E 'Model Name:|Chip:|Processor Name:|Memory:'
sw_vers -productVersion
# Pour confirmer que Cassandra a retrouvé sa protection de 10 jours :
docker compose --profile colonne exec -T cassandra cqlsh -e "SELECT gc_grace_seconds FROM system_schema.tables WHERE keyspace_name = 'discord' AND table_name = 'messages_par_salon';"
```

Après avoir enregistré les dernières preuves et le matériel, nettoyer les ressources :

```bash
docker compose --profile colonne down -v
```

**Contenu du rendu :** `DOSSIER_ARCHI.md`, `MESURES.md`, `RUNBOOK_tombstones.md`, `mcd.md`, `architecture.md`, `mld.md`, `sql/`, `cql/`, `bench/`, ressources de démarrage et preuves d'exécution. Les fichiers `.md` de schémas utilisent Mermaid, lisible sur GitHub.
