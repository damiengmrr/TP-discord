"""Réplique les données PostgreSQL (source de vérité) vers MongoDB, Cassandra, Redis et Neo4j.

Usage : depuis bench/: python load_nosql.py [--sans-cassandra]
Les accusés de réception Cassandra ne remplacent pas la vérification de relecture (voir verifier.py).
"""
import argparse
import json
import random

from cassandra import ConsistencyLevel
from cassandra.concurrent import execute_concurrent_with_args
from cassandra.query import UNSET_VALUE
from pymongo import ASCENDING, DESCENDING
from common import bucket_de, cassandra_session, mongo_db, neo_driver, pg_conn, redis_conn

ap = argparse.ArgumentParser()
ap.add_argument('--sans-cassandra', action='store_true')
args = ap.parse_args()
pg = pg_conn()
nb_messages_source = pg.execute('SELECT count(*) FROM app.message').fetchone()[0]
if nb_messages_source == 0:
    raise SystemExit('PostgreSQL app.message est vide : corriger le trigger puis relancer sql/02_chargement.sql.')
# Vérification d'accès AVANT de vider MongoDB et les autres copies.
if not args.sans_cassandra:
    try:
        preflight_cs = cassandra_session()
        preflight_cs.execute('SELECT release_version FROM system.local')
        preflight_cs.shutdown()
    except Exception as exc:
        raise SystemExit('Cassandra non prête. Lancer python wait_for_cassandra.py depuis bench/, puis réessayer.') from exc
print(f'PostgreSQL source : {nb_messages_source} messages ; migration démarrée.')


def lots(curseur, taille):
    while True:
        rows = curseur.fetchmany(taille)
        if not rows:
            break
        yield rows


# MongoDB 2015 : une collection de documents autonomes, index composée (salon, Snowflake).
mdb = mongo_db()
collection = mdb.messages
collection.delete_many({})
collection.create_index([('salon_id', ASCENDING), ('_id', DESCENDING)], name='salon_messages_recents')
collection.create_index([('serveur_id', ASCENDING), ('envoye_le', ASCENDING)], name='activite_serveur_date')
pg_mongo = pg_conn()
pg_mongo.autocommit = False  # un curseur serveur PostgreSQL nécessite une transaction
count_mongo = 0
with pg_mongo.cursor(name='stream_mongo') as cur:
    cur.execute('''SELECT m.id,m.salon_id,s.serveur_id,m.auteur_id,m.contenu,m.envoye_le,
                          m.modifie_le,m.pieces_jointes
                   FROM app.message m JOIN app.salon s ON s.id=m.salon_id ORDER BY m.id''')
    for block in lots(cur, 4000):
        docs = []
        for mid, salon, serveur, auteur, contenu, envoye, modifie, pieces in block:
            d = {'_id': mid, 'salon_id': salon, 'serveur_id': serveur,
                 'auteur_id': auteur, 'contenu': contenu, 'envoye_le': envoye}
            if modifie is not None:
                d['modifie_le'] = modifie
            if pieces is not None:
                d['pieces_jointes'] = pieces
            docs.append(d)
        collection.insert_many(docs, ordered=False)
        count_mongo += len(docs)
pg_mongo.close()
print(f'mongo     : {count_mongo} documents, count_documents={collection.count_documents({})}')


# Cassandra 2017 : un message par (salon, fenêtre de 10 jours, Snowflake).
if not args.sans_cassandra:
    cs = cassandra_session()
    cs.execute("CREATE KEYSPACE IF NOT EXISTS discord WITH replication = {'class':'SimpleStrategy','replication_factor':1}")
    cs.set_keyspace('discord')
    cs.execute('''CREATE TABLE IF NOT EXISTS messages_par_salon (
        salon_id int, bucket bigint, message_id bigint, auteur_id int, contenu text,
        envoye_le timestamp, modifie_le timestamp, pieces_jointes text,
        PRIMARY KEY ((salon_id,bucket),message_id))
        WITH CLUSTERING ORDER BY (message_id DESC) AND gc_grace_seconds=864000''')
    cs.execute('''CREATE TABLE IF NOT EXISTS fenetres_non_vides (
        salon_id int, bucket bigint, PRIMARY KEY (salon_id,bucket))
        WITH CLUSTERING ORDER BY (bucket DESC)''')
    cs.execute('TRUNCATE messages_par_salon')
    cs.execute('TRUNCATE fenetres_non_vides')
    ins = cs.prepare('''INSERT INTO messages_par_salon
        (salon_id,bucket,message_id,auteur_id,contenu,envoye_le,modifie_le,pieces_jointes)
        VALUES (?,?,?,?,?,?,?,?)''')
    ins.consistency_level = ConsistencyLevel.ONE
    ins_bucket = cs.prepare('INSERT INTO fenetres_non_vides(salon_id,bucket) VALUES (?,?)')
    n_ok, pairs = 0, set()
    pg_cs = pg_conn()
    pg_cs.autocommit = False  # idem, lecture par lots en transaction
    with pg_cs.cursor(name='stream_cassandra') as cur:
        cur.execute('''SELECT id,salon_id,auteur_id,contenu,envoye_le,modifie_le,pieces_jointes
                       FROM app.message ORDER BY id''')
        for block in lots(cur, 500):
            batch = []
            for mid, salon, auteur, contenu, envoye, modifie, pieces in block:
                b = bucket_de(mid)
                pairs.add((salon, b))
                # UNSET_VALUE au lieu de None : pas de tombstones sur les champs absents.
                batch.append((salon, b, mid, auteur, contenu, envoye,
                              modifie if modifie is not None else UNSET_VALUE,
                              json.dumps(pieces, ensure_ascii=False) if pieces is not None else UNSET_VALUE))
            results = execute_concurrent_with_args(cs, ins, batch, concurrency=32,
                                                   raise_on_first_error=False)
            for success, res in results:
                if not success:
                    raise RuntimeError(f'Insertion Cassandra échouée : {res}')
                n_ok += 1
    pg_cs.close()
    for i in range(0, len(pairs), 500):
        batch = sorted(pairs)[i:i+500]
        results = execute_concurrent_with_args(cs, ins_bucket, batch, concurrency=32,
                                               raise_on_first_error=False)
        for success, res in results:
            if not success:
                raise RuntimeError(f'Index de fenêtres incomplet : {res}')
    print(f'cassandra : {n_ok} insertions confirmées, {len(pairs)} fenêtres non vides')
    assert n_ok == count_mongo, 'Migration Cassandra incomplète'
    cs.shutdown()


