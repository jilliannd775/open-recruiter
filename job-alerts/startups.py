"""The startup board list: a big, automatically built list of startups' job
boards, so the daily alert searches far beyond companies.yaml.

  * Building (a separate daily workflow, run before the alert): takes every
    Y Combinator company marked as hiring in the US, finds its Greenhouse,
    Lever, Ashby, Workable or SmartRecruiters board, and remembers the result
    in startup_boards.json. It works through new companies a few hundred at a
    time, re-checks found boards every couple of months, and retries companies
    with no board every few months.
  * Sweeping (part of the daily alert): reads every board on the list. Those
    jobs then go through the same strict filters as the big job boards (your
    target titles or keywords, not too senior, remote, US) before any AI.

Usage:
  python startups.py --build [--limit N]   # add up to N more companies to the list
  python startups.py --stats               # how big the list is
"""
from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from common import (CAREERS_URLS, HERE, PLATFORM_LABELS, fetch_board, find_board, get_with_retries,
                    http_json, load_json_state, load_settings, log, norm_name, save_json_state,
                    today_pacific)

INDEX_FILE = HERE / "startup_boards.json"
EMPTY_INDEX = {"companies": {}, "last_build": None}
YC_HIRING_URL = "https://yc-oss.github.io/api/companies/hiring.json"
YC_US_REGIONS = {"United States of America", "America / Canada"}
WORKERS = 8


def load_index() -> dict:
    return load_json_state(INDEX_FILE, EMPTY_INDEX)


def yc_hiring_us(min_team_size: int) -> list[dict]:
    data = get_with_retries(lambda: http_json(YC_HIRING_URL, timeout=90), "Y Combinator directory")
    if not isinstance(data, list):
        raise ValueError("unexpected Y Combinator directory shape")
    out = []
    for c in data:
        if c.get("status") != "Active" or not c.get("isHiring"):
            continue
        if not YC_US_REGIONS & set(c.get("regions") or []):
            continue
        if int(c.get("team_size") or 0) < min_team_size:
            continue
        if not norm_name(c.get("name") or ""):
            continue
        out.append(c)
    # Bigger teams first: more likely to hire non-engineering roles.
    out.sort(key=lambda c: -int(c.get("team_size") or 0))
    return out


def _older_than(date: str | None, days: int, today: str) -> bool:
    if not date:
        return True
    return date < (datetime.fromisoformat(today) - timedelta(days=days)).date().isoformat()


def build(limit: int | None = None) -> int:
    settings = load_settings()
    cfg = settings["startup_boards"]
    index = load_index()
    today = today_pacific()
    limit = int(limit or cfg["new_companies_per_run"])

    companies = yc_hiring_us(int(cfg["min_team_size"]))
    log(f"{len(companies)} hiring US companies in the Y Combinator directory "
        f"(team of {cfg['min_team_size']}+).")

    todo = []
    for c in companies:
        key = c.get("slug") or norm_name(c["name"])
        prev = index["companies"].get(key)
        if prev is None:
            todo.append(c)
        elif prev.get("status") == "none" and _older_than(prev.get("checked"),
                                                          int(cfg["recheck_missing_after_days"]), today):
            todo.append(c)
    todo = todo[:limit]

    recheck = [(k, v) for k, v in index["companies"].items()
               if v.get("status") == "found"
               and _older_than(v.get("checked"), int(cfg["recheck_found_after_days"]), today)][:limit]

    log(f"Looking up {len(todo)} companies' job boards, and re-checking {len(recheck)} known boards...")

    def lookup(c):
        try:
            return c, find_board(c["name"], c.get("website") or "", extra_slugs=(c.get("slug") or "",),
                                 quick=True, pause=0.1)
        except Exception:  # noqa: BLE001
            return c, None

    found = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for c, result in pool.map(lookup, todo):
            key = c.get("slug") or norm_name(c["name"])
            entry = {"name": c["name"], "website": c.get("website") or "", "checked": today,
                     "team_size": c.get("team_size"), "source": "yc"}
            if result:
                platform, slug, jobs = result
                entry.update(status="found", platform=platform, slug=slug)
                found += 1
                log(f"  found  {c['name']:<32} {platform}/{slug} ({len(jobs)} jobs)")
            else:
                entry["status"] = "none"
            index["companies"][key] = entry

        def still_there(item):
            key, v = item
            try:
                return key, bool(fetch_board({"name": v["name"], "platform": v["platform"], "slug": v["slug"]}))
            except Exception:  # noqa: BLE001
                return key, False
        for key, ok in pool.map(still_there, recheck):
            index["companies"][key]["checked"] = today
            if not ok:
                index["companies"][key]["status"] = "none"
                log(f"  gone   {index['companies'][key]['name']} (board empty or removed)")

    index["last_build"] = today
    save_json_state(INDEX_FILE, index)
    stats(index)
    log(f"This run: {found} new boards found out of {len(todo)} companies looked up.")
    return 0


def active_boards(index: dict) -> list[dict]:
    return [{"name": v["name"], "platform": v["platform"], "slug": v["slug"]}
            for v in index["companies"].values() if v.get("status") == "found"]


def sweep(skip: set[tuple[str, str]] | None = None):
    """Read every board on the list. Returns (jobs, boards read, boards failed)."""
    boards = [b for b in active_boards(load_index()) if (b["platform"], b["slug"].lower()) not in (skip or set())]

    def read(b):
        try:
            return b, fetch_board(b), None
        except Exception as e:  # noqa: BLE001
            return b, [], e

    jobs, failed = [], 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for b, got, err in pool.map(read, boards):
            if err:
                failed += 1
                continue
            for j in got:
                # Same strict filters as the big job boards (target titles/keywords).
                j.kind = "aggregator"
                j.source = f"{b['name']} careers ({PLATFORM_LABELS[b['platform']]})"
                j.source_url = CAREERS_URLS[b["platform"]].format(slug=b["slug"])
            jobs.extend(got)
    return jobs, len(boards), failed


def stats(index: dict | None = None) -> None:
    index = index or load_index()
    vals = list(index["companies"].values())
    found = [v for v in vals if v.get("status") == "found"]
    by_platform: dict[str, int] = {}
    for v in found:
        by_platform[v["platform"]] = by_platform.get(v["platform"], 0) + 1
    log(f"Startup board list: {len(found)} boards found, {len(vals) - len(found)} companies with no "
        f"board we can read, out of {len(vals)} looked up. By platform: "
        + (", ".join(f"{PLATFORM_LABELS[p]} {n}" for p, n in sorted(by_platform.items())) or "none yet"))


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--build", action="store_true", help="look up more companies' job boards")
    p.add_argument("--limit", type=int, default=None, help="how many new companies to look up this run")
    p.add_argument("--stats", action="store_true", help="show how big the list is")
    args = p.parse_args()
    if args.build:
        return build(args.limit)
    stats()
    return 0


if __name__ == "__main__":
    sys.exit(main())
