"""Daily job-offer collector for Yassine (Mataró). Runs on GitHub Actions.

Reads every source in full through its official/public listing (open data feed,
sitemaps, per-town pages), always respecting robots.txt, keeps only offers in
towns reachable from Mataró, flags hard blockers, and writes
jobs/data/offers.json for the daily scheduled task (read with jobs/list.py).

Sources:
  xaloc       per-town list pages (municipality filter) + every offer's detail page
  feinaactiva official open-data XML feed (all published offers in Catalonia)
  eurofirms   offers sitemap (town in URL) + JobPosting data of each offer
  randstad    per-town listing pages + JobPosting data of each offer
  iman        per-town filter on empleo.imancorp.es + offer pages
  ras         sitemap of empleo.ras-interim.es + JobPosting data of each offer
  meditempus  offers sitemap + offer pages ("Población", "Publicación")
Not readable by rule (robots.txt / JS-only): Adecco, Manpower, Crit -> the task
uses web searches for those.
"""
import datetime as dt, gzip, html, json, os, re, sys, time, traceback
import unicodedata, urllib.request, urllib.robotparser
from urllib.parse import urlparse, quote
import xml.etree.ElementTree as ET

UA = "YassineJobFeed/1.0 (+https://github.com/Yassine-XD/bus-times)"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "data", "offers.json")
CACHE = os.path.join(HERE, "data", "cache.json.gz")
TODAY = dt.date.today().isoformat()

# ---------------------------------------------------------------- towns
TOWNS = {  # canonical name: Xaloc municipality code
    "Mataró": "08121", "Argentona": "08009", "Cabrera de Mar": "08029", "Cabrils": "08030",
    "Vilassar de Mar": "08219", "Vilassar de Dalt": "08214", "Premià de Mar": "08172",
    "Premià de Dalt": "08230", "Teià": "08281", "El Masnou": "08118", "Alella": "08003",
    "Montgat": "08126", "Tiana": "08282", "Badalona": "08015", "Sant Adrià de Besòs": "08194",
    "Sant Andreu de Llavaneres": "08197", "Sant Vicenç de Montalt": "08264",
    "Caldes d'Estrac": "08033", "Arenys de Mar": "08006", "Arenys de Munt": "08007",
    "Canet de Mar": "08040", "Sant Pol de Mar": "08235", "Calella": "08035",
    "Pineda de Mar": "08163", "Santa Susanna": "08261", "Malgrat de Mar": "08110",
    "Palafolls": "08155", "Tordera": "08284", "Dosrius": "08075", "Granollers": "08096",
    "Les Franqueses del Vallès": "08086", "Canovelles": "08041", "La Roca del Vallès": "08181",
    "Lliçà d'Amunt": "08107", "Lliçà de Vall": "08108", "Parets del Vallès": "08159",
    "Montmeló": "08135", "Montornès del Vallès": "08136", "Mollet del Vallès": "08124",
    "Martorelles": "08115", "Vilanova del Vallès": "08902", "Cardedeu": "08046",
    "Llinars del Vallès": "08106", "Sant Celoni": "08202", "Sabadell": "08187",
}
EXTRA_ALIASES = {  # Spanish spellings / short forms -> canonical
    "mataro": "Mataró", "masnou": "El Masnou", "premia de mar": "Premià de Mar",
    "premia de dalt": "Premià de Dalt", "vilasar de mar": "Vilassar de Mar",
    "vilasar de dalt": "Vilassar de Dalt", "san adrian de besos": "Sant Adrià de Besòs",
    "sant adria": "Sant Adrià de Besòs", "san andres de llavaneras": "Sant Andreu de Llavaneres",
    "llavaneres": "Sant Andreu de Llavaneres", "san vicente de montalt": "Sant Vicenç de Montalt",
    "caldas de estrach": "Caldes d'Estrac", "caldes d estrac": "Caldes d'Estrac",
    "san pol de mar": "Sant Pol de Mar", "santa susana": "Santa Susanna",
    "franqueses del valles": "Les Franqueses del Vallès", "franqueses": "Les Franqueses del Vallès",
    "canovellas": "Canovelles", "roca del valles": "La Roca del Vallès",
    "llica d amunt": "Lliçà d'Amunt", "llica de amunt": "Lliçà d'Amunt",
    "llica de vall": "Lliçà de Vall", "montornes": "Montornès del Vallès",
    "mollet": "Mollet del Vallès", "martorellas": "Martorelles", "san celoni": "Sant Celoni",
    "llinars": "Llinars del Vallès", "parets": "Parets del Vallès",
}

