# TP2 Discord — MESURES.md (mesures 0 à 8)

**Étudiant :** Gamarra Damien · Bachelor 3 Ynov Montpellier · 13 novembre 2026

## Méthode et environnement

Les valeurs de ce document proviennent des sorties du Terminal transmises par l’étudiant, pas de chiffres théoriques. Les fichiers `preuves/` reprennent ces sorties ou leurs extraits explicitement signalés. Les durées sont locales, sur les services Docker d’un MacBook Pro ; les versions visibles sont PostgreSQL 16, MongoDB 7, Redis 7, Neo4j 5 et Cassandra 4.1.12. Python 3.13 et les pilotes ont été installés dans `.venv`.

**Machine mesurée :** MacBook Pro, puce **Apple M3 Pro**, **36 Go de RAM physique**, **macOS 26.5.1** (sortie `system_profiler` / `sw_vers` transmise le 13 novembre 2026). **Mémoire effectivement attribuée à Docker : non relevée** ; le TP exige un paramétrage d'au moins 5 Go, mais la valeur réelle ne peut pas être déduite des 36 Go de RAM du Mac. Voir `preuves/machine_et_gc_grace.txt`.

**Vérification après la mission tombstones :** `gc_grace_seconds = 864000` secondes, soit les 10 jours rétablis dans `discord.messages_par_salon` (lecture de `system_schema.tables` sur Cassandra).

Le benchmark final utilise `python bench.py --n 300` et un échauffement de 10 appels par cas. **Exception : B3bis utilise 30 répétitions** (`max(30, n//10)` dans le script), même avec `--n 300`. Il mesure le coût des appels pilotes sur localhost avec données en cache, pas un p95 d’API en production.

## Mesure 0 — État des données

Commande exécutée : `python generate_data.py`, puis `python bench/profil_csv.py`.

| CSV | Lignes sans en-tête |
|---|---:|
| utilisateurs | 5 000 |
| serveurs | 150 |
| salons | 974 |
| membres | 7 984 |
| messages | 300 000 |
| amities | 15 000 |

Pour les **974 salons**, minimum **0**, médiane **41**, maximum **12 952** messages. Les 10 salons les plus actifs réunissent **68 101 / 300 000 = 22,70 %** des messages ; **375** salons ont moins de 20 messages, dont **227** n’en ont aucun.

| Salon choisi | ID | Nombre de messages | Profil approché |
|---|---:|---:|---|
| Chaud | 775 | 12 952 | Grand salon textuel très actif |
| Moyen | 424 | 90 | Salon privé modérément actif |
| Clairsemé | 340 | 2 | Serveur à dominante vocale, très peu d’échanges écrits |

La répartition est volontairement inégale comme dans les profils de Discord [A1], mais **ni le volume réel ni la durée, ni la concurrence** ne sont représentatifs de Discord en production. Aucune conclusion sur le dépassement de mémoire à des centaines de millions de messages n’est possible avec ce jeu.

## Mesure 1 — PostgreSQL et contraintes

`sql/02_chargement.sql` a terminé avec **COMMIT**, puis `REFRESH MATERIALIZED VIEW` et les commandes `ANALYZE`. Le même nombre de lignes a été observé dans staging et app :

| Table | staging | app | Écart |
|---|---:|---:|---:|
| utilisateur | 5 000 | 5 000 | 0 |
| serveur | 150 | 150 | 0 |
| salon | 974 | 974 | 0 |
| membre | 7 984 | 7 984 | 0 |
| message | 300 000 | 300 000 | 0 |
| amitie | 15 000 | 15 000 | 0 |

**Invariants vérifiés :** propriétaire membre avec rôle valide : **0 erreur** ; messages dans un salon vocal : **0** ; compteurs `nb_membres` incorrects : **0**.

`sql/04_preuves.sql` a refusé huit violations et vérifié un compteur :

