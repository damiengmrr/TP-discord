"""Comparaisons B1 à B4, avec assertions de cohérence avant les mesures.

Depuis bench/: python bench.py --n 300
Les p50/p95 incluent les appels drivers sur localhost, et non le réseau de production.
"""
import argparse
import json
import random
import statistics
import time
from datetime import datetime, timezone, date

from common import bucket_de, cassandra_session, mongo_db, neo_driver, pg_conn, redis_conn

pg, mdb, rds, neo = pg_conn(), mongo_db(), redis_conn(), neo_driver()
if pg.execute('SELECT count(*) FROM app.message').fetchone()[0] == 0:
    raise SystemExit('PostgreSQL est vide : exécuter sql/02_chargement.sql avant le benchmark.')
cs = cassandra_session('discord')
SELECT_CS = cs.prepare('SELECT message_id FROM messages_par_salon WHERE salon_id = ? AND bucket = ? LIMIT ?')
SELECT_FENETRES = cs.prepare('SELECT bucket FROM fenetres_non_vides WHERE salon_id = ?')
NEO = neo.session()

SALON_CHAUD, SALON_MOYEN, SALON_CLAIRSEME = 775, 424, 340
DERNIER_BUCKET = bucket_de(pg.execute('SELECT max(id) FROM app.message').fetchone()[0])
CREATION = {s: bucket_de((int(c.timestamp() * 1000) - 1420070400000) << 22)
            for s, c in pg.execute('SELECT id, cree_le FROM app.salon').fetchall()}
NB_UTILISATEURS = pg.execute('SELECT max(id) FROM app.utilisateur').fetchone()[0]
SERVEUR_TEST = 118
DEBUT, FIN = datetime(2026, 10, 1, tzinfo=timezone.utc), datetime(2026, 11, 1, tzinfo=timezone.utc)


def b1_pg(salon):
    return [x[0] for x in pg.execute('SELECT id FROM app.message WHERE salon_id = %s ORDER BY id DESC LIMIT 50', (salon,)).fetchall()]


def b1_redis_cache(salon):
    data = rds.get(f'cache:messages:{salon}')
    if data is None:
        raise RuntimeError('Cache Redis des messages manquant : relancer load_nosql.py')
    return json.loads(data)


def b1_mongo(salon):
    return [d['_id'] for d in mdb.messages.find({'salon_id': salon}, {'_id': 1})
            .sort('_id', -1).limit(50)]


def b1_cassandra(salon):
    results = []
    for b in range(DERNIER_BUCKET, CREATION[salon]-1, -1):
        results.extend(row.message_id for row in cs.execute(SELECT_CS, (salon, b, 50-len(results))))
        if len(results) == 50:
            break
    return results


def b1_cassandra_fenetres(salon):
    results = []
    for (b,) in cs.execute(SELECT_FENETRES, (salon,)):
        results.extend(row.message_id for row in cs.execute(SELECT_CS, (salon, b, 50-len(results))))
        if len(results) == 50:
            break
    return results


def b2w_pg(uid):
    pg.execute('''INSERT INTO app.presence VALUES (%s, now())
                  ON CONFLICT (utilisateur_id) DO UPDATE SET vu_le = now()''', (uid,))


def b2w_redis(uid):
    rds.set(f'presence:{uid}', 'en_ligne', ex=300)


def b2r_pg(serveur):
    return pg.execute('''SELECT count(*) FROM app.membre m JOIN app.presence p ON p.utilisateur_id=m.utilisateur_id
                         WHERE m.serveur_id=%s AND p.vu_le > now() - interval '5 minutes' ''',
                      (serveur,)).fetchone()[0]


def b2r_redis(serveur):
    mem = rds.smembers(f'membres:{serveur}')
    if not mem:
        return 0
    values = rds.mget([f'presence:{u}' for u in mem])
    return sum(v is not None for v in values)


# Test complémentaire H5 TP1 : appartenance simple, pas autorisation complète d'écrire.
def b5_pg_adhesion(serveur, uid):
    return pg.execute('SELECT EXISTS(SELECT 1 FROM app.membre WHERE serveur_id=%s AND utilisateur_id=%s)',
                      (serveur,uid)).fetchone()[0]


def b5_redis_adhesion(serveur, uid):
    return bool(rds.sismember(f'membres:{serveur}', str(uid)))


def b3_pg(uid):
    return [tuple(row) for row in pg.execute('''
        SELECT m.serveur_id, count(*) AS n
        FROM (SELECT utilisateur_b AS ami FROM app.amitie WHERE utilisateur_a=%(u)s
              UNION ALL SELECT utilisateur_a FROM app.amitie WHERE utilisateur_b=%(u)s) f
        JOIN app.membre m ON m.utilisateur_id=f.ami
        WHERE NOT EXISTS (SELECT 1 FROM app.membre mine
                          WHERE mine.utilisateur_id=%(u)s AND mine.serveur_id=m.serveur_id)
        GROUP BY m.serveur_id HAVING count(*)>=2
        ORDER BY n DESC,m.serveur_id LIMIT 5''', {'u': uid}).fetchall()]


