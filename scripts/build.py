#!/usr/bin/env python3
"""Nebula scoreboard builder.

Runs every few minutes in GitHub Actions (see .github/workflows/scoreboard.yml):

  1. Accepts pending collaborator invitations sent to the HQ bot account.
  2. Finds every cadet repository the bot can read (it must contain .nebula/profile.json).
  3. Reads .nebula/progress/log.jsonl and verifies every flag SERVER-SIDE with the
     master key. Points that come from invalid flags are never counted.
  4. Updates data/state.json (first time each capture was seen) and writes the
     public site (index.html + data.json) to the output folder.

Environment:
  NEBULA_KEY   64-hex master key (same one compiled into nebula-agent)
  BOT_TOKEN    classic personal access token of the HQ bot account (scope: repo)

Local test without GitHub:
  NEBULA_KEY=... python3 scripts/build.py --offline tests/fixtures.json --out _site
"""
import argparse
import datetime as dt
import json
import os
import shutil
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from nebula_flags import check_flag, player_id  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://api.github.com"


# ------------------------------------------------------------------ GitHub API
class GitHub:
    def __init__(self, token: str):
        self.token = token

    def request(self, method, path, accept="application/vnd.github+json", body=None):
        url = path if path.startswith("http") else API + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers={
            "Authorization": f"Bearer {self.token}",
            "Accept": accept,
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "nebula-scoreboard",
        })
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.status, resp.read(), resp.headers
        except urllib.error.HTTPError as e:
            return e.code, e.read(), e.headers

    def paged(self, path):
        url = API + path
        while url:
            status, body, headers = self.request("GET", url)
            if status != 200:
                raise RuntimeError(f"GitHub API {status} on {url}: {body[:200]!r}")
            yield from json.loads(body)
            url = None
            for part in (headers.get("Link") or "").split(","):
                if 'rel="next"' in part:
                    url = part[part.find("<") + 1:part.find(">")]

    def raw_file(self, full_name, path):
        status, body, _ = self.request("GET", f"/repos/{full_name}/contents/{path}",
                                       accept="application/vnd.github.raw+json")
        if status == 200:
            return body.decode("utf-8", "replace")
        if status == 404:
            return None
        raise RuntimeError(f"GitHub API {status} reading {full_name}/{path}")

    def count_dir(self, full_name, path):
        status, body, _ = self.request("GET", f"/repos/{full_name}/contents/{path}")
        if status != 200:
            return 0
        items = json.loads(body)
        return sum(1 for i in items if i.get("type") == "file") if isinstance(items, list) else 0

    def accept_invitations(self):
        accepted = 0
        for inv in self.paged("/user/repository_invitations?per_page=100"):
            status, _, _ = self.request("PATCH", f"/user/repository_invitations/{inv['id']}")
            if status in (204, 200):
                accepted += 1
                print(f"  accepted invitation to {inv['repository']['full_name']}")
        return accepted


def fetch_cadets_online(gh: GitHub, with_writeups=False):
    """Yield dicts: login, repo, profile (dict), log (str)."""
    for repo in gh.paged("/user/repos?affiliation=collaborator&per_page=100"):
        full = repo["full_name"]
        prof_txt = gh.raw_file(full, ".nebula/profile.json")
        if not prof_txt:
            continue
        try:
            profile = json.loads(prof_txt)
        except ValueError:
            continue
        cadet = {
            "login": repo["owner"]["login"],
            "repo": full,
            "profile": profile,
            "log": gh.raw_file(full, ".nebula/progress/log.jsonl") or "",
        }
        if with_writeups:
            cadet["writeups"] = gh.count_dir(full, "writeups")
        yield cadet


def fetch_cadets_offline(path):
    with open(path) as fh:
        yield from json.load(fh)


# ------------------------------------------------------------------ scoring
def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_catalog():
    with open(os.path.join(ROOT, "catalog.json")) as fh:
        cat = json.load(fh)
    index = {}
    for lab in cat["labs"]:
        for ch in lab["challenges"]:
            index[ch["id"]] = dict(ch, lab=lab["id"])
    return cat, index


