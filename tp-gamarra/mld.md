# MLD — modèle logique utilisé au TP2

- `UTILISATEUR`(**id**, pseudo, email UNIQUE, cree_le)
- `SERVEUR`(**id**, nom, proprietaire_id → UTILISATEUR.id, cree_le, nb_membres)
- `SALON`(**id**, serveur_id → SERVEUR.id, nom, type, cree_le, UNIQUE(serveur_id,nom))
- `MEMBRE`(**utilisateur_id** → UTILISATEUR.id, **serveur_id** → SERVEUR.id, role, rejoint_le)
- `MESSAGE`(**id** BIGINT Snowflake, salon_id → SALON.id, auteur_id → UTILISATEUR.id, contenu, envoye_le, modifie_le NULL, pieces_jointes JSONB NULL)
- `AMITIE`(**utilisateur_a** → UTILISATEUR.id, **utilisateur_b** → UTILISATEUR.id, depuis, CHECK(utilisateur_a < utilisateur_b))
- `PRESENCE`(**utilisateur_id** → UTILISATEUR.id, vu_le)
- `ACTIVITE_SERVEUR_JOUR`(serveur_id, jour, nb_messages, nb_auteurs) : **vue matérialisée** dérivée des messages.

`SERVEUR.nb_membres` est une dénormalisation volontaire, tenue par trigger. Les tables source restent normalisées et PostgreSQL demeure le propriétaire des données métier.

Le MPD exécutable avec types et index justifiés est `sql/01_schema.sql`.