def norm(s):
    s = html.unescape(s or "")
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    m = re.match(r"(.*) (les|la|el|l)$", s)          # "franqueses del valles les"
    if m: s = m.group(2) + " " + m.group(1)
    return s

ALIAS = {}
for name in TOWNS:
    n = norm(name); ALIAS[n] = name
    ALIAS[re.sub(r"^(les|la|el|l) ", "", n)] = name
for k, v in EXTRA_ALIASES.items():
    ALIAS[norm(k)] = v
TEXT_ALIAS = {a: v for a, v in ALIAS.items() if len(a) >= 6 and a not in ("calella",)} | {"calella": "Calella"}

def town_of(s):
    """Exact town match for a location field."""
    n = norm(s)
    if n in ALIAS: return ALIAS[n]
    n2 = re.sub(r"^(les|la|el|l) ", "", n)
    if n2 in ALIAS: return ALIAS[n2]
    n3 = re.sub(r" (barcelona|bcn|maresme|valles oriental|valles occidental)$", "", n)
    return ALIAS.get(n3)

def towns_in_text(s):
    n = " " + norm(s) + " "
    return sorted({v for a, v in TEXT_ALIAS.items() if " " + a + " " in n})

# ---------------------------------------------------------------- flags
FLAG_RX = {
    "forklift": r"carretiller|carreto elevador|carreto|carretilla|\bretractil\b|toro mecanic|transpalet electric|apilador electric",
    "car": r"vehicle propi|vehiculo propio|cotxe propi|coche propio|carnet de conduir|carnet de conducir|"
           r"permiso de conducir|permis de conduir|carnet b\b|carne b\b|carnet tipus b|disponer de vehiculo|"
           r"mitja de transport propi|medio de transporte propio|transporte propio|transport propi",
    "lang_level": r"(catala|castella|castellano|espanol|catalan)[^.;]{0,45}\b(b1|b2|c1|c2|mitja|alt|nivel medio|nivel alto|"
                  r"avanzado|fluido|fluid|nativo|natiu|correctamente|correctament)\b|\b(b1|b2|c1)\b|"
                  r"catala[^.;]{0,30}imprescindible|imprescindible[^.;]{0,30}catala",
    "diploma": r"\bcfgm\b|\bcfgs\b|cicle formatiu|ciclo formativo|grau mitja|grado medio|grau superior|grado superior|"
               r"\bfp ?(i|ii|1|2)\b|formacion profesional|formacio professional|titulacio universit|titulacion universit|grado universit|llicenciat|licenciad",
    "kitchen_meat_alcohol": r"cuiner|cocinero|\bcuina\b|cocina|cambrer|camarer|carnisser|carnicer|xarcut|charcut|sommelier|"
                            r"barman|bartender|escorxador|matadero|porcino|elaborats carnis|productos carnicos|bodega|celler|vinos",
}
HARD_FLAGS = ("forklift", "car", "lang_level", "diploma", "kitchen_meat_alcohol")
SOFT_RX = r"valora|valorable|es valorar|se valorar|deseable|preferible|\bplus\b|no imprescindible|no es imprescindible|opcional"

def flags_for(title, text):
    """Returns (flags, why). Checked sentence by sentence: if every sentence with the blocker word
    also says 'valorable/deseable/…', the flag becomes '<flag>?' (soft, not mandatory)."""
    raw = html.unescape(title + ". " + text)
    sents = [norm(x) for x in re.split(r"[.;:\n•·\-–]\s|\n|[!?]", raw) if x.strip()]
    t = " ".join(sents)
    f, why = [], {}
    for k, rx in FLAG_RX.items():
        hits = [x for x in sents if re.search(rx, x)]
        if not hits: continue
        soft = all(re.search(SOFT_RX, x) for x in hits)
        f.append(k + ("?" if soft else ""))
        why[k] = " … ".join(x[:160] for x in hits[:3])
    if re.search(r"\bangles\b|\bingles\b|english", t): f.append("english")
    m = re.search(r"experiencia (?:en l ocupacio )?(?:mesos |meses )?(\d{1,2})\b", t)
    if m and m.group(1) != "0": f.append(f"exp:{m.group(1)}")
    return f, why

# ---------------------------------------------------------------- http
_robots, _last = {}, {}

