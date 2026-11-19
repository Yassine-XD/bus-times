#!/usr/bin/env python3
"""
Build a small timetable file for the Mataró / Maresme / Vallès / Barcelonès area
from the official open-data GTFS feeds (ATM Barcelona, Generalitat interurban
buses, Renfe Rodalies). Runs in GitHub Actions twice a week.

Output: data/area.json.gz  (+ data/meta.json)

Local test:  python3 build.py --local gencat=/path/to/gtfs_dir --start 2026-03-09
"""
import argparse, csv, datetime as dt, gzip, io, json, os, re, sys, urllib.request, zipfile
from zoneinfo import ZoneInfo

# Area kept: Badalona/Sant Adrià (south) to Tordera (north), Sabadell (west) to Malgrat (east)
BBOX = (41.40, 41.75, 2.05, 2.80)  # lat_min, lat_max, lon_min, lon_max
DAYS = 28

FEEDS = [
    ("atm", [
        "https://storage.googleapis.com/storage/v1/b/mdb-latest/o/es-atm-autobuses-trains-complete-gtfs-2826.zip?alt=media",
    ]),
    ("gencat", [
        "https://territori.gencat.cat/web/.content/home/serveis/visors-cartografia/bases-cartografiques/infraestructures-mobilitat/autobusos-interurbans/busos-interurbans-GTFS.zip",
        "https://storage.googleapis.com/storage/v1/b/mdb-latest/o/es-catalonia-autobusos-interurbans-gtfs-2926.zip?alt=media",
    ]),
    ("renfe", [
        "https://ssl.renfe.com/ftransit/Fichero_CER_FOMENTO/fomento_transit.zip",
        "https://storage.googleapis.com/storage/v1/b/mdb-latest/o/es-unknown-renfe-cercanias-gtfs-2653.zip?alt=media",
    ]),
]

