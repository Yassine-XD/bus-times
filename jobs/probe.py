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

print("==== FEINA ACTIVA")
t = get("https://feinaactiva.gencat.cat/api/offers/offers-xml")
if t:
    root = ET.fromstring(t)
    ads = root.findall(".//ad")
    print("ads", len(ads), "status", Counter(a.findtext("status") for a in ads).most_common(4),
          "origin", Counter(a.findtext("origin") for a in ads).most_common(6))
    dates = sorted(a.findtext("date") or "" for a in ads)
    print("dates sample", Counter(d[-7:] for d in dates).most_common(6))
    cities = Counter((a.findtext("city") or "").upper() for a in ads)
    for c in ["MATARÓ", "GRANOLLERS", "ARGENTONA", "VILASSAR DE MAR", "PREMIÀ DE MAR", "LLIÇÀ DE VALL", "LES FRANQUESES DEL VALLÈS", "MOLLET DEL VALLÈS", "BADALONA", "SABADELL", "MONTORNÈS DEL VALLÈS", "CALELLA"]:
        print("  ", c, cities.get(c, 0))
    print("  similar:", [c for c in cities if "MATAR" in c or "FRANQUESES" in c or "LLI" in c[:4]])
    for a in ads:
        if (a.findtext("city") or "").upper().startswith("MATAR"):
            print("  EX:", ET.tostring(a, encoding="unicode")[:900]); break

print("==== XALOC Mataró card")
t = get("https://xaloc.diba.cat/ofertes-de-feina?offer_type%5Bxaloc%5D=xaloc&offer_type%5Bpublic%5D=0&municipality%5B0%5D=08121&disability=All&day=All&map=false")
if t:
    i = t.find("ofertes-de-feina/39")
    print(sq(re.sub(r"<[^>]+>", " | ", t[i-1500:i+2500]), 2000))
    print("pager:", re.findall(r'[?&]page=(\d+)', t)[:10])
    opts = re.findall(r'<option value="(08\d{3})"[^>]*>([^<]+)</option>', t)
    print("municipality options", len(opts), opts[:5])
    want = ["Mataró","Argentona","Cabrera de Mar","Cabrils","Vilassar de Mar","Vilassar de Dalt","Premià de Mar","Premià de Dalt","Teià","Masnou","Alella","Montgat","Tiana","Badalona","Sant Adrià de Besòs","Sant Andreu de Llavaneres","Sant Vicenç de Montalt","Caldes d'Estrac","Arenys de Mar","Arenys de Munt","Canet de Mar","Sant Pol de Mar","Calella","Pineda de Mar","Santa Susanna","Malgrat de Mar","Palafolls","Tordera","Dosrius","Granollers","Franqueses","Canovelles","Roca del Vallès","Lliçà d'Amunt","Lliçà de Vall","Parets del Vallès","Montmeló","Montornès del Vallès","Mollet del Vallès","Martorelles","Vilanova del Vallès","Cardedeu","Llinars del Vallès","Sant Celoni","Sabadell"]
    print("CODES", json.dumps({n: c for c, n in opts if any(w.lower() in n.lower() for w in want)}, ensure_ascii=False))

print("==== ADECCO")
t = get("https://www.adecco.com/jobsindex.xml")
if t:
    locs = re.findall(r"<loc>([^<]+)</loc>", t); print("jobsindex locs", len(locs), [l for l in locs if "es-es" in l][:5], locs[:3])
t = get("https://www.adecco.com/es-es/ofertas-trabajo?l=Matar%C3%B3")
if t:
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', t, re.S)
    if m:
        d = json.loads(m.group(1)); s = json.dumps(d, ensure_ascii=False)
        print("NEXT_DATA size", len(s))
        for k in ["jobTitle", "title", "jobId", "city", "postedDate", "datePosted", "location"]:
            i = s.find('"' + k + '"'); print(" ", k, "->", s[i:i+200] if i >= 0 else None)
        print("  total hints:", re.findall(r'"(?:totalCount|total|numFound|count)":\s*\d+', s)[:5])

print("==== RANDSTAD")
t = get("https://www.randstad.es/offers_sitemap.xml")
if t:
    locs = re.findall(r"<loc>(?:<!\[CDATA\[)?([^<\]]+)", t); print("offers locs", len(locs), locs[:3])
    print("lastmods", re.findall(r"<lastmod>(?:<!\[CDATA\[)?([^<\]]+)", t)[:3])
    print("mataro/granollers urls", [l for l in locs if "mataro" in l or "granollers" in l][:6])
t = get("https://www.randstad.es/candidatos/ofertas-empleo/p-barcelona/c-mataro/")
for j in ldjson(t): print("  ld:", sq(json.dumps(j, ensure_ascii=False), 600))

print("==== EUROFIRMS")
t = get("https://jobs.eurofirms.com/sitemap_es-ES_offers.xml")
if t:
    locs = re.findall(r"<loc>([^<]+)</loc>", t); print("offers", len(locs), locs[:3])
    mt = [l for l in locs if "mataro" in l or "granollers" in l]; print("mataro/granollers", len(mt), mt[:4])
    if mt:
        p = get(mt[0])
        for j in ldjson(p): print("  ld:", sq(json.dumps(j, ensure_ascii=False), 900))

print("==== RAS")
t = get("https://empleo.ras-interim.es/sitemap.xml")
if t:
    pairs = re.findall(r"<loc>([^<]+/jobs/[^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", t)
    print("job urls", len(pairs), pairs[:3])
    if pairs:
        p = get(pairs[0][0])
        for j in ldjson(p): print("  ld:", sq(json.dumps(j, ensure_ascii=False), 900))
get("https://empleo.ras-interim.es/jobs.rss")

print("==== IMAN")
t = get("https://empleo.imancorp.es/jobs")
if t:
    print("teamtailor" in t, "pager", re.findall(r'href="([^"]*page=\d+[^"]*)"', t)[:4])
    print("location filter", re.findall(r'href="([^"]*location[^"]*)"', t)[:6])
get("https://empleo.imancorp.es/jobs.rss")

print("==== MEDITEMPUS")
t = get("https://www.meditempus.com/oferta-sitemap.xml")
if t:
    pairs = re.findall(r"<loc>([^<]+)</loc>\s*<lastmod>([^<]+)</lastmod>", t); print("ofertas", len(pairs), pairs[-3:])
