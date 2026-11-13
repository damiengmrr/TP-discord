# Architecture du TP2 — implantée et cible

```mermaid
flowchart TB
  API[Application et requêtes de test]
  PG[(PostgreSQL 16\nSource de vérité\nutilisateurs / serveurs / membres / messages / amitiés)]
  MV[(Vue activité quotidienne\nrafraîchissement manuel)]
  MD[(MongoDB 7\ncopie messages 2015)]
  CS[(Cassandra 4.1\ncopie messages 2017\nfenêtres de 10 jours)]
  RD[(Redis 7\nprésence TTL 300 s\nensemble des membres)]
  NEO[(Neo4j 5\ncopie graphe social)]
  API -->|écritures métier / SQL| PG
  PG -->|agrégat SQL / REFRESH| MV
  PG -.->|lot Python load_nosql.py| MD
  PG -.->|lot Python load_nosql.py| CS
  PG -.->|chargement initial des membres| RD
  PG -.->|lot Python load_nosql.py| NEO
  API -->|heartbeat direct TP| RD
  API -->|lectures comparées| MD
  API -->|lectures comparées| CS
  API -->|lectures comparées| NEO
  API -->|lectures comparées| MV
```

**Implémenté :** répliques reconstruites par le script du TP. Les écritures de présence sont testées séparément dans PostgreSQL et Redis pour comparer B2a. Le flux n'est **pas** une synchronisation de production en continu.

**Si la plateforme passait en production :** événements de changement fiables via outbox transactionnelle et consommateur idempotent, surveillance du retard des copies, règles de reconstruction après incident. Aucune double écriture non contrôlée dans l'application.

**Version minimale retenue au TP1 et maintenue provisoirement :** PostgreSQL + Redis. Cassandra, MongoDB et Neo4j sont des moteurs *candidats évalués* dans le TP2, pas un choix de production automatique.