def b3_neo(uid):
    rows = NEO.run('''MATCH (u:Utilisateur {id:$u})-[:AMI_DE]-(f:Utilisateur)-[:MEMBRE_DE]->(s:Serveur)
                      WHERE NOT EXISTS { MATCH (u)-[:MEMBRE_DE]->(s) }
                      WITH s,count(DISTINCT f) AS n WHERE n>=2
                      RETURN s.id AS id,n ORDER BY n DESC,id ASC LIMIT 5''', u=uid)
    return [(row['id'], row['n']) for row in rows]


def b3bis_pg(uid):
    return [tuple(row) for row in pg.execute('''
        WITH f AS (
          SELECT utilisateur_b AS ami FROM app.amitie WHERE utilisateur_a=%(u)s
          UNION ALL SELECT utilisateur_a FROM app.amitie WHERE utilisateur_b=%(u)s
        ), s AS (
          SELECT CASE WHEN a.utilisateur_a=f.ami THEN a.utilisateur_b ELSE a.utilisateur_a END AS candidat
          FROM f JOIN app.amitie a ON a.utilisateur_a=f.ami OR a.utilisateur_b=f.ami
        )
        SELECT candidat,count(*) AS communs FROM s
        WHERE candidat<>%(u)s
          AND NOT EXISTS(SELECT 1 FROM app.amitie a
                         WHERE a.utilisateur_a=LEAST(candidat,%(u)s)
                           AND a.utilisateur_b=GREATEST(candidat,%(u)s))
        GROUP BY candidat ORDER BY communs DESC,candidat ASC LIMIT 5''', {'u': uid}).fetchall()]


def b3bis_neo(uid):
    rows = NEO.run('''MATCH (u:Utilisateur {id:$u})-[:AMI_DE]-(f:Utilisateur)-[:AMI_DE]-(c:Utilisateur)
                      WHERE c<>u AND NOT EXISTS { MATCH (u)-[:AMI_DE]-(c) }
                      WITH c,count(DISTINCT f) AS n
                      RETURN c.id AS id,n ORDER BY n DESC,id ASC LIMIT 5''', u=uid)
    return [(row['id'],row['n']) for row in rows]


def b4_pg_normalise(serveur):
    return [tuple(row) for row in pg.execute('''
        SELECT (m.envoye_le AT TIME ZONE 'UTC')::date AS jour,
               count(*)::bigint AS nb_messages,count(DISTINCT m.auteur_id)::bigint AS nb_auteurs
        FROM app.message m JOIN app.salon s ON s.id=m.salon_id
        WHERE s.serveur_id=%s AND m.envoye_le>=%s AND m.envoye_le<%s
        GROUP BY 1 ORDER BY 1''', (serveur,DEBUT,FIN)).fetchall()]


def b4_pg_vue(serveur):
    return [tuple(row) for row in pg.execute('''
        SELECT jour,nb_messages,nb_auteurs FROM app.activite_serveur_jour
        WHERE serveur_id=%s AND jour>=%s AND jour<%s ORDER BY jour''',
        (serveur,DEBUT.date(),FIN.date())).fetchall()]


def b4_redis_cache(serveur):
    # Cache produit uniquement pour le serveur 118 et octobre 2026 (hypothèse TP1).
    data = rds.get(f'cache:activite:{serveur}:2026-10')
    if data is None:
        raise RuntimeError('Cache Redis du tableau de bord manquant : relancer load_nosql.py')
    return [(date.fromisoformat(d), n, a) for d,n,a in json.loads(data)]


def b4_mongo(serveur):
    rows = mdb.messages.aggregate([
        {'$match': {'serveur_id': serveur,'envoye_le': {'$gte':DEBUT,'$lt':FIN}}},
        {'$group': {'_id': {'$dateToString': {'format':'%Y-%m-%d','date':'$envoye_le','timezone':'UTC'}},
                    'nb_messages': {'$sum':1},'auteurs': {'$addToSet':'$auteur_id'}}},
        {'$project': {'nb_messages':1,'nb_auteurs': {'$size':'$auteurs'}}},
        {'$sort': {'_id':1}}
    ])
    from datetime import date
    return [(date.fromisoformat(x['_id']),x['nb_messages'],x['nb_auteurs']) for x in rows]


def chrono(f, entrees, echauffement=10):
    for e in entrees[:echauffement]:
        f(*e)
    t=[]
    for e in entrees:
        t0=time.perf_counter_ns()
        f(*e)
        t.append((time.perf_counter_ns()-t0)/1_000_000)
    t.sort()
    return statistics.median(t), t[max(0, int((len(t)-1)*0.95))]