| Preuve | Règle vérifiée | Résultat SQL observé |
|---|---|---|
| 1 | Email unique | `duplicate key value violates unique constraint "utilisateur_email_key"` |
| 2 | Rôle membre autorisé | `new row for relation "membre" violates check constraint "membre_role_check"` |
| 3 | Type salon texte/vocal | `new row for relation "salon" violates check constraint "salon_type_check"` |
| 4 | Nom de salon unique/serveur | `duplicate key value violates unique constraint "salon_serveur_id_nom_key"` |
| 5 | Amitié ordonnée | `new row for relation "amitie" violates check constraint "amitie_check"` |
| 6 | FK serveur du salon | `insert or update on table "salon" violates foreign key constraint "salon_serveur_id_fkey"` |
| 7 | Pas de messages dans salon vocal | `message_dans_salon_vocal: salon 9` |
| 8 | Auteur obligatoirement membre | `auteur_non_membre: utilisateur 1, serveur 1` |
| 9 | Compteur `nb_membres` (INSERT/DELETE) | **12 → 13 → 12**, retour à la valeur initiale |

Preuves brutes dans `preuves/contraintes.txt`. La règle « propriétaire = membre avec rôle propriétaire » est contrôlée par un **trigger différé**, pour permettre une transaction créant serveur + adhésion ; « salon textuel et auteur membre » est contrôlée lors de l’écriture d’un message. Ces contrôles ajoutent des accès indexés sur le chemin d’écriture, mais empêchent qu’une API contournant un contrôle applicatif corrompe la base.

## Mesure 2 — Temps de R1, R2, R3

Les temps suivants proviennent de `psql` avec `\timing on`, exécuté **après** le chargement correct :

| Requête SQL | Durée locale |
|---|---:|
| R1, 50 derniers du salon 775 avec auteur | **1,881 ms** (50 lignes) |
| R2, droit d’écrire dans le salon 577 par utilisateur 1 | **0,879 ms** (vrai) |
| R3, activité du serveur 118 en octobre 2026 | **7,802 ms** (31 jours) |

**Complément R1 — même requête avec jointure auteur pour les trois salons.** Après le chargement et le benchmark, `sql/06_mesure_r1_trois_salons.sql` a été lancé sur les trois salons, avec `JOIN app.utilisateur`, `ORDER BY m.id DESC`, `LIMIT 50` et `\timing on` :

| Profil et ID du salon | Lignes retournées | Durée ponctuelle psql |
|---|---:|---:|
| Chaud · 775 | 50 | **2,262 ms** |
| Moyen · 424 | 50 | **0,648 ms** |
| Clairsemé · 340 | 2 | **0,195 ms** |

Le salon clairsemé ne contient que deux messages. Ces durées **d'une exécution SQL dans psql** ne sont pas les centiles p50 et p95 mesurés plus loin pour B1 (appels pilotes répétés). Les sorties complètes sont conservées dans `preuves/terminal_verifications_finales_13-11-2026.txt` et résumées dans `preuves/r1_trois_salons.txt`.

## Mesure 3 — EXPLAIN (ANALYZE, BUFFERS) de R3

Le plan réel affiche un `GroupAggregate` supérieur (coût estimé 4134,80..4137,87), un `Sort`, puis un `Nested Loop`. La lecture de `app.message` est un **Bitmap Heap Scan**, alimenté par `Bitmap Index Scan using message_salon_id_desc_idx` : l’index sélectionne les messages des salons, puis PostgreSQL doit appliquer le filtre temporel sur `envoye_le`.

- `Bitmap Index Scan` : **4 859 lignes en moyenne × 4 salons** ; `Bitmap Heap Scan` : **482 retenues × 4**, soit **1 928 messages** après filtre ; **4 377 × 4** lignes rejetées par date.
- `Buffers: shared hit=5645` pour l’agrégation ; `shared hit=5633` pour le `Nested Loop` côté messages.
- `Execution Time: 5.079 ms` selon `EXPLAIN ANALYZE` ; `Time: 5.401 ms` pour la commande `psql`.

Le `Bitmap Heap Scan` des messages est la partie la plus lourde du plan côté accès aux données (≈ 0,968..1,063 ms par boucle, quatre boucles). L’index `(salon_id, id DESC)` aide R1, pas une restriction temporelle directe de R3. Le scan des salons est un `Index Scan using salon_pkey`, qui élimine **970 salons** pour conserver les **4** du serveur 118. Ces choix sont observés sur le poste de TP, pas à généraliser à une autre taille.

## Mesure 4 — Dénormalisations

