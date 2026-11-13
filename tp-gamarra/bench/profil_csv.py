"""Mission 0 : comptage + distribution des messages des 974 salons, zéros compris."""
import csv
from collections import Counter
from pathlib import Path
from statistics import median

repertoire = Path(__file__).resolve().parents[1] / 'data'
noms = ['utilisateurs','serveurs','salons','membres','messages','amities']
print('| CSV | Lignes hors en-tête |\n|---|---:|')
for name in noms:
    with (repertoire/f'{name}.csv').open(newline='',encoding='utf-8') as f:
        n = sum(1 for _ in f)-1
    print(f'| {name} | {n} |')
with (repertoire/'salons.csv').open(newline='',encoding='utf-8') as f:
    salons=[int(r['id']) for r in csv.DictReader(f)]
counts=Counter({s:0 for s in salons})
with (repertoire/'messages.csv').open(newline='',encoding='utf-8') as f:
    for r in csv.DictReader(f):
        counts[int(r['salon_id'])]+=1
values=sorted(counts.values())
top10=sum(sorted(values,reverse=True)[:10])
print('Min:',values[0],'Médiane:',median(values),'Max:',values[-1])
print('Top10:',top10,'/',sum(values),'=',f'{100*top10/sum(values):.2f}%')
print('Salons <20:',sum(v<20 for v in values),'dont sans messages:',sum(v==0 for v in values))
for nom,s in [('chaud',775),('moyen',424),('clairsemé',340)]:
    print(f'Test {nom} : salon {s}, {counts[s]} messages')
