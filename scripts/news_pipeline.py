#!/usr/bin/env python3
"""Traceable news intake, approval publishing, and weekly aggregation pipeline."""
from __future__ import annotations
import argparse, datetime as dt, email.utils, hashlib, html, json, re, sys, urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
CFG=ROOT/'config'/'news_sources.json'; QUEUE=ROOT/'data'/'review'/'news_queue.json'
PUBLIC=ROOT/'data'/'public'/'news.json'; WEEKLY=ROOT/'data'/'public'/'weekly.json'; APPROVED=ROOT/'config'/'approved_news_ids.txt'
UTC=dt.timezone.utc

def now(): return dt.datetime.now(UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
def read_json(path,default):
    try: return json.loads(path.read_text(encoding='utf-8'))
    except (FileNotFoundError,json.JSONDecodeError): return default
def write_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True); path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def strip_markup(value): return re.sub(r'\s+',' ',html.unescape(re.sub(r'<[^>]+>',' ',value or ''))).strip()
def parse_date(value):
    try: return email.utils.parsedate_to_datetime(value).astimezone(UTC).replace(microsecond=0).isoformat().replace('+00:00','Z')
    except Exception: return now()
def fetch(url):
    req=urllib.request.Request(url,headers={'User-Agent':'AI-Infrastructure-Bankability-News/1.0 (+public-source-monitor)'})
    with urllib.request.urlopen(req,timeout=30) as response: return response.read()
def node_text(node,name):
    child=node.find(name); return (child.text or '').strip() if child is not None else ''
def item_id(title,url): return hashlib.sha256((re.sub(r'\W+','',title.lower())+'|'+url).encode('utf-8')).hexdigest()[:20]

def load_known_companies():
    text=(ROOT/'index.html').read_text(encoding='utf-8'); m=re.search(r'const companyData=(\[.*?\]);\s*\n',text,re.S)
    if not m: return []
    try: return sorted({x['n'] for x in json.loads(m.group(1)) if x.get('n')},key=len,reverse=True)
    except Exception: return []

def classify(text,cfg,companies):
    low=text.lower(); matched_companies=[c for c in companies if c.lower() in low]
    subs=[name for name,words in cfg['subindustry_keywords'].items() if any(w.lower() in low for w in words)]
    event='其他重要事件'
    for name,words in cfg['event_keywords'].items():
        if any(w.lower() in low for w in words): event=name; break
    system=cfg['system_map'].get(subs[0],'跨系統／待分類') if subs else '跨系統／待分類'
    important={'CapEx／擴產','融資／籌資','訂單／合作／認證','併購／投資','風險事件'}
    return matched_companies,subs,event,system,'High' if event in important else 'Medium'

def discover_candidates(text,known):
    found=[]
    for name,code in re.findall(r'([\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z&\-]{1,24})[（(](\d{4})[）)]',text):
        name=name.strip(' -｜');
        if name and name not in known: found.append({'name':name,'stock_code':code,'status':'pending','evidence_gap':'須核對MOPS、公司官網及與AI Infrastructure的直接關聯。'})
    return found

def blocked_item(title,source,cfg):
    title=(title or '').lower(); source=(source or '').lower()
    return (any(x.lower() in source for x in cfg.get('blocked_sources',[])) or
            any(x.lower() in title for x in cfg.get('blocked_title_patterns',[])) or
            any(x.lower() in title for x in cfg.get('anonymous_title_patterns',[])))