| Opération | Normalisé | Dénormalisé | Observation |
|---|---:|---:|---|
| R3, requêtes SQL `\timing` (une exécution) | **7,802 ms** | **0,280 ms** (vue) | Environ **27,9 fois** plus rapide en lecture sur cette exécution |
| B4, benchmark p50 | **3,682 ms** | **0,151 ms** | Environ **24,4 fois** plus rapide |
| B4, benchmark p95 | **3,865 ms** | **0,223 ms** | Environ **17,3 fois** plus rapide |
| `REFRESH MATERIALIZED VIEW CONCURRENTLY` | — | **182,418 ms** | Coût de mise à jour, fraîcheur non instantanée |
| Compteur membre (insertion/relecture/suppression/relecture) | **12** | **13 puis 12** | Maintien du compteur validé par trigger |

**Vue matérialisée :** lecture rapide, calcul reporté au rafraîchissement (dans cette implémentation, manuel ; en production, tâche quotidienne). Les données sont périmées jusqu’au prochain `REFRESH`. L’index unique autorise le rafraîchissement concurrent, qui laisse lire l’ancienne vue durant le calcul et consomme des ressources.

**Compteur :** le trigger incrémente/décrémente au lieu de recompter toutes les adhésions. Un `UPDATE` de la clé `serveur_id` doit retirer un membre de l’ancien serveur et l’ajouter au nouveau ; `DELETE` doit décrémenter. Risques : contention sur `serveur` très actif, trigger désactivé ou mise à jour sans réconciliation ; garde-fou : contrôle périodique du compteur par `COUNT(*)`.

## Mesure 5 — Migration / dark launch

Après `python load_nosql.py` et `python verifier.py` :

| Source / copie | Messages mesurés | Vérification |
|---|---:|---|
| PostgreSQL | 300 000 | Référence |
| MongoDB | 300 000 | `count_documents=300000` |
| Cassandra | 300 000 | Relecture cumulée sur **15 965 fenêtres** non vides, sans `SELECT count(*)` global |

Le chargement indiquait également **1 654 clés Redis**, dont **1 500 présences**, **15 000 relations AMI_DE** et **7 984 relations MEMBRE_DE** dans Neo4j. Les assertions de cohérence pour B1, B2, B3, B3bis et B4 ont réussi.

Le dark launch B1 a comparé les ID des trois salons entre PostgreSQL, MongoDB, Cassandra et la version « fenêtres » : mêmes identifiants, même ordre. Le salon clairsemé ne renvoie que **2 messages**, pas 50 imaginaires. Cassandra utilise la clé `((salon_id, bucket), message_id)` et n’insère pas explicitement les champs absents (`UNSET_VALUE`).

## Mesure 6 — B1, 50 derniers messages

**p50/p95 en millisecondes, benchmark final** :

| Salon | Moteur | p50 | p95 |
|---|---|---:|---:|
| chaud | PostgreSQL | 0.141 | 0.227 |
| chaud | MongoDB | 0.230 | 0.248 |
| chaud | Cassandra | 1.289 | 3.069 |
| chaud | Cassandra fenêtres | 5.880 | 8.353 |
| chaud | Redis cache (TP1) | 0.117 | 0.130 |
| moyen | PostgreSQL | 0.190 | 0.498 |
| moyen | MongoDB | 0.228 | 0.252 |
| moyen | Cassandra | 63.962 | 77.543 |
| moyen | Cassandra fenêtres | 64.374 | 75.834 |
| moyen | Redis cache (TP1) | 0.103 | 0.115 |
| clairsemé | PostgreSQL | 0.197 | 0.578 |
| clairsemé | MongoDB | 0.203 | 0.220 |
| clairsemé | Cassandra | 90.181 | 110.618 |
| clairsemé | Cassandra fenêtres | 12.040 | 14.878 |
| clairsemé | Redis cache (TP1) | 0.110 | 0.120 |

Sur le salon chaud, Cassandra atteint **1,289 ms p50** et **3,069 ms p95** ; sur le salon clairsemé, il atteint **90,181 ms p50** et **110,618 ms p95**. Le moteur doit rechercher des fenêtres temporelles vides avant de retrouver les rares messages. Le mécanisme est le même que celui décrit dans le calcul 3.c du TP1 : plus les messages sont espacés, plus les buckets à parcourir sont nombreux.

