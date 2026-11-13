#!/usr/bin/env python3
"""Create fake cadets to preview the board without GitHub.

    export NEBULA_KEY=<64 hex>
    python3 tests/make_fixtures.py > tests/fixtures.json
    python3 scripts/build.py --offline tests/fixtures.json --out _site --state /tmp/state.json
    python3 -m http.server -d _site 8000     # open http://localhost:8000
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts"))
from nebula_flags import derive_flag  # noqa: E402

key = bytes.fromhex(os.environ["NEBULA_KEY"].strip())
here = os.path.dirname(os.path.abspath(__file__))
cat = json.load(open(os.path.join(here, "..", "catalog.json")))
chs = [c for lab in cat["labs"] for c in lab["challenges"]]
random.seed(7)
names = ["Orion-7", "StarDust", "Kestrel", "Nova_R", "Pulsar", "Quasar99", "Lyra", "Comet-K",
         "Vesper", "Halcyon", "Draco", "Andromeda", "Zenith", "Polaris", "Sirius-B", "Rigel"]
out = []
for i, alias in enumerate(names):
    login = f"cadet{i:02d}"
    k = random.randint(0, len(chs))
    log = [json.dumps({"type": "solve", "challenge": c["id"],
                       "flag": derive_flag(key, login, c["id"], c["slug"])}) for c in chs[:k]]
    out.append({"login": login, "repo": f"{login}/nebula", "profile": {"alias": alias}, "log": "\n".join(log)})
# someone who copied flags from cadet00: must get 0 points
out.append({"login": "copycat", "repo": "copycat/nebula", "profile": {"alias": "Copycat"}, "log": out[0]["log"]})
json.dump(out, sys.stdout, indent=1)
