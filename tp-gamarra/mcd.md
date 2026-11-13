# MCD — Plateforme Discord miniature

Le MCD de départ est repris et précisé pour le TP2. Le propriétaire est aussi un membre du serveur ; cette règle supplémentaire est contrôlée en SQL par trigger différé. Les pièces jointes ont une structure variable (JSONB).

```mermaid
erDiagram
    UTILISATEUR ||--o{ MEMBRE : "rejoint"
    SERVEUR ||--|{ MEMBRE : "accueille"
    UTILISATEUR ||--o{ SERVEUR : "possede"
    SERVEUR ||--|{ SALON : "contient"
    SALON ||--o{ MESSAGE : "recoit si texte"
    UTILISATEUR ||--o{ MESSAGE : "ecrit"
    UTILISATEUR ||--o| PRESENCE : "a"
    UTILISATEUR ||--o{ AMITIE : "personne A"
    UTILISATEUR ||--o{ AMITIE : "personne B"
    UTILISATEUR {
        int id PK
        string pseudo
        string email UK
        datetime cree_le
    }
    SERVEUR {
        int id PK
        string nom
        int proprietaire_id FK
        int nb_membres
    }
    SALON {
        int id PK
        int serveur_id FK
        string nom
        string type
    }
    MEMBRE {
        int utilisateur_id PK,FK
        int serveur_id PK,FK
        string role
        datetime rejoint_le
    }
    MESSAGE {
        bigint id PK
        int salon_id FK
        int auteur_id FK
        string contenu
        datetime envoye_le
        json pieces_jointes
    }
    AMITIE {
        int utilisateur_a PK,FK
        int utilisateur_b PK,FK
        datetime depuis
    }
    PRESENCE {
        int utilisateur_id PK,FK
        datetime vu_le
    }
```

**Cardinalités importantes :** un message a un seul auteur et un seul salon ; chaque salon appartient à un serveur ; une personne peut être membre de plusieurs serveurs. Un serveur a exactement un propriétaire, présent dans `MEMBRE` avec le rôle `proprietaire`. Une amitié est symétrique et stockée une seule fois avec `utilisateur_a < utilisateur_b`.

**Règle non exprimable par simple FK :** seul un membre peut écrire dans un salon **textuel** ; vérification au moment de l'insertion du message. La présence expire en Redis au bout de 300 secondes, et doit être filtrée/purgée côté PostgreSQL.