**Correctif `fenetres_non_vides` :** pour le salon clairsemé, Cassandra passe de **90,181 à 12,040 ms p50**, et de **110,618 à 14,878 ms p95**. En revanche, pour le salon chaud, le p50 passe de **1,289 à 5,880 ms**, car il paie une lecture supplémentaire des métadonnées alors que les buckets nécessaires sont proches ; pour le salon moyen, **63,962 contre 64,374 ms p50**, pas de gain notable. Il faut maintenir la liste des fenêtres occupées et la cohérence de cette métadonnée, avec un coût d’écriture supplémentaire.

Ces résultats ne prouvent pas que Cassandra est intrinsèquement lent : il s’agit d’un conteneur local et d’un petit jeu de données où la répartition temporelle et les allers-retours pilotes dominent. Ils ne reproduisent pas le cluster historique de Discord.

## Mission 4 — Incident tombstones (preuves complémentaires)

- Avant suppressions : **50 messages lus en 5 ms**.
- Après **119 999 suppressions cellule/ligne** : lecture échouée en **129 ms** avec `READ_TOO_MANY_TOMBSTONES` (erreur `code=1300`). Le script fourni tronque le texte complet à 160 caractères.
- Logs : `Read 0 live rows and 100001 tombstone cells` ; `Scanned over 100001 tombstones ... query aborted`. L’échec est donc expliqué par un dépassement du seuil de tombstones par lecture, pas par l’absence de message.
- **Correctif 1 :** `python tombstones.py --reparer` a lu 50 messages en **4 ms** avant réparation, puis **0 message en 33 ms** après suppression de la partition entière. La lecture fonctionne mais le dernier message est perdu : on ne l’applique que si la suppression totale est autorisée.
- **Correctif 2 :** incident reproduit (50 messages en **7 ms**, puis échec en **85 ms**). Après réglage temporaire `gc_grace_seconds=0`, `nodetool flush`, `nodetool compact`, la requête est revenue avec **1 ligne : `message_id = 1`**. La restauration `gc_grace_seconds=864000` a été **confirmée ensuite par une requête de lecture sur `system_schema.tables`** (voir `preuves/machine_et_gc_grace.txt`).

**Risque :** ramener immédiatement `gc_grace_seconds` à 0 est réservé au TP isolé, car en production multi-réplicas une suppression purgée prématurément peut provoquer la réapparition des données. Voir `RUNBOOK_tombstones.md`.

## Mesure 7 — Présence et suggestions

Les `assert` de cohérence ont été exécutés **avant** le benchmark ; sinon un moteur pourrait paraître rapide simplement parce qu’il retourne un résultat faux ou incomplet.

| Accès | Moteur | p50 (ms) | p95 (ms) |
|---|---|---:|---:|
| B2a battement | PostgreSQL | 0.294 | 0.527 |
| B2a battement | Redis | 0.115 | 0.137 |
| B2b en ligne | PostgreSQL | 0.241 | 0.259 |
| B2b en ligne | Redis | 0.939 | 1.039 |
| B3 serveurs suggérés | PostgreSQL | 0.147 | 0.234 |
| B3 serveurs suggérés | Neo4j | 0.919 | 1.256 |
| B3bis amis d’amis | PostgreSQL | 0.452 | 0.672 |
| B3bis amis d’amis | Neo4j | 1.410 | 1.984 |

**Lecture du résultat :** Redis gagne sur les écritures de présence (0,115 ms p50 contre 0,294 ms), mais perd sur le nombre de membres en ligne (0,939 contre 0,241 ms p50), car l’implémentation doit récupérer un ensemble de membres puis interroger leurs clés de présence (`SMEMBERS` + `MGET`). PostgreSQL bénéficie d’une jointure locale. Neo4j est moins rapide sur les deux suggestions simples testées ; cela ne dit rien des graphes profonds à très grande échelle.

**TTL natif :** Redis a renvoyé une clé présente avec TTL 2 s à `t=0`, puis absente (`TTL=-2`) à `t=3 s`. PostgreSQL ne supprime pas physiquement une ligne de présence par TTL ; il faut filtrer sur `vu_le` et prévoir une tâche périodique de purge si l’on veut supprimer les lignes anciennes. La sortie indique **0 ligne enregistrée à cet instant**, ce qui ne prouve pas une purge automatique.

## Mesure 8 — Tableau intégral, `python bench.py --n 300`