def allowed(url):
    host = "{0.scheme}://{0.netloc}".format(urlparse(url))
    if host not in _robots:
        rp = urllib.robotparser.RobotFileParser()
        try:
            rp.parse(_raw(host + "/robots.txt", 20).splitlines())
        except Exception:
            rp.parse([])
        _robots[host] = rp
    return _robots[host].can_fetch(UA, url)

def _raw(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "es-ES,es;q=0.9,ca;q=0.8"})
    body = urllib.request.urlopen(req, timeout=timeout).read()
    if body[:2] == b"\x1f\x8b": body = gzip.decompress(body)
    return body.decode("utf-8", "replace")

def get(url, delay=0.6, tries=2):
    if not allowed(url):
        raise PermissionError("robots.txt disallows " + url)
    host = urlparse(url).netloc
    wait = _last.get(host, 0) + delay - time.time()
    if wait > 0: time.sleep(wait)
    for i in range(tries):
        try:
            t = _raw(url); _last[host] = time.time(); return t
        except urllib.error.HTTPError as e:
            _last[host] = time.time()
            if e.code in (404, 410): return None
            if i == tries - 1: raise
        except Exception:
            _last[host] = time.time()
            if i == tries - 1: raise
        time.sleep(3)

def text_of(h):
    h = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", h or "", flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>", "\n", h, flags=re.I)
    return re.sub(r"[ \t\r\f\v]+", " ", html.unescape(re.sub(r"<[^>]+>", " ", h))).replace(" \n", "\n").strip()

def jobposting(h):
    for m in re.findall(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', h or "", re.S | re.I):
        try:
            d = json.loads(m.strip())
        except Exception:
            continue
        for x in (d if isinstance(d, list) else d.get("@graph", [d])):
            if isinstance(x, dict) and x.get("@type") == "JobPosting":
                return x
    return None

def jp_locality(jp):
    loc = jp.get("jobLocation") or []
    if isinstance(loc, dict): loc = [loc]
    for l in loc:
        a = (l or {}).get("address") or {}
        if isinstance(a, dict) and a.get("addressLocality"): return a["addressLocality"]
    return ""

def dmy(s):
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s or "")
    return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}" if m else ""

def iso(s):
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    return m.group(0) if m else ""

def salary_jp(jp):
    b = jp.get("baseSalary") or {}
    v = b.get("value") if isinstance(b, dict) else None
    if isinstance(v, dict):
        val = v.get("value") or (f"{v.get('minValue')}-{v.get('maxValue')}" if v.get("minValue") else "")
        return f"{val} {b.get('currency','')}/{v.get('unitText','')}".strip() if val else ""
    return ""

def offer(src, oid, title, town, url, text, published="", modified="", company="", salary="", town_note=""):
    fl, why = flags_for(title or "", text or "")
    return {"src": src, "id": str(oid), "title": re.sub(r"\s+", " ", html.unescape(title or "")).strip(),
            "town": town, "town_note": town_note, "url": url, "published": published, "modified": modified,
            "company": company, "salary": salary,
            "text": re.sub(r"\n\s*\n+", "\n", text or "").strip()[:2500],
            "flags": fl, "why": why}

# ---------------------------------------------------------------- sources
def src_xaloc(cache):
    out = []
    for name, code in TOWNS.items():
        ids = []
        for page in range(0, 6):
            url = ("https://xaloc.diba.cat/ofertes-de-feina?offer_type%5Bxaloc%5D=xaloc&offer_type%5Bpublic%5D=0"
                   f"&municipality%5B0%5D={code}&disability=All&day=All&map=false" + (f"&page={page}" if page else ""))
            h = get(url, 0.8) or ""
            new = [i for i in dict.fromkeys(re.findall(r"/ofertes-de-feina/(\d{5,7})", h)) if i not in ids]
            ids += new
            if not new or f"page={page + 1}" not in h: break
        for oid in ids:
            u = f"https://xaloc.diba.cat/ofertes-de-feina/{oid}"
            h = get(u, 0.8)
            if not h: continue
            t = text_of(h); flat = re.sub(r"\s+", " ", t)
            m = re.search(r"Publicat - Modificat\s*([\d/]+)\s*-\s*([\d/]+)", flat)
            pub, mod = (dmy(m.group(1)), dmy(m.group(2))) if m else ("", "")
            loc = re.search(r"Localització\s+(.+?)\s+Ocupació", flat)
            tm = re.search(r"Tasques específiques(.*?)(?:Inscripció oberta|Si vols apuntar-te)", flat)
            title = re.search(r"<title>\s*(?:[\d_]+-\s*)?([^<|]+)", h)
            body = tm.group(1) if tm else flat[:2000]
            town = town_of(loc.group(1)) if loc else name
            out.append(offer("xaloc", oid, title.group(1) if title else oid, town or name, u, body, pub, mod,
                             town_note="" if town else f"list town {name}, location {loc.group(1) if loc else '?'}"))
    return out

