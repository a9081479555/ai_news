#!/usr/bin/env python3
"""Reproducible AI-infrastructure financial scoring pipeline.

Uses public MOPS financial-statement pages, local caching, and a user-maintained
company/sub-industry mapping. It never guesses missing facts: unavailable values
remain blank and are reported as Evidence Gaps.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable

MOPS = "https://mops.twse.com.tw/mops/web/{report}"
REPORTS = {"balance": "t164sb03", "income": "t164sb04", "cashflow": "t164sb05"}
ALIASES = {
    "revenue": ("營業收入合計", "營業收入淨額", "營業收入"),
    "gross_profit": ("營業毛利（毛損）淨額", "營業毛利(毛損)淨額", "營業毛利（毛損）", "營業毛利"),
    "ar": ("應收帳款淨額", "應收帳款", "應收票據及帳款淨額"),
    "inventory": ("存貨淨額", "存貨"),
    "ap": ("應付帳款", "應付票據及帳款"),
    "capex": ("取得不動產、廠房及設備", "購置不動產、廠房及設備", "取得不動產及設備"),
}


class TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(); self.rows=[]; self.row=[]; self.cell=[]; self.in_cell=False
    def handle_starttag(self, tag, attrs):
        if tag.lower() in {"td", "th"}: self.in_cell=True; self.cell=[]
    def handle_data(self, data):
        if self.in_cell: self.cell.append(data)
    def handle_endtag(self, tag):
        tag=tag.lower()
        if tag in {"td", "th"} and self.in_cell:
            self.row.append(re.sub(r"\s+", " ", "".join(self.cell)).strip()); self.in_cell=False
        elif tag=="tr" and self.row:
            self.rows.append(self.row); self.row=[]


def number(value: str):
    value=value.replace(",", "").replace("−", "-").replace("—", "").strip()
    if not value or value in {"-", "--", "N/A"}: return None
    negative=value.startswith("(") and value.endswith(")")
    value=value.strip("()")
    m=re.search(r"-?\d+(?:\.\d+)?", value)
    if not m: return None
    n=float(m.group()); return -n if negative else n


def first_numeric(cells: list[str]):
    for cell in cells:
        n=number(cell)
        if n is not None: return n
    return None


def extract(rows: list[list[str]], aliases: Iterable[str]):
    candidates=[]
    for row in rows:
        if not row: continue
        label=re.sub(r"\s+", "", row[0])
        for alias in aliases:
            compact=re.sub(r"\s+", "", alias)
            if label==compact or compact in label:
                n=first_numeric(row[1:])
                if n is not None: candidates.append((0 if label==compact else 1, len(label), n))
    return sorted(candidates)[0][2] if candidates else None


@dataclass
class Company:
    code: str; name: str; subindustries: list[str]; listed: bool


def read_companies(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            yield Company(r["code"].strip(), r["name"].strip(), [x.strip() for x in r["subindustries"].split("|") if x.strip()], r.get("listed", "Y").upper()=="Y")


def request(url: str, cache: Path, delay: float, retries: int):
    cache.mkdir(parents=True, exist_ok=True)
    target=cache/(hashlib.sha256(url.encode()).hexdigest()+".html")
    if target.exists(): return target.read_text(encoding="utf-8", errors="replace"), str(target)
    headers={"User-Agent":"AI-Infrastructure-Banking-Research/1.0 (public-data audit; contact project owner)"}
    error=None
    for attempt in range(retries):
        try:
            time.sleep(delay)
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=40) as res:
                raw=res.read(); encoding=res.headers.get_content_charset() or "utf-8"
                text=raw.decode(encoding, errors="replace"); target.write_text(text, encoding="utf-8")
                return text, str(target)
        except (urllib.error.URLError, TimeoutError) as exc:
            error=exc; time.sleep((attempt+1)*2)
    raise RuntimeError(f"fetch failed after {retries} attempts: {url}: {error}")


def mops_url(report: str, code: str, year: int, season: int):
    query=urllib.parse.urlencode({"firstin":"1","step":"1","isnew":"false","co_id":code,"year":str(year),"season":str(season)})
    return MOPS.format(report=REPORTS[report])+"?"+query


def parse_statement(html: str):
    p=TableParser(); p.feed(html); return p.rows


def safe_div(a, b): return None if a is None or b in {None, 0} else a/b
def median(values):
    values=[v for v in values if v is not None and math.isfinite(v)]
    return statistics.median(values) if values else None


def mean(values):
    values=[v for v in values if v is not None and math.isfinite(v)]
    return statistics.mean(values) if values else None


def quintile_scores(values: dict[str, float | None]):
    valid=sorted((v,k) for k,v in values.items() if v is not None)
    out={k:None for k in values}; n=len(valid)
    for rank,(_,k) in enumerate(valid): out[k]=min(5, int(rank*5/n)+1)
    return out


def read_growth(path: Path):
    if not path.exists(): return {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        return {r["subindustry"].strip(): r for r in csv.DictReader(f)}


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w=csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--companies", default="config/company_universe.csv")
    ap.add_argument("--growth", default="config/growth_inputs.csv")
    ap.add_argument("--year", type=int, required=True, help="ROC fiscal year, e.g. 114 for 2025")
    ap.add_argument("--season", type=int, default=4)
    ap.add_argument("--cache", default="data/cache")
    ap.add_argument("--output", default="data/output")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--retries", type=int, default=3)
    ap.add_argument("--offline", action="store_true", help="use cache only; never access network")
    args=ap.parse_args()
    cache=Path(args.cache); output=Path(args.output); companies=list(read_companies(Path(args.companies))); growth=read_growth(Path(args.growth))
    company_rows=[]; evidence=[]
    for c in companies:
        vals={k:None for k in ("revenue","gross_profit","ar","inventory","ap","capex")}; sources=[]
        if not c.code or not c.listed:
            evidence.append({"company":c.name,"field":"all financial metrics","gap":"No listed-company code or complete public financial statements"})
        else:
            for kind in REPORTS:
                url=mops_url(kind,c.code,args.year,args.season); sources.append(url)
                try:
                    key=hashlib.sha256(url.encode()).hexdigest()+".html"; cached=cache/key
                    if args.offline:
                        if not cached.exists(): raise RuntimeError("cache miss in offline mode")
                        html=cached.read_text(encoding="utf-8", errors="replace")
                    else: html,_=request(url,cache,args.delay,args.retries)
                    rows=parse_statement(html)
                    for field in ("revenue","gross_profit") if kind=="income" else (("ar","inventory","ap") if kind=="balance" else ("capex",)):
                        vals[field]=extract(rows,ALIASES[field])
                except Exception as exc:
                    evidence.append({"company":c.name,"field":kind,"gap":str(exc)})
        gpm=safe_div(vals["gross_profit"],vals["revenue"]); capex=safe_div(abs(vals["capex"]) if vals["capex"] is not None else None,vals["revenue"])
        operating=safe_div(None if any(vals[x] is None for x in ("ar","inventory","ap")) else vals["ar"]+vals["inventory"]-vals["ap"],vals["revenue"])
        company_rows.append({"code":c.code,"company":c.name,"subindustries":"|".join(c.subindustries),"year_roc":args.year,"season":args.season,**vals,"gpm":gpm,"capex_revenue":capex,"operating_demand":operating,"sources":"|".join(sources)})
    subs=sorted({s for c in companies for s in c.subindustries}); aggregates=[]
    for s in subs:
        sample=[r for r in company_rows if s in r["subindustries"].split("|")]
        grow=growth.get(s,{})
        aggregates.append({"subindustry":s,"profitability_raw":median([r["gpm"] for r in sample]),"growth_raw":number(grow.get("cagr_pct", "")),"growth_source_title":grow.get("source_title", ""),"growth_source_url":grow.get("source_url", ""),"growth_evidence_grade":grow.get("evidence_grade", ""),"investment_raw":median([r["capex_revenue"] for r in sample]),"operating_raw":median([r["operating_demand"] for r in sample]),"sample_gpm":sum(r["gpm"] is not None for r in sample),"sample_capex":sum(r["capex_revenue"] is not None for r in sample),"sample_operating":sum(r["operating_demand"] is not None for r in sample)})
    score_fields={raw:quintile_scores({r["subindustry"]:r[raw] for r in aggregates}) for raw in ("profitability_raw","growth_raw","investment_raw","operating_raw")}
    for r in aggregates:
        s=r["subindustry"]; r.update({"profitability_score":score_fields["profitability_raw"][s],"growth_score":score_fields["growth_raw"][s],"investment_score":score_fields["investment_raw"][s],"operating_score":score_fields["operating_raw"][s]})
        x=[r["profitability_score"],r["growth_score"]]; y=[r["investment_score"],r["operating_score"]]; all_scores=x+y
        r["x_score"]=mean(x) if all(v is not None for v in x) else None
        r["y_score"]=mean(y) if all(v is not None for v in y) else None
        r["overall_score"]=mean(all_scores) if all(v is not None for v in all_scores) else None
        for raw in ("profitability_raw","growth_raw","investment_raw","operating_raw"):
            if r[raw] is None: evidence.append({"company":s,"field":raw,"gap":"Insufficient public data; score remains N/A"})
    write_csv(output/"company_financial_metrics.csv",company_rows,list(company_rows[0]))
    write_csv(output/"subindustry_scores.csv",aggregates,list(aggregates[0]))
    write_csv(output/"evidence_gaps.csv",evidence,["company","field","gap"])
    (output/"subindustry_scores.json").write_text(json.dumps(aggregates,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"companies={len(company_rows)} subindustries={len(aggregates)} gaps={len(evidence)} output={output}")


if __name__=="__main__": main()
