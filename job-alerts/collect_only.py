"""One-off: collect and keyword-filter new jobs WITHOUT the AI, and save them to
collected.json so they can be scored by hand while the Gemini key is out of
credit. Reads seen_jobs.json but never writes it, and sends no email."""
from __future__ import annotations

import json
import re

import job_alerts as ja
from common import fill_page_details, load_json_state, prefilter, priority

settings = ja.load_settings()
ja.TRACKER_SETTINGS.update(settings)
settings.setdefault("sources", {})
settings["email_alerts_days"] = 9          # cover the days since the last good run
seen = load_json_state(ja.SEEN_FILE, ja.EMPTY_SEEN)
notes: list[str] = []
jobs, ok, tried = ja.collect_fixed_sources(settings, notes, seen)

unique, keys = {}, set()
for j in jobs:
    k = j.dedupe_key()
    if j.uid in unique or k in keys:
        continue
    unique[j.uid] = j
    keys.add(k)
new = [j for j in unique.values() if j.uid not in seen["jobs"] and j.dedupe_key() not in seen["jobs"]]
fill_page_details(new, settings)
kept = [j for j in new if not prefilter(j, settings)]
kept.sort(key=priority)
out = [{"id": j.uid, "t": j.title, "c": j.company, "u": j.url, "l": j.location, "w": j.workplace,
        "src": j.source, "d": re.sub(r"\s+", " ", j.description or "")[:2500]} for j in kept]
with open("collected.json", "w", encoding="utf-8") as fh:
    json.dump({"sources_ok": ok, "sources_tried": tried, "notes": notes, "jobs": out}, fh, indent=1, ensure_ascii=False)
print(f"{len(unique)} open, {len(new)} new, {len(kept)} kept after keyword filter; {ok}/{tried} sources worked")
