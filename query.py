#!/usr/bin/env python3
"""
Can I get to this job by public transport, for this shift?

Checks real timetables (official open data, refreshed twice a week) from
Mataró station to a workplace, with at most 2 vehicles (one change) and a
maximum door-to-door time (default 90 min), for the shift start AND end.

Examples:
  python3 query.py --to "Les Franqueses del Vallès" --day weekday --shift 06:00-14:00
  python3 query.py --to "Granollers" --near "Can Gili" --day saturday --shift 14:00-22:00
  python3 query.py --to "41.6012,2.2950" --date 2026-11-24 --shift 08:00-17:00 --shift 14:00-22:00
  python3 query.py --to "stop:Pla de Llerona" --day weekday --shift 06:00-14:00
"""
import argparse, bisect, datetime as dt, gzip, io, json, math, os, re, sys, unicodedata, urllib.request
from zoneinfo import ZoneInfo

REPO_RAW = "https://raw.githubusercontent.com/Yassine-XD/bus-times/main"
DATA_URL = REPO_RAW + "/data/area.json.gz"
HOME = ("Mataró station", 41.5333, 2.4450, 650)  # name, lat, lon, radius of usable stops (m)
WALK_M_PER_MIN = 75.0
DETOUR = 1.25          # straight line -> street distance
TRANSFER_RADIUS = 350  # m between two stops for a change
MIN_CHANGE = 2         # min
EARLY = 5              # arrive at least 5 min before the shift starts

TOWNS = {
    "Mataró": (41.5381, 2.4445), "Argentona": (41.5536, 2.4017), "Cabrera de Mar": (41.5272, 2.3933),
    "Cabrils": (41.5272, 2.3683), "Vilassar de Mar": (41.5056, 2.3925), "Vilassar de Dalt": (41.5167, 2.3583),
    "Premià de Mar": (41.4917, 2.3625), "Premià de Dalt": (41.5044, 2.3497), "Teià": (41.4983, 2.3225),
    "El Masnou": (41.4797, 2.3192), "Alella": (41.4947, 2.2944), "Montgat": (41.4686, 2.2800),
    "Tiana": (41.4828, 2.2672), "Badalona": (41.4500, 2.2475), "Sant Adrià de Besòs": (41.4306, 2.2183),
    "Sant Andreu de Llavaneres": (41.5722, 2.4831), "Sant Vicenç de Montalt": (41.5800, 2.5100),
    "Caldes d'Estrac": (41.5714, 2.5278), "Arenys de Mar": (41.5814, 2.5506), "Arenys de Munt": (41.6125, 2.5397),
    "Canet de Mar": (41.5906, 2.5806), "Sant Pol de Mar": (41.6019, 2.6247), "Calella": (41.6139, 2.6547),
    "Pineda de Mar": (41.6264, 2.6894), "Santa Susanna": (41.6361, 2.7111), "Malgrat de Mar": (41.6464, 2.7411),
    "Palafolls": (41.6694, 2.7506), "Tordera": (41.7000, 2.7186), "Dosrius": (41.5911, 2.4086),
    "Òrrius": (41.5531, 2.3519), "Granollers": (41.6083, 2.2875), "Les Franqueses del Vallès": (41.6300, 2.2969),
    "Canovelles": (41.6175, 2.2814), "La Roca del Vallès": (41.5867, 2.3275), "Cardedeu": (41.6400, 2.3594),
    "Llinars del Vallès": (41.6411, 2.4031), "Sant Celoni": (41.6900, 2.4900),
    "Santa Maria de Palautordera": (41.6950, 2.4469), "Lliçà d'Amunt": (41.6153, 2.2394),
    "Lliçà de Vall": (41.5869, 2.2394), "Bigues i Riells": (41.6833, 2.2250), "L'Ametlla del Vallès": (41.6667, 2.2611),
    "La Garriga": (41.6797, 2.2836), "Parets del Vallès": (41.5728, 2.2333), "Montmeló": (41.5514, 2.2486),
    "Montornès del Vallès": (41.5428, 2.2672), "Vilanova del Vallès": (41.5500, 2.2950),
    "Mollet del Vallès": (41.5403, 2.2131), "Martorelles": (41.5317, 2.2386), "Sant Fost de Campsentelles": (41.5072, 2.2397),
    "Santa Perpètua de Mogoda": (41.5333, 2.1833), "Montcada i Reixac": (41.4833, 2.1867),
    "Palau-solità i Plegamans": (41.5833, 2.1786), "Polinyà": (41.5578, 2.1561), "Sabadell": (41.5486, 2.1075),
    "Barberà del Vallès": (41.5153, 2.1250), "Barcelona": (41.3874, 2.1686),
}


