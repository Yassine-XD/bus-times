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



print("==== RANDSTAD listing + page")
t = get("https://www.randstad.es/candidatos/ofertas-empleo/p-barcelona/c-mataro/")
if t:
    links = re.findall(r'ofertas-empleo/oferta/[^"\'\s<]+', t); print("links", len(set(links)), list(set(links))[:6])
    print("result count hints", re.findall(r'(\d+)\s*ofertas', t)[:5])
    print("paging", re.findall(r'href="([^"]*c-mataro[^"]*pg-?\d+[^"]*)"', t)[:4], re.findall(r'href="([^"]*c-mataro/[^"]+)"', t)[:6])
t = get("https://www.randstad.es/candidatos/ofertas-empleo/oferta/mozo-a-almacen-carga-y-descarga-media-jornada-turno-tarde-san-fernando-henares-madrid-3025168/")
if t:
    print("title", re.findall(r"<title>([^<]+)", t)[:1], "desc", re.findall(r'name="description" content="([^"]+)', t)[:1])
    for k in ["Localidad", "Ubicación", "ubicación", "Provincia", "jobLocation", "addressLocality", "datePosted", "Fecha"]:
        i = t.find(k); print(" ", k, sq(re.sub(r"<[^>]+>", " | ", t[i:i+300]), 200) if i >= 0 else None)

print("==== IMAN location options")
t = get("https://empleo.imancorp.es/jobs")
if t:
    m = re.search(r'<select[^>]+name="location"[^>]*>(.*?)</select>', t, re.S)
    opts = re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)<', m.group(1)) if m else []
    print(len(opts), [o for o in opts if any(k in o[1].lower() for k in ["matar", "granol", "barcelona", "vall", "maresme", "badalona", "sabadell", "mollet", "vilassar", "lli"])][:30])
    if not m: print(sq(t[t.find('name="location"')-300:t.find('name="location"')+1500], 1500))

print("==== EUROFIRMS ld keys")
p = get("https://jobs.eurofirms.com/es/es/mataro/manipulador-a-062-017250")
for j in ldjson(p):
    if j.get("@type") == "JobPosting":
        print({k: (v if k != "description" else len(v)) for k, v in j.items()})

print("==== MEDITEMPUS page text")
p = get("https://www.meditempus.com/oferta/soldador-a-mig-mag-tig-estable-manana-tarde/")
if p:
    txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", p, flags=re.S)))
    i = txt.find("Soldador"); print(txt[i:i+1800])

print("==== RAS page ld keys")
p = get("https://empleo.ras-interim.es/jobs/8471772-mozo-a-de-almacen")
for j in ldjson(p):
    if j.get("@type") == "JobPosting":
        print({k: (v if k != "description" else len(v)) for k, v in j.items()})
t = get("https://empleo.ras-interim.es/jobs.rss")
if t:
    print("rss locations", Counter(re.findall(r"<tt:name>([^<]+)</tt:name>", t)).most_common(40))
    print("rss dates", re.findall(r"<pubDate>([^<]+)", t)[:3], re.findall(r"<pubDate>([^<]+)", t)[-3:])
