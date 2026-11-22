"""Probe: where Randstad offer pages keep the job description."""
import re, json, urllib.request
UA = "YassineJobFeed/1.0 (+https://github.com/Yassine-XD/bus-times)"
for u in ["https://www.randstad.es/candidatos/ofertas-empleo/oferta/operario-u-operaria-sector-textil-3024748/",
          "https://www.randstad.es/candidatos/ofertas-empleo/oferta/mozo-a-3024433/"]:
    h = urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=60).read().decode("utf-8", "replace")
    print("==", u, len(h))
    for m in re.finditer(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', h, re.S):
        s = m.group(1); print("  ld+json", len(s), s[:300].replace("\n", " "))
    nd = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h, re.S)
    print("  next_data", len(nd.group(1)) if nd else None)
    for k in ["description", "funciones", "Funciones", "requisitos", "Requisitos", "horario", "Horario", "salario", "jornada", "tus funciones", "qué ofrecemos"]:
        for m in list(re.finditer(k, h))[:2]:
            print(f"  [{k}] @{m.start()}:", re.sub(r"\s+", " ", h[max(0, m.start() - 150):m.start() + 350]).replace("\n", " ")[:500])