def src_feinaactiva(cache):
    t = get("https://feinaactiva.gencat.cat/api/offers/offers-xml", 0, 3)
    out = []
    for a in ET.fromstring(t).iter("ad"):
        g = lambda k: (a.findtext(k) or "").strip()
        town = town_of(g("city"))
        if not town: continue
        text = "\n".join(x for x in [g("content"), "Experiència: " + g("experience"), "Requisits: " + g("requirements"),
                                     "Estudis: " + g("studies"), g("contract"), g("workingHours")] if x.strip(" :"))
        sal = f"{g('salaryMin')}-{g('salaryMax')} €/mes" if g("salaryMin") else ""
        out.append(offer("feinaactiva", g("id"), g("title"), town, g("url"), text, dmy(g("date")), "", g("company"), sal))
    return out

def src_eurofirms(cache):
    sm = get("https://jobs.eurofirms.com/sitemap_es-ES_offers.xml", 0)
    out = []
    for u in re.findall(r"<loc>([^<]+)</loc>", sm):
        m = re.match(r"https://jobs\.eurofirms\.com/es/es/([^/]+)/", u)
        town = town_of(m.group(1).replace("-", " ")) if m else None
        if not town: continue
        d = cache.get(u)
        if d is not None and d.get("dead") and not d.get("v2"): d = None   # retry pre-fix dead markers
        if d is None:
            h = get(u, 0.8)
            jp = jobposting(h) if h else None
            if jp:
                d = {"title": jp.get("title", ""), "text": text_of(jp.get("description", "")),
                     "published": iso(jp.get("datePosted")), "loc": jp_locality(jp), "salary": salary_jp(jp)}
            elif h:
                ti = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S) or re.search(r"<title>([^<|]+)", h)
                d = {"title": text_of(ti.group(1)) if ti else u.rsplit("/", 1)[-1], "published": "", "loc": "",
                     "salary": "", "text": text_of(h)[:2500], "no_jobposting": True}
            else:
                d = {"dead": True, "v2": True}
            cache[u] = d
        if d.get("dead"): continue
        code = re.search(r"(\d{3}-\d{6})$", u.rstrip("/"))
        out.append(offer("eurofirms", code.group(1) if code else u, d["title"], town_of(d.get("loc", "")) or town, u,
                         d["text"], d["published"], salary=d.get("salary", "")))
    return out

def randstad_slugs(name):
    n = norm(name).replace(" ", "-")
    base = re.sub(r"^(les|la|el|l)-", "", n)
    art = n.split("-")[0] if base != n else ""
    return list(dict.fromkeys([n, base] + ([base + "-" + art] if art else [])))

def src_randstad(cache):
    out, seen, tried = [], set(), []
    for name in TOWNS:
        for slug in randstad_slugs(name):
            u = f"https://www.randstad.es/candidatos/ofertas-empleo/p-barcelona/c-{slug}/"
            h = get(u, 1.0)
            links = list(dict.fromkeys(re.findall(r"ofertas-empleo/oferta/([a-z0-9\-]+-\d{6,8})/", h or "")))
            if h and links:
                tried.append(slug); seen.update(links); break
    print("   randstad town pages with offers:", tried)
    for slug in seen:
        u = f"https://www.randstad.es/candidatos/ofertas-empleo/oferta/{slug}/"
        d = cache.get(u)
        if d is None:
            h = get(u, 1.0)
            jp = jobposting(h) if h else None
            if jp:
                d = {"title": jp.get("title", ""), "text": text_of(jp.get("description", "")),
                     "published": iso(jp.get("datePosted")), "loc": jp_locality(jp), "salary": salary_jp(jp)}
            elif h:
                loc = re.search(r'"addressLocality"\s*:\s*"([^"]+)"', h)
                dp = re.search(r'"datePosted"\s*:\s*"([^"]+)"', h)
                ti = re.search(r'"title"\s*:\s*"([^"]+)"', h) or re.search(r"<title>(?:Oferta de empleo )?([^<]+)", h)
                desc = re.search(r'name="description" content="([^"]+)', h)
                d = {"title": ti.group(1) if ti else slug, "loc": loc.group(1) if loc else "",
                     "published": iso(dp.group(1)) if dp else "", "salary": "",
                     "text": text_of(h)[:2500] if not desc else desc.group(1) + "\n" + text_of(h)[:2000]}
            else:
                d = {"dead": True}
            cache[u] = d
        if d.get("dead"): continue
        town = town_of(d.get("loc", ""))
        if not town: continue
        out.append(offer("randstad", slug.rsplit("-", 1)[-1], d["title"], town, u, d["text"], d["published"],
                         salary=d.get("salary", "")))
    return out