# Redis : état éphémère (TTL) ; ensemble stable des membres de chaque serveur.
r = redis_conn()
r.flushdb()
rnd = random.Random(7)
users = [u for (u,) in pg.execute('SELECT id FROM app.utilisateur').fetchall()]
en_ligne = set(rnd.sample(users, int(len(users) * 0.3)))
pipe = r.pipeline()
for u in en_ligne:
    pipe.set(f'presence:{u}', 'en_ligne', ex=300)
for serv, mem in pg.execute('SELECT serveur_id, array_agg(utilisateur_id) FROM app.membre GROUP BY 1').fetchall():
    pipe.sadd(f'membres:{serv}', *mem)
# Copies facultatives pour tester les trois hypothèses TP1 qui portent sur le cache Redis.
for salon in (775, 424, 340):
    ids = [row[0] for row in pg.execute('SELECT id FROM app.message WHERE salon_id=%s ORDER BY id DESC LIMIT 50', (salon,))]
    pipe.set(f'cache:messages:{salon}', json.dumps(ids), ex=3600)
activite = [(row[0].isoformat(), row[1], row[2]) for row in pg.execute('''
    SELECT jour,nb_messages,nb_auteurs FROM app.activite_serveur_jour
    WHERE serveur_id=118 AND jour>=%s AND jour<%s ORDER BY jour''', ('2026-10-01','2026-11-01'))]
pipe.set('cache:activite:118:2026-10', json.dumps(activite), ex=3600)
pipe.execute()
pg.execute('TRUNCATE app.presence')
with pg.cursor() as c:
    c.executemany('INSERT INTO app.presence VALUES (%s, now())', [(u,) for u in sorted(en_ligne)])
print(f'redis     : {r.dbsize()} clés ({len(en_ligne)} présences)')


# Neo4j : relations AMI_DE (une arête par paire canonique) et MEMBRE_DE.
drv = neo_driver()
with drv.session() as s:
    s.run('MATCH (n) DETACH DELETE n').consume()
    s.run('CREATE CONSTRAINT utilisateur_id IF NOT EXISTS FOR (u:Utilisateur) REQUIRE u.id IS UNIQUE').consume()
    s.run('CREATE CONSTRAINT serveur_id IF NOT EXISTS FOR (s:Serveur) REQUIRE s.id IS UNIQUE').consume()
    s.run('UNWIND $ids AS i MERGE (:Utilisateur {id: i})', ids=users).consume()
    s.run('UNWIND $ids AS i MERGE (:Serveur {id: i})', ids=[x for (x,) in pg.execute('SELECT id FROM app.serveur').fetchall()]).consume()
    am = pg.execute('SELECT utilisateur_a, utilisateur_b FROM app.amitie').fetchall()
    for i in range(0, len(am), 2500):
        s.run('''UNWIND $rows AS r MATCH (a:Utilisateur {id:r[0]}),(b:Utilisateur {id:r[1]})
                 MERGE (a)-[:AMI_DE]->(b)''', rows=[list(x) for x in am[i:i+2500]]).consume()
    me = pg.execute('SELECT utilisateur_id, serveur_id FROM app.membre').fetchall()
    for i in range(0, len(me), 2500):
        s.run('''UNWIND $rows AS r MATCH (u:Utilisateur {id:r[0]}),(v:Serveur {id:r[1]})
                 MERGE (u)-[:MEMBRE_DE]->(v)''', rows=[list(x) for x in me[i:i+2500]]).consume()
    for t in ('AMI_DE', 'MEMBRE_DE'):
        print(f"neo4j     : {s.run(f'MATCH ()-[r:{t}]->() RETURN count(r) AS n').single()['n']} relations {t}")
pg.close()
