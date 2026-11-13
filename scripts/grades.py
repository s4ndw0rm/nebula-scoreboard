#!/usr/bin/env python3
"""Private grade report for the instructor. Run it on YOUR machine or in a
private Codespace, never in the public scoreboard workflow.

    export NEBULA_KEY=<64 hex>   BOT_TOKEN=<bot classic PAT>
    python3 scripts/grades.py > grades.csv

Columns: GitHub login, alias, repo, points per lab, total, % of total, hints,
invalid flags (possible tampering) and number of files in writeups/.
"""
import csv
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from build import GitHub, evaluate, fetch_cadets_offline, fetch_cadets_online, load_catalog  # noqa: E402


def main():
    key = bytes.fromhex(os.environ["NEBULA_KEY"].strip())
    catalog, index = load_catalog()
    if len(sys.argv) > 2 and sys.argv[1] == "--offline":
        cadets = list(fetch_cadets_offline(sys.argv[2]))
    else:
        cadets = list(fetch_cadets_online(GitHub(os.environ["BOT_TOKEN"].strip()), with_writeups=True))
    evaluated = evaluate(key, cadets, index)
    lab_ids = [lab["id"] for lab in catalog["labs"]]
    max_pts = sum(c["points"] for c in index.values())

    w = csv.writer(sys.stdout)
    w.writerow(["login", "alias", "repo"] + lab_ids + ["total", "pct", "hints", "invalid_flags", "writeups"])
    for p in sorted(evaluated.values(), key=lambda p: p["login"].lower()):
        per_lab = {lid: 0 for lid in lab_ids}
        for cid in p["solves"]:
            per_lab[index[cid]["lab"]] += index[cid]["points"]
        total = sum(per_lab.values())
        w.writerow([p["login"], p["alias"], " ".join(p["repos"])] + [per_lab[l] for l in lab_ids] +
                   [total, f"{100 * total / max_pts:.1f}" if max_pts else "0",
                    sum(p["hints"].values()), p["invalid"], p["writeups"]])


if __name__ == "__main__":
    main()