def src_iman(cache):
    h = get("https://empleo.imancorp.es/jobs", 0.8)
    m = re.search(r'<select[^>]+name="location"[^>]*>(.*?)</select>', h, re.S)
    opts = re.findall(r'<option[^>]*value="(city:[^"]+)"[^>]*>([^<]*)<', m.group(1)) if m else []
    out, links = [], {}
    for val, label in opts:
        town = town_of(label)
        if not town: continue
        for page in range(1, 5):
            lh = get(f"https://empleo.imancorp.es/jobs?location={quote(val)}" + (f"&page={page}" if page > 1 else ""), 0.8) or ""
            new = [l for l in dict.fromkeys(re.findall(r'href="(https://empleo\.imancorp\.es/jobs/[^"?#]+)"', lh)) if l not in links]
            for l in new: links[l] = town
            if not new or f"page={page + 1}" not in lh: break
    for u, town in links.items():
        d = cache.get(u)
        if d is None:
            ph = get(u, 0.8)
            jp = jobposting(ph) if ph else None
            if jp:
                d = {"title": jp.get("title", ""), "text": text_of(jp.get("description", "")),
                     "published": iso(jp.get("datePosted")), "salary": salary_jp(jp)}
            elif ph:
                ti = re.search(r"<h1[^>]*>(.*?)</h1>", ph, re.S) or re.search(r"<title>([^<]+)", ph)
                d = {"title": text_of(ti.group(1)) if ti else u.rsplit("/", 1)[-1], "published": "", "salary": "",
                     "text": text_of(re.search(r"<main.*?</main>", ph, re.S).group(0) if "<main" in ph else ph)[:2500]}
            else:
                d = {"dead": True}
            cache[u] = d
        if d.get("dead"): continue
        out.append(offer("iman", u.rsplit("/", 1)[-1], d["title"], town, u, d["text"], d.get("published", ""),
                         salary=d.get("salary", "")))
    return out

RAS_AREA = re.compile(r"ras (matar|granoll|mollet|sabadell)|maresme|valles oriental", re.I)

def src_ras(cache):
    sm = get("https://empleo.ras-interim.es/sitemap.xml", 0)
    pairs = re.findall(r"<loc>(https://empleo\.ras-interim\.es/jobs/[^<]+)</loc>\s*(?:<lastmod>([^<]+)</lastmod>)?", sm)
    limit = (dt.date.today() - dt.timedelta(days=45)).isoformat()
    out, fetched = [], 0
    for u, lm in pairs:
        d = cache.get(u)
        if d is None:
            if (lm and lm[:10] < limit) or fetched >= 600: continue
            h = get(u, 0.7); fetched += 1
            jp = jobposting(h) if h else None
            d = cache[u] = {"title": jp.get("title", ""), "text": text_of(jp.get("description", "")),
                            "published": iso(jp.get("datePosted")), "loc": jp_locality(jp),
                            "salary": salary_jp(jp)} if jp else {"dead": True}
        if d.get("dead"): continue
        town = town_of(d.get("loc", ""))
        note = ""
        if not town:
            in_text = [t for t in towns_in_text(d["text"]) if t != "Sabadell" or "sabadell" in norm(d.get("loc", ""))]
            if in_text: town, note = in_text[0], f"location field '{d.get('loc')}', town found in text"
            elif RAS_AREA.search(d.get("loc", "")): town, note = d["loc"], "office only — workplace not stated, check"
            else: continue
        out.append(offer("ras", u.rsplit("/", 1)[-1].split("-")[0], d["title"], town, u, d["text"],
                         d["published"], salary=d.get("salary", ""), town_note=note))
    return out

