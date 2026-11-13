# DOSSIER_ARCHI.md — Architecture de données Discord (version 2)

**Gamarra Damien · Bachelor 3 Ynov Montpellier · Conception et architecture des données · TP1 + TP2, novembre 2026**

Ce dossier reprend la direction retenue au TP1 : **PostgreSQL** comme source de vérité pour les données métier et les messages, **Redis** pour les présences temporaires et des caches ciblés. Le TP2 a construit la base, comparé les moteurs sur les mêmes données et mesuré les requêtes sur le Mac de l’étudiant, le 13 novembre 2026. Les mesures et leurs limites figurent dans `MESURES.md` ; les chiffres historiques de Discord restent distingués des hypothèses [H]. Les schémas sont dans `mcd.md`, `mld.md` et `architecture.md`.

## 0. Résumé du cas en cinq lignes

1. Discord a dû gérer des volumes massifs de messages, avec de fortes différences d'activité entre ses salons [A1].
2. MongoDB a commencé à présenter des latences imprévisibles lorsque messages et index ont dépassé la mémoire disponible [A1].
3. Cassandra a permis de répartir les messages par salon et fenêtres temporelles, mais a introduit des difficultés avec les tombstones et partitions chaudes [A1, A2].
4. L'architecture doit garantir les droits d'écriture, la cohérence des relations et l'expiration de la présence.
5. Pour notre version miniature, nous conservons une architecture simple, puis nous la testons avant d'ajouter des moteurs spécialisés.

## 1. Ce que le système doit garantir

### 1.a. Acteurs, objets et cycles de vie

Un utilisateur crée un compte, rejoint ou quitte un serveur, envoie/édite un message dans un salon textuel, se connecte et ajoute des amis. Le propriétaire crée un serveur et ses salons, et attribue les rôles. Le système met à jour les présences et produit les statistiques quotidiennes.

