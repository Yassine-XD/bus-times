"""Show recent job offers from the daily feed (jobs/data/offers.json).

  curl -sL https://raw.githubusercontent.com/Yassine-XD/bus-times/main/jobs/list.py -o /tmp/jobs.py
  python3 /tmp/jobs.py --days 3            # offers new/updated in the last 3 days, blockers hidden
  python3 /tmp/jobs.py --days 8 --blocked  # also list the offers hidden by a hard blocker
  python3 /tmp/jobs.py --id xaloc:397227   # full text of one offer
Options: --text N (chars of offer text per offer, default 500), --src xaloc,ras, --all (ignore dates)
"""
import argparse, datetime as dt, json, sys, urllib.request

URL = "https://raw.githubusercontent.com/Yassine-XD/bus-times/main/jobs/data/offers.json"
HARD = {"forklift", "car", "lang_level", "diploma", "kitchen_meat_alcohol"}

ap = argparse.ArgumentParser()
ap.add_argument("--days", type=int, default=3)
ap.add_argument("--text", type=int, default=500)
ap.add_argument("--src", default="")
ap.add_argument("--blocked", action="store_true")
ap.add_argument("--all", action="store_true")
ap.add_argument("--id", default="")
ap.add_argument("--data", default="")
a = ap.parse_args()

data = json.load(open(a.data, encoding="utf-8")) if a.data else json.load(urllib.request.urlopen(URL, timeout=60))
built = dt.datetime.strptime(data["built"], "%Y-%m-%d %H:%M UTC")
age_h = (dt.datetime.utcnow() - built).total_seconds() / 3600
print(f"FEED built {data['built']} ({age_h:.0f}h ago){'  ⚠️ STALE — older than 30h, also check sources by hand' if age_h > 30 else ''}")
for k, s in data["sources"].items():
    print(f"  {k:12s} {'✔ ' + str(s.get('count')) + ' offers in reachable towns' if s.get('ok') else '✖ ' + s.get('error', '')}")

if a.id:
    src, oid = a.id.split(":", 1)
    for o in data["offers"]:
        if o["src"] == src and o["id"] == oid:
            print(json.dumps(o, ensure_ascii=False, indent=1)); break
    else:
        print("not found"); sys.exit(1)
    sys.exit()

since = (dt.date.today() - dt.timedelta(days=a.days)).isoformat()
def fresh(o):
    return max(o.get("published") or "", o.get("modified") or "", o.get("first_seen") or "")
srcs = set(a.src.split(",")) if a.src else None
rows = [o for o in data["offers"] if (a.all or fresh(o) >= since) and (not srcs or o["src"] in srcs)]
ok = [o for o in rows if not (set(o["flags"]) & HARD)]
bad = [o for o in rows if set(o["flags"]) & HARD]
print(f"\nWINDOW: {'all dates' if a.all else 'new or updated since ' + since} · {len(ok)} without hard blocker · {len(bad)} with a blocker word (verify on the page before excluding)\n")

def show(o, text=True):
    dates = " ".join(x for x in [f"pub {o['published']}" if o.get("published") else "",
                                  f"mod {o['modified']}" if o.get("modified") else "",
                                  f"seen {o['first_seen']}" if o.get("first_seen") else ""] if x)
    print(f"[{o['src']}:{o['id']}] {o['title']} — {o['town']}{' (' + o['town_note'] + ')' if o.get('town_note') else ''}")
    print(f"   {dates} · {o.get('company') or ''} {('· ' + o['salary']) if o.get('salary') else ''} · flags: {', '.join(o['flags']) or '-'}")
    print(f"   {o['url']}")
    if text and a.text:
        print("   " + o["text"][:a.text].replace("\n", " / "))
    print()

for o in sorted(ok, key=lambda o: (o["town"] != "Mataró", o["town"], o["src"])):
    show(o)
if a.blocked and bad:
    print("---- WITH A BLOCKER WORD (forklift / car / language level / diploma / kitchen-meat-alcohol) ----\n")
    for o in sorted(bad, key=lambda o: o["town"]):
        show(o, text=False)
elif bad:
    print(f"({len(bad)} offers hidden because of a blocker word — run with --blocked to see them)")
