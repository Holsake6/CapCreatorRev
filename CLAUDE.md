# Notes for coding agents

- Product: local Mac tool that learns a CapCut template style per category and finds matching creators. UI and docs are Simplified Chinese; keep user-facing strings in Chinese.
- Entry: `capcut_local.py` → `capcreator/cli.py`. Web: `capcreator/server.py` (stdlib only) + static pages in `capcreator/web/`.
- Core stays stdlib-only; video analysis (`dna.py`, `taste.py`) needs `requirements.txt`. Pin OpenCV < 5 (5.x removed Haar/HOG detectors).
- `capcut_local_data/categories/<slug>/*.json` is the user's real review state and is tracked in Git. Never rewrite it in tests: tests use `CAPCREATOR_DATA` (see `tests/conftest.py`).
- CapCut hosts are usually blocked in cloud sandboxes; run `python3 capcut_local.py doctor` to confirm. Do not fake network results; tests mock `capcut.template_page` / `landing_template_ids`.
- Run tests: `python3 -m pytest -q tests` (~45 s, uses synthetic videos from `tests/synth.py`).
- v2 compatibility that must hold: review validation rules, 7-day/1000-uses rule, 60/40 ranked/random batches, seen creators never repeat, launchd job calls `capcut_local.py --refresh --scan-only`.
