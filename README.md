# bus-times

Checks whether a job can be reached by public transport from **Mataró station** for the real shift times: at most 2 vehicles (one change) and at most 90 minutes door to door, both for the shift start and for the trip home after it ends.

The timetables come from official open data (GTFS):
- Generalitat de Catalunya, interurban buses
- Renfe, Rodalies

A GitHub Action (`.github/workflows/update.yml`) downloads them every Monday and Thursday. It keeps only the Maresme, Vallès and Badalona area for the next 28 days, and saves the result to `data/area.json.gz`.

## Use

```bash
curl -sL https://raw.githubusercontent.com/Yassine-XD/bus-times/main/query.py -o query.py
python3 query.py --to "Les Franqueses del Vallès" --day weekday --shift 06:00-14:00 --shift 14:00-22:00
python3 query.py --to "Granollers" --near "Can Gili" --day saturday --shift 08:00-17:00
python3 query.py --to "41.6012,2.2950" --date 2026-11-24 --shift 22:00-06:00
```

`--to` takes a town, `stop:<stop name>` or `lat,lon`. `--near` narrows a town down to a stop name, for example a polígono.

Each shift prints a GO line, a BACK line, a VERDICT (✅ / ⚠️ / ❌) and a one-line SUMMARY.

Not covered: Barcelona city (outside the area), Mataró's own city buses, and services that are not in the open data. Always confirm in a journey planner before an interview.

## Job-offer feed (`jobs/`)
`jobs/collect.py` runs every day on GitHub Actions (~05:23 Madrid) and reads, in full and respecting robots.txt:
Xaloc (per-town pages + every offer page), Feina Activa (official open-data XML), Eurofirms (offers sitemap),
Randstad (per-town pages), IMAN (per-town filter), RAS (sitemap), Meditempus (sitemap).
It keeps only towns reachable from Mataró and writes `jobs/data/offers.json`.

```
curl -sL https://raw.githubusercontent.com/Yassine-XD/bus-times/main/jobs/list.py -o /tmp/jobs.py
python3 /tmp/jobs.py --days 3          # A: no blocker word · B: only "valorable" · C: blocker word + the sentence
python3 /tmp/jobs.py --id xaloc:397227 # full text of one offer
```
Not covered (JavaScript-only or robots.txt forbids): Adecco, Manpower, Crit — use web searches for those.
