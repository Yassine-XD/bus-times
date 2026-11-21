"""Probe round 2: structure of each readable source (robots.txt respected)."""
import re, gzip, json, urllib.request, urllib.robotparser
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
from collections import Counter

UA = "YassineJobFeed/1.0 (+https://github.com/Yassine-XD/bus-times)"
robots = {}

def allowed(url):
    host = urlparse(url).scheme + "://" + urlparse(url).netloc
    if host not in robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": UA})
            rp.parse(urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace").splitlines())
        except Exception:
            rp.parse([])
        robots[host] = rp
    return robots[host].can_fetch(UA, url)

def get(url):
    if not allowed(url):
        print("[DISALLOWED]", url); return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9"})
        body = urllib.request.urlopen(req, timeout=60).read()
        if body[:2] == b"\x1f\x8b": body = gzip.decompress(body)
        t = body.decode("utf-8", "replace"); print(f"[ok] {url} {len(t)}b"); return t
    except Exception as e:
        print("[ERR]", url, e); return None

def sq(s, n=400): return re.sub(r"\s+", " ", s or "")[:n]

def ldjson(t):
    out = []
    for m in re.findall(r'<script[^>]+application/ld\+json[^>]*>(.*?)</script>', t or "", re.S):
        try: out.append(json.loads(m))
        except Exception: pass
    return out


print("==== RANDSTAD sub-sitemap")
t = get("https://www.randstad.es/candidate-offers_sitemap_1.xml")
if t:
    locs = re.findall(r"<loc>(?:<!\[CDATA\[)?([^<\]]+)", t); lm = re.findall(r"<lastmod>(?:<!\[CDATA\[)?([^<\]]+)", t)
    print("locs", len(locs), locs[:4], lm[:2])
    p = get(locs[0]) if locs else None
    for j in ldjson(p):
        if "JobPosting" in json.dumps(j): print("  ld:", sq(json.dumps(j, ensure_ascii=False), 1200))

print("==== RAS rss")
t = get("https://empleo.ras-interim.es/jobs.rss")
if t:
    items = re.findall(r"<item>(.*?)</item>", t, re.S); print("items", len(items)); print(sq(items[0], 1500))

print("==== IMAN")
t = get("https://empleo.imancorp.es/jobs")
if t:
    print("inputs", re.findall(r'<(?:input|select)[^>]+name="([^"]+)"', t)[:20])
    print("forms", re.findall(r'<form[^>]+action="([^"]*)"', t)[:5])
    i = t.find("/jobs/operario"); print(sq(re.sub(r"<[^>]+>", " | ", t[i-800:i+1200]), 1200))
    p = get("https://empleo.imancorp.es/jobs/customer-service-sat-english-speaking")
    for j in ldjson(p): print("  ld:", sq(json.dumps(j, ensure_ascii=False), 900))
for q in ["https://empleo.imancorp.es/jobs?search=Matar%C3%B3", "https://empleo.imancorp.es/jobs?q=Matar%C3%B3", "https://empleo.imancorp.es/jobs?location=Barcelona"]:
    t = get(q)
    if t: print("  links", len(re.findall(r'href="https://empleo\.imancorp\.es/jobs/[^"]+"', t)), "matar" , t.lower().count("matar"))

print("==== ADECCO endpoints in NEXT_DATA")
t = get("https://www.adecco.com/es-es/ofertas-trabajo?l=Matar%C3%B3")
if t:
    urls = set(re.findall(r'https?://[^"\s\\]+', t))
    print([u for u in urls if any(k in u.lower() for k in ["api", "search", "job", "solr", "graphql"])][:30])
    print(re.findall(r'"[^"]*(?:[Ee]ndpoint|[Aa]pi[Uu]rl|searchUrl|serviceUrl)[^"]*":\s*"[^"]*"', t)[:15])

print("==== MEDITEMPUS offer")
p = get("https://www.meditempus.com/oferta/soldador-a-mig-mag-tig-estable-manana-tarde/")
for j in ldjson(p):
    if "JobPosting" in json.dumps(j): print("  ld:", sq(json.dumps(j, ensure_ascii=False), 900))
if p: i = p.find("Ubicaci"); print(sq(re.sub(r"<[^>]+>", " | ", p[i-300:i+800]), 800))

print("==== XALOC detail")
p = get("https://xaloc.diba.cat/ofertes-de-feina/397227")
if p:
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", p))
    i = txt.find("Obligatoris"); print(txt[max(0,i-1500):i+1500])