def verifier_coherence():
    for s in (SALON_CHAUD,SALON_MOYEN,SALON_CLAIRSEME):
        a,b,c,d = b1_pg(s),b1_mongo(s),b1_cassandra(s),b1_cassandra_fenetres(s)
        assert a==b==c==d==b1_redis_cache(s),(f'B1 salon {s}',a[:5],b[:5],c[:5],d[:5])
    assert b2r_pg(SERVEUR_TEST)==b2r_redis(SERVEUR_TEST),'B2b incohérent'
    for uid in (1,7,42,128,NB_UTILISATEURS):
        assert b3_pg(uid)==b3_neo(uid),(f'B3 uid={uid}',b3_pg(uid),b3_neo(uid))
        assert b3bis_pg(uid)==b3bis_neo(uid),(f'B3bis uid={uid}',b3bis_pg(uid),b3bis_neo(uid))
    assert b4_pg_normalise(SERVEUR_TEST)==b4_pg_vue(SERVEUR_TEST)==b4_mongo(SERVEUR_TEST)==b4_redis_cache(SERVEUR_TEST),'B4 incohérent'
    for uid in (1,7,42,128,NB_UTILISATEURS):
        assert b5_pg_adhesion(SERVEUR_TEST,uid)==b5_redis_adhesion(SERVEUR_TEST,uid),'H5 adhésion incohérente'
    # Le même heartbeat doit se refléter dans les deux moteurs avant mesure.
    b2w_pg(1)
    b2w_redis(1)
    assert pg.execute('SELECT vu_le > now()-interval \'5 minutes\' FROM app.presence WHERE utilisateur_id=1').fetchone()[0]
    assert rds.exists('presence:1')
    print('Contrôles de cohérence B1/B2/B3/B3bis/B4 : OK')


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--n',type=int,default=300)
    n=ap.parse_args().n
    verifier_coherence()  # jamais de benchmark sur des résultats différents
    rnd=random.Random(1)
    lignes=[]
    def mesure(cas,moteur,f,entrees):
        p50,p95=chrono(f,entrees)
        lignes.append(f'| {cas} | {moteur} | {p50:.3f} | {p95:.3f} |')

    for nom,s in [('chaud',SALON_CHAUD),('moyen',SALON_MOYEN),('clairsemé',SALON_CLAIRSEME)]:
        entree=[(s,)]*n
        label=f'B1 50 derniers, salon {nom}'
        for moteur,f in [('PostgreSQL',b1_pg),('Redis cache (TP1)',b1_redis_cache),('MongoDB',b1_mongo),('Cassandra',b1_cassandra),
                         ('Cassandra fenêtres',b1_cassandra_fenetres)]:
            mesure(label,moteur,f,entree)
    e=[(rnd.randint(1,NB_UTILISATEURS),) for _ in range(n)]
    mesure('B2a battement','PostgreSQL',b2w_pg,e)
    mesure('B2a battement','Redis',b2w_redis,e)
    e=[(SERVEUR_TEST,)]*n
    mesure('B2b en ligne','PostgreSQL',b2r_pg,e)
    mesure('B2b en ligne','Redis',b2r_redis,e)
    e=[(rnd.randint(1,NB_UTILISATEURS),) for _ in range(n)]
    for (uid,) in sorted(set(e)):
        assert b3_pg(uid)==b3_neo(uid),(f'B3 uid={uid}',b3_pg(uid),b3_neo(uid))
    mesure('B3 serveurs suggérés','PostgreSQL',b3_pg,e)
    mesure('B3 serveurs suggérés','Neo4j',b3_neo,e)
    e=[(rnd.randint(1,NB_UTILISATEURS),) for _ in range(max(30,n//10))]
    for (uid,) in sorted(set(e)):
        assert b3bis_pg(uid)==b3bis_neo(uid),(f'B3bis uid={uid}',b3bis_pg(uid),b3bis_neo(uid))
    mesure('B3bis amis d’amis','PostgreSQL',b3bis_pg,e)
    mesure('B3bis amis d’amis','Neo4j',b3bis_neo,e)
    e=[(SERVEUR_TEST,)]*n
    mesure('B4 activité serveur','PostgreSQL normalisé',b4_pg_normalise,e)
    mesure('B4 activité serveur','PostgreSQL vue',b4_pg_vue,e)
    mesure('B4 activité serveur','MongoDB',b4_mongo,e)
    mesure('B4 activité serveur','Redis cache (TP1)',b4_redis_cache,e)
    e=[(SERVEUR_TEST,rnd.randint(1,NB_UTILISATEURS)) for _ in range(n)]
    for sid,uid in e:
        assert b5_pg_adhesion(sid,uid)==b5_redis_adhesion(sid,uid),'H5 échec contrôle'
    mesure('H5 appartenance simple','PostgreSQL',b5_pg_adhesion,e)
    mesure('H5 appartenance simple','Redis',b5_redis_adhesion,e)
    print(f'| Cas | Moteur | p50 (ms) | p95 (ms) |\n|---|---|---:|---:|\n'+ '\n'.join(lignes))


if __name__=='__main__':
    try:
        main()
    finally:
        NEO.close()
        neo.close()
        pg.close()
        cs.shutdown()
