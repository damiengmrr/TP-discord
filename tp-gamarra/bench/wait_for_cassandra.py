"""Attend que Cassandra réponde à une vraie requête CQL (et pas seulement que Docker l'affiche Up).
Depuis bench/ : python wait_for_cassandra.py
"""
import sys
import time
from cassandra.cluster import Cluster

for tentative in range(1, 61):
    cluster = Cluster(["127.0.0.1"], port=9042)
    try:
        session = cluster.connect()
        row = session.execute('SELECT release_version FROM system.local').one()
        print(f'Cassandra prête, version {row.release_version} (tentative {tentative}).')
        break
    except Exception as exc:
        print(f'Cassandra non prête ({tentative}/60) : {type(exc).__name__}', flush=True)
        time.sleep(3)
    finally:
        cluster.shutdown()
else:
    sys.exit('Cassandra reste inaccessible : vérifier docker compose --profile colonne ps et logs cassandra.')
