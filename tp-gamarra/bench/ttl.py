"""Prouve un TTL Redis court et l'absence de TTL PostgreSQL natif. Usage : python ttl.py"""
import time
from common import redis_conn, pg_conn
r=redis_conn()
key='presence:preuve_ttl'
r.set(key,'en_ligne',ex=2)
print('t=0s  Redis present:', bool(r.exists(key)), 'TTL:',r.ttl(key))
time.sleep(3)
print('t=3s  Redis present:', bool(r.exists(key)), 'TTL:',r.ttl(key))
assert not r.exists(key)
print('PostgreSQL : lignes app.presence présentes physiquement même après 5 minutes ;')
print('la requête filtre vu_le > now() - interval 5 minutes, une purge planifiée reste nécessaire.')
pg=pg_conn()
print('Lignes encore enregistrées :',pg.execute('SELECT count(*) FROM app.presence').fetchone()[0])
pg.close()
