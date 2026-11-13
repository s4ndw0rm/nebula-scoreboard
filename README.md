# Nebula scoreboard

Public leaderboard of the Nebula Cadet Program, rebuilt every 5 minutes by
GitHub Actions and published with GitHub Pages.

- `catalog.json`: official list of challenges and points (students cannot change it)
- `scripts/build.py`: accepts invitations, reads cadet repos, **verifies every flag** and builds the site
- `scripts/grades.py`: private CSV report for the instructor (run locally, never in the workflow)
- `site/index.html`: the board (reads `data.json`)
- `data/state.json`: first time HQ saw each capture (public; no GitHub logins)

Secrets required: `NEBULA_KEY`, `BOT_TOKEN`. Pages source: **GitHub Actions**.