def src_meditempus(cache):
    sm = get("https://www.meditempus.com/oferta-sitemap.xml", 0)
    out = []
    for u in re.findall(r"<loc>(https://www\.meditempus\.com/oferta/[^<]+)</loc>", sm):
        d = cache.get(u)
        if d is None:
            h = get(u, 0.8)
            if not h:
                cache[u] = {"dead": True}; continue
            t = text_of(h); flat = re.sub(r"\s+", " ", t)
            ti = re.search(r"<h1[^>]*>(.*?)</h1>", h, re.S)
            pob = re.search(r"Población\s+(.+?)\s+Provincia", flat)
            pub = re.search(r"Publicación\s+([\d/]+)", flat)
            i = flat.find("Detalles de la oferta")
            d = cache[u] = {"title": text_of(ti.group(1)) if ti else u, "loc": pob.group(1) if pob else "",
                            "published": dmy(pub.group(1)) if pub else "",
                            "text": flat[max(0, i - 1800):i + 200] if i > 0 else flat[:2000]}
        if d.get("dead"): continue
        town = town_of(d.get("loc", ""))
        if not town: continue
        out.append(offer("meditempus", u.rstrip("/").rsplit("/", 1)[-1], d["title"], town, u, d["text"], d["published"]))
    return out

class SeenDict(dict):
    """Cache wrapper: any entry read or written gets _seen=today (so it is kept)."""
    def __init__(self, base):
        super().__init__(); self.base = base
    def get(self, k, default=None):
        d = self.base.get(k, default)
        if isinstance(d, dict): d["_seen"] = TODAY
        return d
    def __setitem__(self, k, v):
        if isinstance(v, dict): v["_seen"] = TODAY
        self.base[k] = v
    def setdefault(self, k, v):
        if k not in self.base: self[k] = v
        return self.get(k)

SOURCES = [("xaloc", src_xaloc), ("feinaactiva", src_feinaactiva), ("eurofirms", src_eurofirms),
           ("randstad", src_randstad), ("iman", src_iman), ("ras", src_ras), ("meditempus", src_meditempus)]

# ---------------------------------------------------------------- main
def main():
    sys.stdout.reconfigure(line_buffering=True)
    only = set(sys.argv[1:])
    prev = {}
    if os.path.exists(OUT):
        old = json.load(open(OUT, encoding="utf-8"))
        prev_offers = {(o["src"], o["id"]): o for o in old.get("offers", [])}
        prev_status = old.get("sources", {})
        baseline = False
    else:
        prev_offers, prev_status, baseline = {}, {}, True
    cache = json.load(gzip.open(CACHE, "rt", encoding="utf-8")) if os.path.exists(CACHE) else {}
    offers, status = [], {}
    for name, fn in SOURCES:
        if only and name not in only:
            offers += [o for o in prev_offers.values() if o["src"] == name]
            status[name] = prev_status.get(name, {"ok": False, "error": "not run"}); continue
        t0 = time.time()
        sc = SeenDict(cache.setdefault(name, {}))
        try:
            got = fn(sc)
            status[name] = {"ok": True, "count": len(got), "secs": int(time.time() - t0), "at": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")}
            offers += got
        except Exception as e:
            traceback.print_exc()
            status[name] = {"ok": False, "error": f"{type(e).__name__}: {e}"[:300],
                            "at": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M")}
            offers += [o for o in prev_offers.values() if o["src"] == name]   # keep yesterday's
        print(f"{name}: {status[name]}")
    # dedupe and first_seen tracking
    final = {}
    for o in offers:
        k = (o["src"], o["id"])
        p = prev_offers.get(k)
        o["first_seen"] = p.get("first_seen", "") if p else ("" if baseline else TODAY)
        final[k] = o
    # prune cache entries not seen in any source listing for 21 days
    cutoff = (dt.date.today() - dt.timedelta(days=21)).isoformat()
    for name in cache:
        cache[name] = {u: d for u, d in cache[name].items() if d.get("_seen", TODAY) >= cutoff}
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    data = {"built": dt.datetime.now(dt.timezone.utc).replace(tzinfo=None).strftime("%Y-%m-%d %H:%M UTC"), "sources": status,
            "offers": sorted(final.values(), key=lambda o: (o["src"], o["town"], o["id"]))}
    json.dump(data, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    json.dump(cache, gzip.open(CACHE, "wt", encoding="utf-8"), ensure_ascii=False)
    print("total offers:", len(final))

if __name__ == "__main__":
    main()
