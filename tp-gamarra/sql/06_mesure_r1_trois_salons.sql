-- Complément facultatif de la Mesure 2 : R1 pour les trois salons, AVEC pseudo auteur.
\timing on
-- Choix correspondant à MESURES.md : chaud 775, moyen 424, clairsemé 340.
SELECT m.id,m.contenu,m.envoye_le,u.pseudo FROM app.message m JOIN app.utilisateur u ON u.id=m.auteur_id
WHERE m.salon_id=775 ORDER BY m.id DESC LIMIT 50;
SELECT m.id,m.contenu,m.envoye_le,u.pseudo FROM app.message m JOIN app.utilisateur u ON u.id=m.auteur_id
WHERE m.salon_id=424 ORDER BY m.id DESC LIMIT 50;
SELECT m.id,m.contenu,m.envoye_le,u.pseudo FROM app.message m JOIN app.utilisateur u ON u.id=m.auteur_id
WHERE m.salon_id=340 ORDER BY m.id DESC LIMIT 50;
