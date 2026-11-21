"""One-off probe: what can be read from each job source (robots.txt respected)."""
import re, sys, gzip, json, urllib.request, urllib.robotparser
from urllib.parse import urlparse

UA = "YassineJobFeed/1.0 (+https://github.com/Yassine-XD/bus-times)"
BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"

robots = {}

def rp_for(url):
    host = urlparse(url).scheme + "://" + urlparse(url).netloc
    if host not in robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(host + "/robots.txt", headers={"User-Agent": UA})
            txt = urllib.request.urlopen(req, timeout=20).read().decode("utf-8", "replace")
            rp.parse(txt.splitlines())
            sm = [l.split(":", 1)[1].strip() for l in txt.splitlines() if l.lower().startswith("sitemap")]
            print(f"[robots] {host}: {len(txt)}b sitemaps={sm[:6]}")
        except Exception as e:
            rp.parse([])
            print(f"[robots] {host}: unavailable ({e}) -> treated as allow-all")
        robots[host] = rp
    return robots[host]

def get(url, n=600, ua=UA):
    rp = rp_for(url)
    if not rp.can_fetch(UA, url):
        print(f"[DISALLOWED by robots] {url}")
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept-Language": "es-ES,es;q=0.9"})
        r = urllib.request.urlopen(req, timeout=40)
        body = r.read()
        if body[:2] == b"\x1f\x8b":
            body = gzip.decompress(body)
        txt = body.decode("utf-8", "replace")
        print(f"[{r.status}] {url} type={r.headers.get('content-type')} size={len(txt)}")
        print("   head:", re.sub(r"\s+", " ", txt[:n]))
        return txt
    except Exception as e:
        print(f"[ERR] {url}: {e}")
        return None

def count(txt, pat, label):
    if txt:
        m = re.findall(pat, txt)
        print(f"   {label}: {len(m)} e.g. {m[:5]}")

print("==== FEINA ACTIVA")
t = get("https://feinaactiva.gencat.cat/api/offers/offers-xml", 1500)
if t:
    count(t, r"<(\w+)>", "tags")
    for town in ["Mataró", "Granollers", "Lliçà", "Argentona", "Vilassar"]:
        print("   ", town, t.count(town))

print("==== XALOC")
get("https://xaloc.diba.cat/ofertes-de-feina/rss.xml")
get("https://xaloc.diba.cat/sitemap.xml")
for code in ["08121", "08096"]:
    t = get("https://xaloc.diba.cat/ofertes-de-feina?offer_type%5Bxaloc%5D=xaloc&offer_type%5Bpublic%5D=0&municipality%5B0%5D=" + code + "&disability=All&day=All&map=false", 200)
    count(t, r"ofertes-de-feina/(\d{6})", "offer ids")

print("==== ADECCO")
t = get("https://www.adecco.com/es-es/sitemap.xml", 1200)
count(t, r"<loc>([^<]+)</loc>", "locs")
t = get("https://www.adecco.com/es-es/ofertas-trabajo?l=Matar%C3%B3", 300)
count(t, r"jobid/[0-9a-f]{20,}", "jobids")
count(t, r"__NEXT_DATA__|application/ld\+json|window\.__", "embedded data")

print("==== RANDSTAD")
t = get("https://www.randstad.es/sitemap.xml", 1200)
count(t, r"<loc>([^<]+)</loc>", "locs")
t = get("https://www.randstad.es/candidatos/ofertas-empleo/p-barcelona/c-mataro/", 300)
count(t, r'href="(/candidatos/ofertas-empleo/oferta/[^"]+)"', "offer links")
count(t, r"__NEXT_DATA__|application/ld\+json", "embedded data")

print("==== MANPOWER")
for u in ["https://www.manpower.es/sitemap.xml", "https://www.manpower.es/es/buscar-empleo?location=Matar%C3%B3"]:
    t = get(u, 600)
    count(t, r"<loc>([^<]+)</loc>", "locs")

print("==== IMAN")
t = get("https://empleo.imancorp.es/sitemap.xml", 800)
count(t, r"<loc>([^<]+)</loc>", "locs")
t = get("https://empleo.imancorp.es/jobs", 300)
count(t, r'href="(https://empleo\.imancorp\.es/jobs/[^"]+)"', "job links")

print("==== RAS")
for u in ["https://empleo.ras-interim.es/sitemap.xml", "https://empleo.ras-interim.es/", "https://ras-interim.trabajos.com/"]:
    t = get(u, 500)
    count(t, r"<loc>([^<]+)</loc>", "locs")

print("==== EUROFIRMS")
t = get("https://jobs.eurofirms.com/sitemap.xml", 800)
count(t, r"<loc>([^<]+)</loc>", "locs")
t = get("https://jobs.eurofirms.com/es/es/trabajo/en-mataro/barcelona", 300)
count(t, r'href="([^"]*oferta[^"]*)"', "offer links")
count(t, r"__NEXT_DATA__|application/ld\+json", "embedded data")

print("==== GI GROUP / CATT / CRIT / MARLEX / MEDITEMPUS")
for u in ["https://es.gigroup.com/sitemap.xml", "https://www.catt.es/sitemap.xml",
          "https://www.crit.es/sitemap.xml", "https://www.marlex.net/sitemap.xml",
          "https://www.meditempus.com/sitemap.xml"]:
    t = get(u, 400)
    count(t, r"<loc>([^<]+)</loc>", "locs")
