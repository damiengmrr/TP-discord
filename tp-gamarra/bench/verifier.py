"""Mesure 5 : réconciliation entre PostgreSQL, MongoDB et Cassandra, sans SELECT count(*) Cassandra.

Usage : depuis bench/: python verifier.py
Cassandra : lecture par pages client de chaque fenêtre répertoriée, ce qui est coûteux à dessein.
"""
from collections import Counter
from common import mongo_db, pg_conn, cassandra_session

pg=pg_conn()
expected=pg.execute('SELECT count(*) FROM app.message').fetchone()[0]
if expected == 0:
    raise SystemExit('PostgreSQL est vide : exécuter sql/02_chargement.sql avant les vérifications.')
mdb=mongo_db()
actual_mongo=mdb.messages.count_documents({})
cs=cassandra_session('discord')
seen=0
salon_counts=Counter()
windows=0
# On lit toutes les fenêtres connues de tous les salons, sans count(*) distribué.
# Nécessite la table d'index des fenêtres, tenue au chargement.
for (salon,) in pg.execute('SELECT id FROM app.salon'):
    for (bucket,) in cs.execute('SELECT bucket FROM fenetres_non_vides WHERE salon_id=%s', (salon,)):
        windows += 1
        for row in cs.execute('SELECT message_id FROM messages_par_salon WHERE salon_id=%s AND bucket=%s', (salon,bucket)):
            seen += 1
            salon_counts[salon] += 1
print('PostgreSQL:',expected,'MongoDB:',actual_mongo,'Cassandra relu:',seen,'fenêtres:',windows)
assert expected==actual_mongo==seen, 'Une migration est incomplète : nombre différent'
for salon, n in pg.execute('SELECT salon_id,count(*) FROM app.message GROUP BY salon_id'):
    assert salon_counts[salon]==n,(salon,n,salon_counts[salon])
print('Mesure 5a : OK, décomptes et salons réconciliés')
cs.shutdown()
pg.close()
