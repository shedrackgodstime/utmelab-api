#!/usr/bin/env python3
"""Fetch production topics/subtopics for selected exam/subject pairs (read-only).

Run from utmelab-bank/ with turso-serverless installed and prod read-only creds in .env:
  PYTHONPATH=src python3 /path/to/fetch_prod_subtopics.py --out ../data/prod-catalog-subtopics.json
"""
import argparse, json
from pathlib import Path

def load_env(path):
    env={}
    for line in Path(path).read_text().splitlines():
        line=line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        k,v=line.split('=',1)
        env[k]=v.strip().strip('"').strip("'")
    return env

PAIRS = [
 ('JAMB','use-of-english'),
 ('WAEC','english-language'),
 ('JAMB','economics'),
 ('JAMB','principles-of-accounts'),
 ('JAMB','commerce'),
]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--out', default='prod-catalog-subtopics.json')
    args=ap.parse_args()
    env=load_env('.env')
    url=env['TURSO_PROD_DATABASE_URL']
    if url.startswith('turso://'): url='libsql://'+url[len('turso://'):]
    token=env.get('TURSO_PROD_AUTH_TOKEN_READONLY') or env['TURSO_PROD_AUTH_TOKEN']
    import turso_serverless
    conn=turso_serverless.connect(url, auth_token=token)
    def q(sql, params=None):
        cur=conn.execute(sql, params or [])
        cols=[d[0] for d in cur.description] if cur.description else []
        return [dict(zip(cols,r)) for r in cur.fetchall()]
    out={}
    for exam,subject in PAIRS:
        topics=q('SELECT slug,name,"order" as ord,weight FROM topics WHERE exam=? AND subject=? ORDER BY ord,slug',[exam,subject])
        subs=q('''SELECT s.slug,s.topic,s.name,s."order" as ord
                  FROM subtopics s JOIN topics t ON t.slug=s.topic AND t.exam=? AND t.subject=?
                  ORDER BY t."order",s."order",s.slug''',[exam,subject])
        out[f'{exam}/{subject}']={'topics':topics,'subtopics':subs}
    Path(args.out).write_text(json.dumps(out,indent=2,ensure_ascii=False)+'\n')
    for k,v in out.items(): print(k,len(v['topics']),len(v['subtopics']))
    conn.close()

if __name__=='__main__':
    main()