Le tableau ci-dessous est la copie structurée des 29 lignes de la sortie utilisateur, avec les unités en **millisecondes**. Pour les métriques B3bis, le script utilise **30 répétitions**, contre 300 pour les autres accès ; tous les tests effectuent 10 appels d’échauffement.

| Cas | Moteur | p50 (ms) | p95 (ms) |
|---|---|---:|---:|
| B1 50 derniers, salon chaud | PostgreSQL | 0.141 | 0.227 |
| B1 50 derniers, salon chaud | Redis cache (TP1) | 0.117 | 0.130 |
| B1 50 derniers, salon chaud | MongoDB | 0.230 | 0.248 |
| B1 50 derniers, salon chaud | Cassandra | 1.289 | 3.069 |
| B1 50 derniers, salon chaud | Cassandra fenêtres | 5.880 | 8.353 |
| B1 50 derniers, salon moyen | PostgreSQL | 0.190 | 0.498 |
| B1 50 derniers, salon moyen | Redis cache (TP1) | 0.103 | 0.115 |
| B1 50 derniers, salon moyen | MongoDB | 0.228 | 0.252 |
| B1 50 derniers, salon moyen | Cassandra | 63.962 | 77.543 |
| B1 50 derniers, salon moyen | Cassandra fenêtres | 64.374 | 75.834 |
| B1 50 derniers, salon clairsemé | PostgreSQL | 0.197 | 0.578 |
| B1 50 derniers, salon clairsemé | Redis cache (TP1) | 0.110 | 0.120 |
| B1 50 derniers, salon clairsemé | MongoDB | 0.203 | 0.220 |
| B1 50 derniers, salon clairsemé | Cassandra | 90.181 | 110.618 |
| B1 50 derniers, salon clairsemé | Cassandra fenêtres | 12.040 | 14.878 |
| B2a battement | PostgreSQL | 0.294 | 0.527 |
| B2a battement | Redis | 0.115 | 0.137 |
| B2b en ligne | PostgreSQL | 0.241 | 0.259 |
| B2b en ligne | Redis | 0.939 | 1.039 |
| B3 serveurs suggérés | PostgreSQL | 0.147 | 0.234 |
| B3 serveurs suggérés | Neo4j | 0.919 | 1.256 |
| B3bis amis d’amis | PostgreSQL | 0.452 | 0.672 |
| B3bis amis d’amis | Neo4j | 1.410 | 1.984 |
| B4 activité serveur | PostgreSQL normalisé | 3.682 | 3.865 |
| B4 activité serveur | PostgreSQL vue | 0.151 | 0.223 |
| B4 activité serveur | MongoDB | 2.183 | 2.336 |
| B4 activité serveur | Redis cache (TP1) | 0.134 | 0.234 |
| H5 appartenance simple | PostgreSQL | 0.118 | 0.130 |
| H5 appartenance simple | Redis | 0.097 | 0.108 |

### Synthèse et limites

- **Hypothèses du TP1 :** confrontées aux résultats et classées dans `DOSSIER_ARCHI.md` §6. La rapidité d’un cache ne suffit pas à le rendre fiable comme source des permissions.
- **Limite 1 (volume) :** 300 000 messages, index et données souvent en cache, versus les 100 millions+ de l’article. On ne teste pas la saturation mémoire et les entrées/sorties disque de MongoDB.
- **Limite 2 (charge) :** tests principalement séquentiels sur localhost, sans dizaines de milliers d’utilisateurs simultanés ni réseau entre nœuds.
- **Limite 3 (nature et configuration) :** une seule machine Docker, partitions simulées et moteur non réglé pour la production ; les résultats peuvent s’inverser avec réplication, compaction, cache froid et suppressions réelles.

Le **p95** expose les requêtes les plus lentes du lot mieux qu’une moyenne. L’**échauffement** réduit la part des connexions initiales et caches froids, mais rend aussi ces mesures moins comparables à la lecture très aléatoire et hors cache décrite dans [A1]. Le seuil p95 API de **80 ms** cité par Discord [A1] ne correspond pas directement aux latences d’un pilote local mesurées ici.

**Sources :** TP1/TP2 fournis, `data/generate_data.py`, scripts SQL/Python du présent dossier et fichiers sous `preuves/`. Toutes les performances sont issues du Terminal utilisateur du 13 novembre 2026.