def parse_log(text):
    for line in (text or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            yield entry


def evaluate(key, cadets, catalog_index):
    """Return {login: {...}} with verified solves and hint counts."""
    result = {}
    for c in cadets:
        login = c["login"].lower()
        p = result.setdefault(login, {
            "login": c["login"], "repos": [], "alias": None,
            "solves": set(), "hints": {}, "invalid": 0, "writeups": 0,
        })
        p["repos"].append(c["repo"])
        alias = str(c.get("profile", {}).get("alias", "")).strip()[:20]
        if alias and not p["alias"]:
            p["alias"] = alias
        p["writeups"] = max(p["writeups"], c.get("writeups", 0))
        for e in parse_log(c.get("log")):
            cid = e.get("challenge")
            if cid not in catalog_index:
                continue
            if e.get("type") == "solve":
                ch = catalog_index[cid]
                if check_flag(key, login, cid, ch["slug"], str(e.get("flag", ""))):
                    p["solves"].add(cid)
                else:
                    p["invalid"] += 1
            elif e.get("type") == "hint":
                try:
                    lvl = int(e.get("level", 0))
                except (TypeError, ValueError):
                    lvl = 0
                p["hints"][cid] = max(p["hints"].get(cid, 0), min(lvl, 10))
    return result


def update_state(state, key, evaluated, ts):
    players = state.setdefault("players", {})
    for login, p in evaluated.items():
        pid = player_id(key, login)
        sp = players.setdefault(pid, {"alias": None, "solves": {}, "hints": {}})
        sp["alias"] = p["alias"] or sp.get("alias") or f"cadet-{pid[:4]}"
        for cid in p["solves"]:
            sp["solves"].setdefault(cid, ts)          # first time HQ saw it
        sp["hints"] = {**sp.get("hints", {}), **p["hints"]}
    return state


def public_data(state, catalog, index, ts):
    players = []
    for pid, sp in state.get("players", {}).items():
        solves = {c: t for c, t in sp.get("solves", {}).items() if c in index}
        pts = sum(index[c]["points"] for c in solves)
        players.append({
            "id": pid,
            "alias": sp.get("alias") or f"cadet-{pid[:4]}",
            "points": pts,
            "flags": len(solves),
            "hints": sum(sp.get("hints", {}).values()),
            "last_solve": max(solves.values()) if solves else None,
            "solved": sorted(solves),
        })
    # rank: points desc, then whoever reached that score first
    players.sort(key=lambda p: (-p["points"], p["last_solve"] or "9999"))
    rank = 0
    prev = None
    for i, p in enumerate(players, 1):
        key = (p["points"], p["last_solve"])
        if key != prev:
            rank = i
        prev = key
        p["rank"] = rank

    feed = []
    for pid, sp in state.get("players", {}).items():
        for cid, t in sp.get("solves", {}).items():
            if cid in index:
                feed.append({"alias": sp.get("alias"), "challenge": cid,
                             "title": index[cid]["title"], "points": index[cid]["points"], "ts": t})
    feed.sort(key=lambda f: f["ts"], reverse=True)

    labs = []
    for lab in catalog["labs"]:
        labs.append({
            "id": lab["id"], "day": lab.get("day"), "title": lab["title"],
            "challenges": [{
                "id": ch["id"], "title": ch["title"], "points": ch["points"],
                "solves": sum(1 for p in players if ch["id"] in p["solved"]),
            } for ch in lab["challenges"]],
        })

    return {
        "generated_at": ts,
        "course": catalog.get("course", "Nebula"),
        "station": catalog.get("station", "VEGA-7"),
        "max_points": sum(c["points"] for c in index.values()),
        "labs": labs,
        "players": players,
        "feed": feed[:25],
    }


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="_site", help="output folder for the public site")
    ap.add_argument("--offline", help="JSON fixtures instead of the GitHub API (testing)")
    ap.add_argument("--state", default=os.path.join(ROOT, "data", "state.json"))
    args = ap.parse_args()

    key_hex = os.environ.get("NEBULA_KEY", "").strip()
    if len(key_hex) != 64:
        sys.exit("NEBULA_KEY is missing or is not 64 hex characters.")
    key = bytes.fromhex(key_hex)

    catalog, index = load_catalog()
    ts = now_iso()

    if args.offline:
        cadets = list(fetch_cadets_offline(args.offline))
    else:
        token = os.environ.get("BOT_TOKEN", "").strip()
        if not token:
            sys.exit("BOT_TOKEN is missing.")
        gh = GitHub(token)
        print("Accepting invitations...")
        gh.accept_invitations()
        print("Reading cadet repositories...")
        cadets = list(fetch_cadets_online(gh))
    print(f"  {len(cadets)} cadet repositories found")

    evaluated = evaluate(key, cadets, index)
    try:
        with open(args.state) as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        state = {"players": {}}
    state = update_state(state, key, evaluated, ts)
    os.makedirs(os.path.dirname(args.state), exist_ok=True)
    with open(args.state, "w") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)

    data = public_data(state, catalog, index, ts)
    os.makedirs(args.out, exist_ok=True)
    site_src = os.path.join(ROOT, "site")
    for name in os.listdir(site_src):
        src = os.path.join(site_src, name)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(args.out, name))
    with open(os.path.join(args.out, "data.json"), "w") as fh:
        json.dump(data, fh, indent=1)
    flagged = sum(1 for p in evaluated.values() if p["invalid"])
    print(f"  {len(data['players'])} cadets on the board, {flagged} with invalid flags")


if __name__ == "__main__":
    main()