def collect():
    cfg=read_json(CFG,{}); companies=load_known_companies(); old=read_json(QUEUE,{'items':[],'candidate_companies':[]})
    by_id={x['id']:x for x in old.get('items',[]) if not blocked_item(x.get('title'),x.get('source_name'),cfg)}; candidates={(x.get('name'),x.get('stock_code')):x for x in old.get('candidate_companies',[])}
    cutoff=dt.datetime.now(UTC)-dt.timedelta(hours=cfg.get('lookback_hours',72)); errors=[]
    for feed in cfg.get('feeds',[]):
        try: root=ET.fromstring(fetch(feed['url']))
        except Exception as exc: errors.append({'feed':feed['name'],'error':str(exc)}); continue
        for node in root.findall('.//item')[:cfg.get('max_items_per_feed',60)]:
            title=strip_markup(node_text(node,'title')); url=node_text(node,'link'); desc=strip_markup(node_text(node,'description')); published=parse_date(node_text(node,'pubDate'))
            try:
                if dt.datetime.fromisoformat(published.replace('Z','+00:00'))<cutoff: continue
            except ValueError: pass
            if not title or not url: continue
            source=node.find('source'); source_name=(source.text or '').strip() if source is not None else feed['name']
            if blocked_item(title,source_name,cfg): continue
            companies_hit,subs,event,system,importance=classify(title+' '+desc,cfg,companies)
            if not companies_hit and not subs and not re.search(r'AI|人工智慧|data center|資料中心|server|伺服器',title+' '+desc,re.I): continue
            iid=item_id(title,url); existing=by_id.get(iid,{})
            by_id[iid]={**existing,'id':iid,'status':existing.get('status','pending'),'title':title,'url':url,'published_at':published,'collected_at':now(),'source_name':source_name,'source_domain':urlparse(url).netloc,'summary':desc[:800],'companies':companies_hit,'subindustries':subs,'system':system,'event_type':event,'importance':importance,'evidence_grade':'C','banking_implication':'待人工審核後補充。','evidence_gap':'目前為新聞／RSS線索；須回查公司公告、MOPS或平台官方文件。'}
            for c in discover_candidates(title+' '+desc,set(companies)):
                key=(c['name'],c['stock_code']); candidates[key]={**c,'first_seen_news_id':iid,'source_url':url}
    items=sorted(by_id.values(),key=lambda x:x.get('published_at',''),reverse=True)
    candidate_items=[x for x in candidates.values() if x.get('first_seen_news_id') in by_id or x.get('status')!='pending']
    write_json(QUEUE,{'generated_at':now(),'items':items,'candidate_companies':candidate_items,'collection_errors':errors})
    print(f'Collected queue: {len(items)} items; candidates: {len(candidate_items)}; errors: {len(errors)}')

def approved_ids():
    if not APPROVED.exists(): return set()
    return {x.strip() for x in APPROVED.read_text(encoding='utf-8').splitlines() if x.strip() and not x.lstrip().startswith('#')}
def publish():
    queue=read_json(QUEUE,{'items':[]}); ids=approved_ids(); old=read_json(PUBLIC,{'items':[]}); merged={x['id']:x for x in old.get('items',[])}
    for item in queue.get('items',[]):
        if item.get('id') in ids:
            clean={k:v for k,v in item.items() if k!='status'}; clean['approved_at']=now(); merged[item['id']]=clean
    items=sorted(merged.values(),key=lambda x:x.get('published_at',''),reverse=True)
    write_json(PUBLIC,{'generated_at':now(),'items':items,'notice':'Only explicitly approved public-source events are published.'}); print(f'Published: {len(items)} items')
def weekly():
    public=read_json(PUBLIC,{'items':[]}); items=public.get('items',[]); today=dt.datetime.now(UTC).date(); start=today-dt.timedelta(days=7)
    recent=[x for x in items if x.get('published_at','')[:10]>=start.isoformat()]; week_id=f'{start.isoformat()}_{today.isoformat()}'
    if not recent:
        old=read_json(WEEKLY,{'weeks':[]}); write_json(WEEKLY,{'generated_at':now(),'weeks':old.get('weeks',[]),'notice':'No approved events were available for a new weekly report.'}); print('Weekly report skipped: no approved events'); return
    high=[x['title'] for x in recent if x.get('importance')=='High']; industry=sorted({s for x in recent for s in x.get('subindustries',[])})
    companies=sorted({c for x in recent for c in x.get('companies',[])})
    banking=[x['title'] for x in recent if x.get('event_type') in {'CapEx／擴產','融資／籌資','併購／投資'}]
    report={'week_id':week_id,'title':f'AI Infrastructure Weekly｜{start.isoformat()}–{today.isoformat()}','period':f'{start.isoformat()} 至 {today.isoformat()}','status':'approved-public','highlights':high,'industry_changes':industry,'company_events':companies,'banking_events':banking,'rm_followups':[f'追蹤 {c}：取得事件對應之官方公告、資金用途與銀行往來資料。' for c in companies[:10]],'evidence_gaps':sorted({x.get('evidence_gap','') for x in recent if x.get('evidence_gap')}),'events':recent}
    old=read_json(WEEKLY,{'weeks':[]}); weeks=[w for w in old.get('weeks',[]) if w.get('week_id')!=week_id]; weeks.insert(0,report)
    write_json(WEEKLY,{'generated_at':now(),'weeks':weeks[:104],'notice':'Generated only from approved public events.'}); print(f'Weekly report: {week_id}, events: {len(recent)}')
def main():
    p=argparse.ArgumentParser(); p.add_argument('command',choices=['collect','publish','weekly','all']); a=p.parse_args()
    if a.command in {'collect','all'}: collect()
    if a.command in {'publish','all'}: publish()
    if a.command in {'weekly','all'}: weekly()
if __name__=='__main__': main()