def norm(s):
    s = unicodedata.normalize("NFKD", s.lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def dist_m(a_lat, a_lon, b_lat, b_lon):
    dy = (a_lat - b_lat) * 110540.0
    dx = (a_lon - b_lon) * 111320.0 * math.cos(math.radians((a_lat + b_lat) / 2))
    return math.hypot(dx, dy)


def walk_min(m):
    return int(math.ceil(m * DETOUR / WALK_M_PER_MIN))


def hhmm(t):
    t = int(t) % 1440
    return f"{t // 60:02d}:{t % 60:02d}"


def parse_hhmm(s):
    h, m = s.strip().split(":")
    return int(h) * 60 + int(m)


def load(path):
    if re.match(r"^https?://", path):
        req = urllib.request.Request(path, headers={"User-Agent": "bus-times query"})
        raw = urllib.request.urlopen(req, timeout=120).read()
    else:
        raw = open(path, "rb").read()
    return json.loads(gzip.decompress(raw).decode("utf-8"))


class Net:
    def __init__(self, data, day):
        self.d = data
        self.stops = data["stops"]
        start = dt.date.fromisoformat(data["start"])
        di = (day - start).days
        if not 0 <= di < data["days"]:
            raise SystemExit(f"Date {day} is outside the timetable data ({data['start']} + {data['days']} days).")
        on = {i for i, s in enumerate(data["services"]) if di in s}
        prev = {i for i, s in enumerate(data["services"]) if (di - 1) in s}
        self.trips = []
        for r, s, st, tm in data["trips"]:
            if s in on:
                self.trips.append((r, st, tm))
            if s in prev and tm[-1] >= 1440:  # after-midnight part of yesterday's trips
                self.trips.append((r, st, [x - 1440 for x in tm]))
        self.at = {}  # stop -> sorted [(time, trip, pos)]
        for ti, (_, st, tm) in enumerate(self.trips):
            for p in range(len(st) - 1):
                self.at.setdefault(st[p], []).append((tm[p], ti, p))
        for v in self.at.values():
            v.sort()
        self.grid = {}
        for i, (_, la, lo) in enumerate(self.stops):
            self.grid.setdefault((int(la / 0.004), int(lo / 0.005)), []).append(i)
        self._near = {}

    def around(self, lat, lon, radius):
        out = {}
        cy, cx = int(lat / 0.004), int(lon / 0.005)
        k = int(radius / 400) + 1
        for y in range(cy - k, cy + k + 1):
            for x in range(cx - k, cx + k + 1):
                for i in self.grid.get((y, x), ()):
                    m = dist_m(lat, lon, self.stops[i][1], self.stops[i][2])
                    if m <= radius:
                        out[i] = walk_min(m)
        return out

    def near(self, s):
        if s not in self._near:
            _, la, lo = self.stops[s]
            self._near[s] = self.around(la, lo, TRANSFER_RADIUS)
        return self._near[s]

    def route(self, ti):
        return self.d["routes"][self.trips[ti][0]][0]

    def journeys(self, src, dst, t_from, t_to, max_dur):
        """All journeys leaving src (incl. walk) at >= t_from and arriving dst (incl. walk) <= t_to."""
        res = []
        for s0, w0 in src.items():
            lst = self.at.get(s0, [])
            for dep, ti, p in lst[bisect.bisect_left(lst, (t_from + w0, -1, -1)):]:
                if dep > t_to:
                    break
                leave = dep - w0
                _, st, tm = self.trips[ti]
                for q in range(p + 1, len(st)):
                    s1, a1 = st[q], tm[q]
                    if a1 - leave > max_dur or a1 > t_to:
                        break
                    if s1 in dst:
                        arr = a1 + dst[s1]
                        if arr <= t_to and arr - leave <= max_dur:
                            res.append((leave, arr, [(ti, s0, dep, s1, a1)], w0, dst[s1]))
                    for s2, wt in self.near(s1).items():
                        lst2 = self.at.get(s2, [])
                        lo = a1 + wt + MIN_CHANGE
                        for d2, tj, p2 in lst2[bisect.bisect_left(lst2, (lo, -1, -1)):]:
                            if d2 - leave > max_dur or d2 > t_to:
                                break
                            if tj == ti or self.trips[tj][0] == self.trips[ti][0]:
                                continue
                            _, st2, tm2 = self.trips[tj]
                            for q2 in range(p2 + 1, len(st2)):
                                s3, a3 = st2[q2], tm2[q2]
                                if a3 - leave > max_dur or a3 > t_to:
                                    break
                                if s3 in dst:
                                    arr = a3 + dst[s3]
                                    if arr <= t_to and arr - leave <= max_dur:
                                        res.append((leave, arr, [(ti, s0, dep, s1, a1), (tj, s2, d2, s3, a3)], w0, dst[s3]))
        return res

    def describe(self, j):
        leave, arr, legs, w0, w1 = j
        parts = []
        for ti, a, ta, b, tb in legs:
            parts.append(f"{self.route(ti).split(' ')[0]} {hhmm(ta)} {self.stops[a][0]} → {hhmm(tb)} {self.stops[b][0]}")
        return " + ".join(parts) + f"  (walk {w0}+{w1} min, {arr - leave} min total, {len(legs)} vehicle{'s' if len(legs) > 1 else ''})"


def pick_go(js):
    # latest departure that still arrives on time; then fewer vehicles, less walking
    return max(js, key=lambda j: (j[0], -len(j[2]), -(j[3] + j[4]))) if js else None


def pick_back(js):
    return min(js, key=lambda j: (j[1], len(j[2]), j[3] + j[4])) if js else None


def resolve(net, to, near, radius):
    m = re.match(r"^\s*(-?\d+\.\d+)\s*,\s*(-?\d+\.\d+)\s*$", to)
    if m:
        lat, lon = float(m.group(1)), float(m.group(2))
        return f"point {lat:.4f},{lon:.4f}", net.around(lat, lon, radius or 900)
    text = to[5:] if to.lower().startswith("stop:") else None
    town = None
    if text is None:
        n = norm(to)
        for name in TOWNS:
            if norm(name) == n:
                town = name
        if not town:
            cands = [name for name in TOWNS if n and n in norm(name)]
            if len(cands) == 1:
                town = cands[0]
        if not town:
            text = to
    if town and not near:
        lat, lon = TOWNS[town]
        return f"{town} (stops within {radius or 1500} m of the centre)", net.around(lat, lon, radius or 1500)
    q = norm(near or text)
    hits = [i for i, (nm, _, _) in enumerate(net.stops) if q in norm(nm)]
    if town:
        lat, lon = TOWNS[town]
        hits = [i for i in hits if dist_m(lat, lon, net.stops[i][1], net.stops[i][2]) < 6000]
    if not hits:
        raise SystemExit(f"No stop matches '{near or text}'. Try a town name, a stop name, or 'lat,lon'.")
    dst = {}
    for i in hits:
        for s, w in net.around(net.stops[i][1], net.stops[i][2], radius or 500).items():
            dst[s] = min(dst.get(s, 99), w)
    names = sorted({net.stops[i][0] for i in hits})[:4]
    return f"stops matching '{near or text}'{' in ' + town if town else ''}: {', '.join(names)}", dst


def next_date(kind, start):
    kinds = {"weekday": range(0, 5), "saturday": [5], "sunday": [6],
             "mon": [0], "tue": [1], "wed": [2], "thu": [3], "fri": [4], "sat": [5], "sun": [6]}
    ok = kinds[kind]
    d = start
    while d.weekday() not in ok:
        d += dt.timedelta(days=1)
    return d


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--to", required=True, help="town, 'stop:<name>', or 'lat,lon'")
    ap.add_argument("--near", help="stop-name text near the workplace (e.g. a polígono name)")
    ap.add_argument("--shift", action="append", required=True, help="HH:MM-HH:MM (repeat for rotating shifts)")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--date", help="YYYY-MM-DD")
    g.add_argument("--day", default="weekday", help="weekday | saturday | sunday | mon..sun (next one)")
    ap.add_argument("--max", type=int, default=90, help="max minutes door to door (default 90)")
    ap.add_argument("--wait", type=int, default=45, help="max wait after the shift ends (default 45)")
    ap.add_argument("--radius", type=int, help="metres around the place to look for stops")
    ap.add_argument("--data", default=os.environ.get("BUS_TIMES_DATA", DATA_URL))
    a = ap.parse_args()

    data = load(a.data)
    today = dt.datetime.now(ZoneInfo("Europe/Madrid")).date()
    base = max(today, dt.date.fromisoformat(data["start"]))
    day = dt.date.fromisoformat(a.date) if a.date else next_date(a.day, base)
    print(f"Timetables: official open data, built {data['built']} (valid {data['start']} + {data['days']} days)")
    net = Net(data, day)
    label, dst = resolve(net, a.to, a.near, a.radius)
    src = net.around(HOME[1], HOME[2], HOME[3])
    if not dst:
        raise SystemExit(f"No bus or train stop found near {label}.")
    print(f"From {HOME[0]} to {label} · {day.strftime('%a %d/%m/%Y')} · max {a.max} min, max 2 vehicles")
    worst = "✅"
    for sh in a.shift:
        s_txt, e_txt = sh.split("-")
        S, E = parse_hhmm(s_txt), parse_hhmm(e_txt)
        go = pick_go(net.journeys(src, dst, S - EARLY - a.max, S - EARLY, a.max))
        if E <= S:  # night shift: return the next morning
            back_net, E2 = Net(data, day + dt.timedelta(days=1)), E
        else:
            back_net, E2 = net, E
        if back_net is not net:
            _, dst2 = resolve(back_net, a.to, a.near, a.radius)
            src2 = back_net.around(HOME[1], HOME[2], HOME[3])
        else:
            dst2, src2 = dst, src
        back = pick_back(back_net.journeys(dst2, src2, E2, E2 + a.wait + 60 + a.max, a.max))
        print(f"\nShift {s_txt}-{e_txt}")
        if go:
            print(f"  GO   ✅ leave {hhmm(go[0])}, arrive {hhmm(go[1])} ({S - go[1]} min early): {net.describe(go)}")
        else:
            first = pick_back(net.journeys(src, dst, S - EARLY - a.max, S + 240, a.max))
            extra = f" — earliest arrival {hhmm(first[1])} ({net.describe(first)})" if first else ""
            print(f"  GO   ❌ no connection arriving before {hhmm(S - EARLY)} within {a.max} min and 2 vehicles{extra}")
        if back:
            wait = back[0] - E2
            mark = "✅" if wait <= a.wait else "⚠️"
            print(f"  BACK {mark} leave work {hhmm(back[0])} (wait {wait} min), home {hhmm(back[1])}: {back_net.describe(back)}")
        else:
            mark = "❌"
            last = pick_go(back_net.journeys(dst2, src2, E2 - 240, E2 + a.max, a.max))
            extra = f" — last one leaves work {hhmm(last[0])} ({back_net.describe(last)})" if last else ""
            print(f"  BACK ❌ no connection back to Mataró after {hhmm(E2)} within {a.wait + 60} min wait{extra}")
        verdict = "❌" if (not go or not back) else ("⚠️" if mark == "⚠️" else "✅")
        print(f"  VERDICT {verdict}")
        def short(j, n):
            return " + ".join(f"{n.route(l[0]).split(' ')[0]} {hhmm(l[2])}" for l in j[2])
        go_txt = f"{short(go, net)} → arrive {hhmm(go[1])} ({go[1] - go[0]} min)" if go else "no bus in time"
        back_txt = f"back {short(back, back_net)} (wait {back[0] - E2} min)" if back else "no bus back"
        print(f"  SUMMARY {verdict} {s_txt}-{e_txt}: {go_txt} · {back_txt}")
        order = {"✅": 0, "⚠️": 1, "❌": 2}
        if order[verdict] > order[worst]:
            worst = verdict
    print(f"\nOVERALL {worst}")


if __name__ == "__main__":
    main()