Glossaire : **utilisateur** (compte), **serveur** (communauté), **salon** (espace texte/vocal), **membre** (lien utilisateur-serveur), **propriétaire** (responsable du serveur), **modérateur** (rôle de gestion), **message** (publication persistante), **amitié** (lien bidirectionnel unique), **présence** (signal temporaire d'activité), **Snowflake** (identifiant de message qui permet un tri chronologique).

### 1.b. Règles de gestion

| Garantie par le modèle/contrainte SQL | Par trigger ou logique applicative | Stockage spécialisé éventuel |
|---|---|---|
| Email unique et champs obligatoires | Propriétaire obligatoirement membre avec rôle propriétaire | Présence avec TTL 300 s : Redis |
| Clés étrangères des serveurs, salons et messages | Un message est envoyé uniquement dans un salon textuel | Relations sur plusieurs sauts : Neo4j candidat |
| Nom de salon unique par serveur | Auteur membre du serveur au moment d'écrire | Historique massif : Cassandra candidat |
| Rôles limités à propriétaire/modérateur/membre | Décrémenter/incrémenter `nb_membres` | Pièces jointes variables : JSONB dans PostgreSQL |
| Amitié canonique `utilisateur_a < utilisateur_b` | Rafraîchir quotidiennement les statistiques | Cache ciblé : Redis |

Les triggers SQL exécutables sont dans `sql/01_schema.sql`. Les droits sont **aussi vérifiés dans l'API** en production, mais seule la vérification au niveau base protège également contre un autre client d'écriture. Aucun message ne peut arriver dans un salon vocal. Pour le retrait d'un propriétaire, une mutation coordonnée de la propriété du serveur est nécessaire.

### 1.c. MCD

Voir `mcd.md`. Le rôle est **un attribut de l'association** `MEMBRE` : c'est le rôle d'une personne *dans un serveur* et non sur tous les serveurs. Les amitiés ne sont insérées qu'une fois par paire ordonnée. La propriété du serveur est conservée dans `SERVEUR.proprietaire_id`, avec contrôle différé de la cohérence avec `MEMBRE`. Les pièces jointes sont dans un attribut JSONB car image, fichier et lien n'ont pas la même structure. Les messages ont leur propre identité Snowflake (BIGINT).

### 1.d. MLD et MPD

Voir `mld.md` et `sql/01_schema.sql`. La table `MEMBRE` résout la relation plusieurs-à-plusieurs entre `UTILISATEUR` et `SERVEUR`. L'amitié réflexive devient `AMITIE` à clé composée. Le message contient deux clés étrangères (`salon_id`, `auteur_id`). Les index sur les clés étrangères sont ajoutés explicitement lorsque la requête en a besoin ; PostgreSQL n'en crée pas automatiquement.

Index décisifs : `message(salon_id, id DESC)` pour lire les 50 derniers sans OFFSET ; `membre(serveur_id, utilisateur_id)` et sa PK inverse pour vérifier les appartenances ; `amitie(utilisateur_b, utilisateur_a)` pour parcourir le graphe social dans les deux sens ; index unique de la vue `(serveur_id,jour)` pour le tableau de bord et son rafraîchissement concurrent.

### 1.e. Questions à poser au client avant la production

1. Un ancien propriétaire peut-il rester simple membre après un transfert ? Cela change le parcours de transfert du rôle, pas le MCD.
2. Un message peut-il être modifié après avoir quitté le serveur ? La règle de permission d'édition doit alors être explicitée.
3. Faut-il conserver les pièces jointes lourdes dans une base ou uniquement leurs métadonnées et un lien vers un stockage objet ?
4. L'utilisateur peut-il masquer sa présence à certains serveurs ? Les clés et autorisations Redis doivent alors être adaptées.
5. Combien de temps doit-on conserver les messages supprimés pour la conformité, la modération et la restauration ? Cela change la stratégie de purge et les tombstones.

## 2. Qui interroge quoi et quelle charge

### 2.a. Accès critiques

*Les fréquences exactes d'une vraie plateforme ne sont pas fournies : sauf la lecture/écriture des messages proche de 50/50 [A1], les qualificatifs ci-dessous sont des hypothèses.*

| Accès | Nature | Fréquence supposée | Objectif/forme | Cohérence |
|---|---|---|---|---|
| Envoyer un message | Écriture | Très élevée | Création par clé, contrôles FK | Stricte |
| 50 derniers messages d'un salon | Lecture | Très élevée | Plage ordonnée sur Snowflake | Forte |
| Vérifier le droit d'écrire | Lecture | À chaque message | Jointure/EXISTS indexé | Stricte |
| Modifier/supprimer un message | Écriture | Plus faible | Point par ID | Stricte |
| Battement de présence | Écriture | Répétée par utilisateur en ligne | Clé avec TTL 300 s | Éphémère |
| Nombre de membres en ligne | Lecture | Fréquente | Ensemble + présence / jointure | Retard de quelques secondes toléré |
| Suggestions de serveurs | Lecture | À l'ouverture | 2 sauts + regroupement | Léger retard toléré |
| Amis d'amis | Lecture | Occasionnelle | Parcours de relations | Léger retard toléré |
| Activité par jour | Lecture | Dashboard | Agrégat | Rafraîchissement quotidien suffisant |
| Chercher dans l'historique | Lecture | Variable | Recherche texte, non implémentée au TP2 | Forte |

### 2.b. Volumétrie (calculs à partir des hypothèses fournies [H])

- **Décembre 2016 [A1] :** 100 000 000 / 86 400 = **1 157,4 messages/s en moyenne** ; pic H2 ×3 ≈ **3 472,2 messages/s**.
- **H1 = 300 octets/message :** 100 000 000 × 300 = **30 Go par jour** (décimaux) et 30 × 365 ≈ **10,95 To par an**, sans index ni réplication.
- **100 millions de messages [H1, H3] :** données ≈ **30 Go**, index ≈ 100M × 40 o = **4 Go**, soit au minimum **34 Go** contre **16 Go de RAM [H4]**. Les index peuvent tenir en mémoire, mais pas toutes les données lues aléatoirement.
- **Cassandra [A1, H1] :** 12 nœuds × 1 To compressé / réplication 3 ≈ **4 To logiques**. À 300 o/message, cela représenterait de l'ordre de **13,3 milliards de messages**, estimation simplifiée qui ignore compression et surcoûts.

### 2.c. Dénormaliser sur une contrainte

| Besoin | Technique | Gain en lecture | Coût / risque | Garde-fou |
|---|---|---|---|---|
| Compter les membres | `serveur.nb_membres` | Pas de `COUNT(*)` à chaque écran | Écriture de compteur sur ajout/retrait ; contention | Trigger + requête de réconciliation |
| Dashboard par jour | Vue matérialisée `activite_serveur_jour` | Pas d'agrégation à chaque ouverture | Fraîcheur limitée à la dernière actualisation | Rafraîchissement quotidien suivi et vérifié |
| 50 messages déjà populaires | Cache Redis **optionnel** | Pas d'accès à PostgreSQL sur hit | Invalidation après nouveau message ; donnée périmée | TTL court et invalidation déclenchée par événement |

Nous **refusons de dénormaliser les droits d'écriture** en simple cache Redis : vérifier le droit sur une copie potentiellement périmée laisserait écrire une personne expulsée.

## 3. Où vivent les messages et pourquoi

### 3.a. Pourquoi MongoDB a rencontré ses limites en 2015

[A1] Une collection unique stockait les messages avec un index composé par salon et date. Lorsque l'ensemble ne tenait plus en mémoire, les lectures aléatoires provoquaient davantage d'entrées/sorties disque. Un salon peu actif constitue un mauvais cas : ses anciennes pages sont peu susceptibles d'être en cache. MongoDB n'est pas intrinsèquement mauvais ; le **volume réel et la configuration** ont créé cette difficulté.

### 3.b. Comparaison pour « les 50 derniers messages »

| Moteur | Lecture principale | Hors RAM et croissance | Limite importante |
|---|---|---|---|
| PostgreSQL | Index `(salon_id,id DESC)`, jointure auteur | Pages index+données, partitionnement possible | Coût de maintenance, montée en charge plus complexe |
| MongoDB | `find` par salon + index composé, document complet | Jeu de données/index peut dépasser RAM ; sharding existe | Risque d'accès aléatoire coûteux à grand volume |
| Cassandra | Clé `(salon,bucket)` + tri Snowflake décroissant | Partitions bornées et répartition sur nœuds | Fenêtres vides, tombstones, requêtes prédéfinies |
| Redis | Cache des 50 messages récents | Très rapide sur hit, mais RAM coûteuse | Cache non canonique, expiration et invalidation |

### 3.c. Partition Cassandra

Avec un salon de **10 millions de messages/an** et H1 = 300 octets :

| Clé de partition | Taille théorique d'une partition (moyenne) | Lecture de 50 msg d'un salon à 1 000 msg/an |
|---|---:|---|
| A : salon entier | 10M × 300 o = **3 000 Mo** | Une partition, mais énorme dans le temps |
| B : salon + 10 jours | (10M / 365 × 10) × 300 ≈ **82,2 Mo** | Environ 2 fenêtres si activité régulière |
| C : salon + 1 jour | (10M / 365) × 300 ≈ **8,2 Mo** | Environ 19 jours si activité régulière |

Avec une moyenne par jour plus faible, le choix C multiplie les partitions à consulter. Avec B, la taille moyenne approche mais reste en dessous de la limite de 100 Mo citée dans l'article [A1] **sous H1** ; les vrais pics peuvent dépasser la moyenne. Le TP2 utilise B (fenêtre **10 jours**, fonction `bucket_de` fournie). Snowflake évite les collisions possibles entre deux horodatages identiques et permet le tri par ID. Le correctif `fenetres_non_vides` évite des lectures inutiles au prix de métadonnées à maintenir.

### 3.d. Quatre modes de défaillance

- **NULL dans Cassandra :** écritures NULL créent des tombstones [A1]. Garde-fou : `UNSET_VALUE` pour champ absent, pas un NULL envoyé.
- **Millions de suppressions :** accumulation de tombstones à parcourir avant un ancien message [A1]. Garde-fou : suppression par partition quand possible, suivi du volume de marqueurs, compaction/réparation sûres.
- **Partition chaude :** un salon très actif surcharge certains nœuds, surtout si les lectures attendent plusieurs réplicas [A2]. Garde-fou : surveiller taille et QPS par partition, évaluer le découpage et le niveau de cohérence.
- **Garbage collector Cassandra :** pauses JVM qui perturbent les p95/p99 [A2]. Garde-fou : surveiller GC, latence et compaction, tester les réglages sous charge.

## 4. Architecture retenue et ajustements du TP2

### 4.a. Quelle donnée vit où ?

| Besoin | Propriétaire | Copies évaluées | Pourquoi |
|---|---|---|---|
| Comptes/serveurs/salons/membres | PostgreSQL | Ensembles Redis, relations Neo4j | Transactions, clés et unicité |
| Messages, auteurs, attachments | PostgreSQL | MongoDB et Cassandra | Source unique, historique B1 sur index |
| Vérification du droit d'écrire | PostgreSQL | Aucune copie autoritaire | Cohérence stricte |
| Présence éphémère | Redis | PostgreSQL pour comparer B2 | TTL 5 min sans job de suppression |
| Amitiés/recommandations | PostgreSQL | Neo4j | Relationalité simple au début, graphe candidat |
| Dashboard quotidien | PostgreSQL | Vue matérialisée, cache Redis facultatif | Rafraîchissement 1 fois/jour suffisant |

**Important :** durant le TP, la présence est volontairement écrite dans les deux moteurs pour mesurer B2a. En production, il faut choisir un propriétaire clair de la présence (ici Redis pour l'état courant), éviter une double écriture fragile et conserver la possibilité de reconstruire les copies métiers depuis PostgreSQL.

### 4.b. Schéma et synchronisation

Voir `architecture.md`. Dans **l'implémentation du TP2**, `load_nosql.py` copie les données depuis PostgreSQL **par lot**, pas par événement temps réel. Redis et Neo4j sont reconstruits depuis la source SQL. Un vrai déploiement exigerait une outbox ou CDC et des consommateurs idempotents pour diffuser les changements, avec alerte de retard.

### 4.c. Trois décisions (TP1 repris)

**Décision 1 — PostgreSQL pour 300 000 messages.** Contexte : taille miniature, requêtes B1 et R3, besoin de transactions. MongoDB et Cassandra sont évalués, mais le coût d'exploiter Cassandra et la complexité d'une migration ne se justifient pas sans preuve de saturation. Risques : table croissante, lectures aléatoires quand les données dépassent RAM. Changer d'avis si p95 sous charge réelle dépasse durablement **80 ms** ou si le débit/saturation mémoire pose problème après optimisation.

**Décision 2 — Redis pour la présence (TTL 5 minutes).** La suppression automatique répond exactement à la règle métier, contrairement à PostgreSQL qui conserve la ligne tant qu'un job ne la purge pas. Risques : perte de cache au redémarrage, cohérence de l'affichage des présences, coût du deuxième moteur. À vérifier : B2a et B2b, p50/p95 et disparition d'une clé expirée.

**Décision 3 — Permissions dans PostgreSQL, modèle normalisé.** Les relations utilisateur/serveur restent des tables à clés, la présence du propriétaire et les messages textuels sont contrôlés par triggers. Le cache de permissions est écarté pour éviter les droits périmés. Coût : vérification indexée à chaque insertion de message. Ajouter un cache de permission uniquement si la mesure R2 révèle un goulot, avec stratégie d'invalidation sûre.

### 4.d. Risque principal : copies qui divergent

Exemple : un utilisateur quitte un serveur dans PostgreSQL, mais l'ensemble `membres:<serveur>` dans Redis n'est pas mis à jour. L'interface le montre encore membre, et des recommandations dérivées deviennent fausses. **Dommage maximal évité :** Redis ne doit jamais autoriser à lui seul l'écriture de messages. Détection par comptage/échantillonnage périodique des appartenances entre SQL/Redis et suivi du délai de synchronisation. Réparation : reconstruire l'ensemble Redis du serveur depuis PostgreSQL (idempotent), puis rejouer les événements manqués si un flux existe.

### 4.e. Version minimale pour deux moteurs

**PostgreSQL + Redis**, inchangé provisoirement : PostgreSQL prend messages, relations, règles, statistiques et pièces jointes JSONB ; Redis gère la présence et éventuellement quelques caches. Des requêtes SQL sur deux niveaux suffisent au jeu miniature pour les suggestions. Ajouter Cassandra ou ScyllaDB seulement si l'historique devient très volumineux et que le p95 ou la taille des partitions/IO restent problématiques après index, cache et optimisation. Neo4j seulement si la profondeur et la complexité des parcours sociaux dépassent ce qu'une requête SQL raisonnable peut offrir. Les mesures du TP2 confortent ce choix : PostgreSQL B1 salon chaud **0,141 ms p50** ; Redis B2a **0,115 ms p50**, avec expiration native. Neo4j et Cassandra ne gagnent pas sur les accès simples de ce jeu. Les seuils **hypothétiques** restent à valider sous charge ; le seuil p95 API **80 ms** est cité par [A1] et n'est pas une performance mesurée par notre TP.

## 5. Les cinq hypothèses falsifiables du TP1

On conserve les prédictions du dossier de conception, même lorsqu'elles ne sont pas confirmées ; il faut préciser la requête et le résultat concret mesuré.

| # | Hypothèse prévue au TP1 | Facteur prédit | Comment vérifier au TP2 | Si l'hypothèse est fausse |
|---|---|---|---|---|
| H1 | Redis cache des 50 derniers messages plus rapide que PostgreSQL | Environ 3× | B1 PostgreSQL vs `Redis cache (TP1)` | Le coût du cache et de son invalidation pourrait ne pas se justifier |
| H2 | Redis plus rapide que PostgreSQL pour mettre à jour la présence | Environ 2× | B2a heartbeat | La simplicité de SQL pourrait l'emporter malgré l'absence de TTL natif |
| H3 | PostgreSQL plus efficace que Neo4j sur les amis d'amis simples | Avantage attendu PG (ordre de grandeur à valider) | B3bis | Un graphe pourrait devenir intéressant plus tôt que prévu |
| H4 | Redis cache des statistiques quotidiennes plus rapide que la lecture relationnelle | Environ 2× | B4 Redis cache vs vue PostgreSQL et requête normalisée | Une vue matérialisée suffit sans ajouter ce cache |
| H5 | Redis plus rapide pour le simple test d'appartenance | Environ 2× | B5 `SISMEMBER` vs SQL `EXISTS` | Conserver SQL pour sa cohérence ; ne pas déplacer les autorisations |

Ces facteurs sont des **prédictions**, pas des résultats. H1 et H4 dépendent d'un cache préalimenté ; B5 ne constitue pas la permission complète R2. Il faut prendre en compte leur coût d'invalidation pour décider réellement.

## 6. Bilan du TP2 : prédictions contre mesures

**Contexte :** p50 et p95 en **ms**, sur un **MacBook Pro Apple M3 Pro (36 Go RAM, macOS 26.5.1)** avec moteurs Docker et appels locaux (RAM effective attribuée à Docker non relevée). Les chiffres viennent du tableau intégral de `MESURES.md`, Mesure 8 ; ils ne représentent pas une plateforme Discord en production. Pour comparer des facteurs, on retient d’abord le **p50**, en signalant le p95. Les prédictions ci-dessous sont conservées telles que formulées au TP1.

| # | Prédiction du TP1 | Valeur mesurée (p50 / p95, ms) | Verdict | Mécanisme / explication |
|---|---|---|---|---|
| H1 | Redis cache ≈ **3×** plus rapide que PostgreSQL pour les 50 derniers messages | Salon chaud : PG **0,141 / 0,227** ; Redis **0,117 / 0,130** ; ≈ **1,21×** au p50 | **Infirmée sur le facteur ×3** (mais Redis légèrement gagnant) | PostgreSQL utilise déjà un index efficace ; le cache évite SQL mais doit être rempli et invalidé. Sur le salon moyen : ≈ 1,84× ; clairsemé : ≈ 1,79× p50, sans facteur stable de 3. |
| H2 | Redis ≈ **2×** plus rapide pour le battement de présence | PG **0,294 / 0,527** ; Redis **0,115 / 0,137** ; ≈ **2,56×** au p50 | **Confirmée (ordre de grandeur)** | `SET EX 300` par clé est peu coûteux ; PostgreSQL effectue un `UPSERT` transactionnel. Redis ajoute un TTL automatique. |
| H3 | PostgreSQL gagne pour les amis d’amis simples | PG **0,452 / 0,672** ; Neo4j **1,410 / 1,984** ; PG ≈ **3,12×** plus rapide au p50 | **Confirmée pour ce jeu** | Parcours limité à deux sauts et index SQL utiles ; Neo4j supporte le coût de la traversée et de son pilote, sans bénéficier d’une grande profondeur ici. |
| H4 | Redis ≈ **2×** plus rapide pour le tableau de bord | PG normalisé **3,682 / 3,865** ; vue PG **0,151 / 0,223** ; Redis **0,134 / 0,234** | **Confirmée vs normalisé, infirmée vs vue matérialisée pour ×2** | Le cache Redis surclasse l’agrégation brute, mais sa lecture est seulement **1,13×** plus rapide que la vue au p50, et légèrement plus lente au p95 ; coût d’invalidation du cache. |
| H5 | Redis ≈ **2×** plus rapide pour l’appartenance simple | PG **0,118 / 0,130** ; Redis **0,097 / 0,108** ; ≈ **1,22×** au p50 | **Infirmée sur le facteur ×2** | `SISMEMBER` évite la requête SQL, mais l’index PostgreSQL est déjà très rapide. Une copie Redis peut être périmée ; la permission d’écriture complète reste dans SQL. |

**Vérification supplémentaire de R1 :** la même requête avec pseudo de l’auteur a été exécutée sur les trois salons (775 : 50 messages, **2,262 ms** ; 424 : 50 messages, **0,648 ms** ; 340 : 2 messages, **0,195 ms**). Il s'agit de durées ponctuelles `psql`, distinctes des centiles du benchmark B1.

**Autres constats mesurés :** B2b (membres en ligne) est plus rapide avec PostgreSQL (**0,241 ms p50**) qu’avec Redis (**0,939 ms**) ; suggestions de serveurs B3 : PostgreSQL **0,147 ms** contre Neo4j **0,919 ms**. Cassandra ne gagne pas sur l’historique B1 à ce volume : le salon clairsemé atteint **90,181 ms p50** sans suivi des fenêtres, réduit à **12,040 ms** avec le correctif. L’incident de **119 999 suppressions** a reproduit `READ_TOO_MANY_TOMBSTONES` ; les deux réparations du TP ont été prouvées (voir Mesure 4 complémentaire et runbook).

**Les trois limites qui pourraient changer la conclusion :** (1) 300 000 messages au lieu de centaines de millions avec dépassement de RAM ; (2) absence de concurrence massive et de réseau multi-nœuds ; (3) moteurs, caches et partitions simulés sur une seule machine, sans vraie réplication ni charge durable. Le **p95** fait apparaître les lenteurs des 5 % d’appels les plus lents que la moyenne masque ; l’échauffement stabilise la mesure mais favorise les caches chauds et ne reproduit pas les lectures aléatoires hors RAM de Discord.

**Décisions révisées :**

1. **PostgreSQL source de vérité : maintenue.** R1 et B1 restent efficaces à cette taille, les règles métier sont contrôlées, et la vue matérialisée multiplie le débit de lecture du dashboard. Réévaluer après des tests 100 M+ messages, p95 sous charge, mémoire et latence disque.
2. **Redis pour la présence : maintenue**, grâce au TTL natif et à B2a ; **cache des 50 messages / dashboard : optionnel et non justifié automatiquement**, car le gain sur l’index ou la vue reste faible et impose l’invalidation. Mesurer son taux de hit et le coût d’invalidation en production.
3. **Permissions PostgreSQL et données normalisées : maintenues.** L’optimisation `SISMEMBER` n’apporte pas le facteur 2 prédit et ne suffit pas pour une autorisation cohérente. Les requêtes R2 et les triggers protègent l’intégrité.

**Verdict avec deux moteurs financés : PostgreSQL + Redis**, comme dans le TP1. Ne pas ajouter Cassandra, MongoDB ou Neo4j au seul vu de ces mesures locales. Nouveaux signaux pour réexaminer : p95 API > **80 ms** (seuil historique Discord [A1], à adapter), saturations RAM/IO, dépassement durable des objectifs métier et complexité réelle des parcours à plusieurs niveaux. Non testés ici : concurrence, réplication, durée de vie des données, incidents multi-nœuds, coût opérationnel et retards de synchronisation.

## Sources

- **[A1]** Discord, *How Discord Stores Billions of Messages*, 13 janvier 2017, <https://discord.com/blog/how-discord-stores-billions-of-messages>.
- **[A2]** Discord, *How Discord Stores Trillions of Messages*, 6 mars 2023, <https://discord.com/blog/how-discord-stores-trillions-of-messages>.
- **[H]** Hypothèses H1 à H5 du dossier documentaire fourni, pas des données mesurées par Discord.
- **TP1** : compte rendu et schémas originaux du dépôt <https://github.com/damiengmrr/TP-discord>.
- **TP2** : `TP2.pdf`, `Cours2.pdf`, `Documentation-discordtp2.pdf` et ressources de code du professeur.