UA = {"User-Agent": "Mozilla/5.0 (bus-times builder; open data)"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


class Source:
    """Read GTFS files from a zip or a directory."""

    def __init__(self, path):
        self.path = path
        self.zip = zipfile.ZipFile(path) if path.endswith(".zip") else None
        if self.zip:
            self.names = {os.path.basename(n): n for n in self.zip.namelist()}

    def has(self, name):
        if self.zip:
            return name in self.names
        return os.path.exists(os.path.join(self.path, name))

    def rows(self, name):
        if self.zip:
            fh = io.TextIOWrapper(self.zip.open(self.names[name]), encoding="utf-8-sig", newline="")
        else:
            fh = open(os.path.join(self.path, name), encoding="utf-8-sig", newline="")
        with fh:
            reader = csv.reader(fh)
            header = [h.strip() for h in next(reader)]
            idx = {h: i for i, h in enumerate(header)}
            for r in reader:
                if r:
                    yield idx, r


def g(idx, r, key, default=""):
    i = idx.get(key)
    return r[i].strip() if i is not None and i < len(r) else default


def download(urls, dest):
    for u in urls:
        try:
            log("GET", u)
            req = urllib.request.Request(u, headers=UA)
            with urllib.request.urlopen(req, timeout=600) as resp, open(dest, "wb") as out:
                while True:
                    chunk = resp.read(1 << 20)
                    if not chunk:
                        break
                    out.write(chunk)
            with zipfile.ZipFile(dest) as z:
                if not any(n.endswith("stop_times.txt") for n in z.namelist()):
                    raise ValueError("no stop_times.txt")
            log("  ok", os.path.getsize(dest) // 1024, "KB")
            return u
        except Exception as e:  # try the next mirror
            log("  failed:", e)
    return None


def tmin(s):
    s = s.strip()
    if not s:
        return None
    h, m, *_ = s.split(":")
    return int(h) * 60 + int(m)


def route_label(short, long_):
    short, long_ = short.strip(), long_.strip()
    m = re.match(r"^\(([^)]+)\)\s*(.*)$", long_)  # gencat style "(e13) Mataró - Granollers"
    if m:
        short, long_ = m.group(1), m.group(2)
    short = re.sub(r"^L0*(?=\d)", "L", short) if re.match(r"^L0\d", short) else short
    return (short + " " + long_).strip()[:80]


def process(feed, src, start, days, out):
    lat0, lat1, lon0, lon1 = BBOX
    # stops
    keep = {}
    for idx, r in src.rows("stops.txt"):
        if g(idx, r, "location_type", "0") not in ("", "0"):
            continue
        try:
            lat, lon = float(g(idx, r, "stop_lat")), float(g(idx, r, "stop_lon"))
        except ValueError:
            continue
        if lat0 <= lat <= lat1 and lon0 <= lon <= lon1:
            keep[g(idx, r, "stop_id")] = (g(idx, r, "stop_name"), round(lat, 5), round(lon, 5))
    log(feed, "stops in area:", len(keep))
    if not keep:
        return 0
    # agencies + routes
    agencies = {}
    if src.has("agency.txt"):
        for idx, r in src.rows("agency.txt"):
            agencies[g(idx, r, "agency_id")] = g(idx, r, "agency_name")
    routes = {}
    for idx, r in src.rows("routes.txt"):
        routes[g(idx, r, "route_id")] = (
            route_label(g(idx, r, "route_short_name"), g(idx, r, "route_long_name")),
            agencies.get(g(idx, r, "agency_id"), next(iter(agencies.values()), "")),
        )
    # services -> active day indexes in the window
    dates = [start + dt.timedelta(days=i) for i in range(days)]
    active = {}
    if src.has("calendar.txt"):
        wd = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        for idx, r in src.rows("calendar.txt"):
            sid = g(idx, r, "service_id")
            try:
                a = dt.datetime.strptime(g(idx, r, "start_date"), "%Y%m%d").date()
                b = dt.datetime.strptime(g(idx, r, "end_date"), "%Y%m%d").date()
            except ValueError:
                continue
            s = active.setdefault(sid, set())
            for i, d in enumerate(dates):
                if a <= d <= b and g(idx, r, wd[d.weekday()]) == "1":
                    s.add(i)
    if src.has("calendar_dates.txt"):
        pos = {d.strftime("%Y%m%d"): i for i, d in enumerate(dates)}
        for idx, r in src.rows("calendar_dates.txt"):
            i = pos.get(g(idx, r, "date"))
            if i is None:
                continue
            s = active.setdefault(g(idx, r, "service_id"), set())
            if g(idx, r, "exception_type") == "1":
                s.add(i)
            else:
                s.discard(i)
    # trips active in the window
    trips = {}
    for idx, r in src.rows("trips.txt"):
        sid = g(idx, r, "service_id")
        if active.get(sid):
            trips[g(idx, r, "trip_id")] = (g(idx, r, "route_id"), sid)
    log(feed, "trips active in window:", len(trips))
    # stop_times (streamed; keep only area stops)
    st = {}
    for idx, r in src.rows("stop_times.txt"):
        tid = g(idx, r, "trip_id")
        if tid not in trips:
            continue
        sid = g(idx, r, "stop_id")
        if sid not in keep:
            continue
        t = tmin(g(idx, r, "departure_time")) if g(idx, r, "departure_time") else tmin(g(idx, r, "arrival_time"))
        if t is None:
            continue
        try:
            seq = int(float(g(idx, r, "stop_sequence")))
        except ValueError:
            seq = 0
        st.setdefault(tid, []).append((seq, sid, t))
    n = 0
    for tid, rows in st.items():
        if len(rows) < 2:
            continue
        rows.sort()
        rid, sid = trips[tid]
        label, agency = routes.get(rid, ("?", ""))
        sidx = []
        times = []
        for _, stop, t in rows:
            key = feed + ":" + stop
            if key not in out["stop_index"]:
                out["stop_index"][key] = len(out["stops"])
                out["stops"].append(list(keep[stop]))
            sidx.append(out["stop_index"][key])
            times.append(t)
        rkey = (label, agency)
        if rkey not in out["route_index"]:
            out["route_index"][rkey] = len(out["routes"])
            out["routes"].append([label, agency])
        skey = tuple(sorted(active[sid]))
        if skey not in out["service_index"]:
            out["service_index"][skey] = len(out["services"])
            out["services"].append(list(skey))
        sig = (out["route_index"][rkey], out["service_index"][skey], tuple(times), tuple(out["stops"][i][0] for i in sidx))
        if sig in out["seen"]:  # same trip published by two feeds
            continue
        out["seen"].add(sig)
        out["trips"].append([out["route_index"][rkey], out["service_index"][skey], sidx, times])
        n += 1
    log(feed, "trips kept:", n)
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local", action="append", default=[], help="name=path (zip or dir), skips download")
    ap.add_argument("--start", help="YYYY-MM-DD (default: today, Europe/Madrid)")
    ap.add_argument("--days", type=int, default=DAYS)
    ap.add_argument("--out", default="data")
    a = ap.parse_args()
    start = dt.date.fromisoformat(a.start) if a.start else dt.datetime.now(ZoneInfo("Europe/Madrid")).date()
    out = {"stops": [], "stop_index": {}, "routes": [], "route_index": {}, "services": [], "service_index": {}, "trips": [], "seen": set()}
    sources = {}
    feeds = []
    if a.local:
        feeds = [(x.split("=", 1)[0], x.split("=", 1)[1]) for x in a.local]
    else:
        os.makedirs("/tmp/gtfs", exist_ok=True)
        for name, urls in FEEDS:
            dest = f"/tmp/gtfs/{name}.zip"
            used = download(urls, dest)
            sources[name] = used or "FAILED"
            if used:
                feeds.append((name, dest))
    for name, path in feeds:
        try:
            sources.setdefault(name, path)
            process(name, Source(path), start, a.days, out)
        except Exception as e:
            log(name, "processing failed:", e)
            sources[name] = f"FAILED: {e}"
    if not out["trips"]:
        log("No trips built — keeping the previous data.")
        sys.exit(1)
    os.makedirs(a.out, exist_ok=True)
    data = {
        "built": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
        "start": start.isoformat(),
        "days": a.days,
        "sources": sources,
        "stops": out["stops"],
        "routes": out["routes"],
        "services": out["services"],
        "trips": out["trips"],
    }
    with gzip.open(os.path.join(a.out, "area.json.gz"), "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    meta = {k: data[k] for k in ("built", "start", "days", "sources")}
    meta.update(stops=len(out["stops"]), trips=len(out["trips"]), routes=len(out["routes"]))
    with open(os.path.join(a.out, "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    log("done:", meta)


if __name__ == "__main__":
    main()
