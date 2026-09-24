"""Weekly company discovery, built to run on GitHub Actions every Monday.

  1. Reads the last week of startup-funding news from the RSS feeds listed in
     settings.yaml (discovery -> feeds), and the Y Combinator company directory
     (companies marked as hiring, filtered to your sectors).
  2. Asks Gemini which of those companies fit the sectors in profile.md and are
     likely to hire program/operations/strategy people.
  3. For each good fit, tries likely board names on Greenhouse, Lever, Ashby,
     Workable and SmartRecruiters.
     If one exists and has open jobs, the company is added to companies.yaml
     (tagged "discovered", with the date and a one-line reason).
  4. Emails a short summary: who was added and why, plus strong fits with no
     job board it could find (with their website) to look at yourself.

It never adds a company twice, and never re-adds one you deleted: every company
it has looked at is remembered in discovery_state.json.

Usage:
  python discover.py            # normal weekly run
  python discover.py --dry-run  # show what it would add; change nothing, send nothing
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import yaml

from common import (CAREERS_URLS, COMPANIES_FILE, DISCOVERY_STATE_FILE, Gemini, QuotaExhausted,
                    _request, as_list, email_shell, find_board, get_with_retries, http_json, load_json_state, load_profile,
                    load_settings, log, missing_secrets, norm_name, prune_dated, save_json_state,
                    send_email, strip_html, today_pacific)

EMPTY_STATE = {"companies": {}, "articles": {}, "yc_seen": {}, "last_run": None}
YC_HIRING_URL = "https://yc-oss.github.io/api/companies/hiring.json"
YC_US_REGIONS = {"United States of America", "America / Canada"}
DEFAULT_YC_KEYWORDS = [
    "quantum", "physics", "space", "satellite", "aerospace", "earth observation", "geospatial",
    "fusion", "nuclear", "energy", "climate", "battery", "grid", "carbon", "defense",
    "national security", "hard tech", "deep tech", "robotics", "drones", "semiconductor",
    "photonics", "sensors",
]
FUNDING_WORDS = re.compile(
    r"\brais(e|es|ed|ing)\b|\bfunding\b|\bseries [a-f]\b|\bseed\b|\bround\b|\bbacked\b|"
    r"\bsecures?\b|\blands?\b|\bcloses?\b|\bvaluation\b|\$\s?\d|€\s?\d|£\s?\d|\bmillion\b", re.I)
ATOM = "{http://www.w3.org/2005/Atom}"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"


# --------------------------------------------------------------------------- #
# Reading feeds
# --------------------------------------------------------------------------- #

def _parse_date(text: str | None) -> datetime | None:
    if not text:
        return None
    text = text.strip()
    try:
        d = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            d = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def read_feed(feed: dict) -> list[dict]:
    """Returns [{title, link, date, text}] for one RSS or Atom feed."""
    raw = _request(feed["url"], timeout=60,
                   accept="application/rss+xml, application/atom+xml, application/xml, text/xml, */*")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        # Some feeds use HTML entities like &nbsp; that strict XML rejects.
        fixed = re.sub(rb"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", b"&amp;", raw)
        root = ET.fromstring(fixed)
    items = []
    for it in root.iter("item"):
        items.append({
            "title": (it.findtext("title") or "").strip(),
            "link": (it.findtext("link") or "").strip(),
            "date": _parse_date(it.findtext("pubDate") or it.findtext("{http://purl.org/dc/elements/1.1/}date")),
            "text": strip_html(it.findtext(CONTENT) or it.findtext("description") or ""),
        })
    for it in root.iter(f"{ATOM}entry"):
        link_el = it.find(f"{ATOM}link")
        items.append({
            "title": (it.findtext(f"{ATOM}title") or "").strip(),
            "link": (link_el.get("href") if link_el is not None else "") or "",
            "date": _parse_date(it.findtext(f"{ATOM}published") or it.findtext(f"{ATOM}updated")),
            "text": strip_html(it.findtext(f"{ATOM}content") or it.findtext(f"{ATOM}summary") or ""),
        })
    for i in items:
        i["feed"] = feed.get("name") or feed["url"]
    return items


def enabled_feeds(settings: dict) -> list[dict]:
    return [f for f in (settings["discovery"].get("feeds") or [])
            if isinstance(f, dict) and f.get("url") and f.get("enabled", True)]


def recent_funding_items(settings: dict, notes: list[str], state: dict | None = None) -> list[dict]:
    lookback = datetime.now(timezone.utc) - timedelta(days=int(settings["discovery"]["lookback_days"]))
    seen_links = (state or {}).get("articles", {})
    out: dict[str, dict] = {}
    for feed in enabled_feeds(settings):
        try:
            items = read_feed(feed)
        except Exception as e:  # noqa: BLE001
            log(f"  {feed.get('name')}: FAILED - {e}")
            notes.append(f"Couldn't read the {feed.get('name') or feed['url']} feed: {e}")
            continue
        kept = 0
        for it in items:
            if it["date"] and it["date"] < lookback:
                continue
            if not it["link"] or it["link"] in seen_links or it["link"] in out:
                continue
            if not feed.get("every_item") and not FUNDING_WORDS.search(f"{it['title']} {it['text'][:600]}"):
                continue
            it["max_chars"] = int(feed.get("max_chars") or 1200)
            out[it["link"]] = it
            kept += 1
        log(f"  {feed.get('name')}: {len(items)} items, {kept} recent funding stories")
        time.sleep(1)
    return list(out.values())


def check_feeds(settings: dict) -> int:
    """Used by `job_alerts.py --check`. Returns how many enabled feeds failed."""
    failed = 0
    cfg = settings["discovery"]
    state = "on " if cfg.get("yc_directory", True) else "off"
    try:
        n = len(yc_candidates(cfg, load_json_state(DISCOVERY_STATE_FILE, EMPTY_STATE), set(), today_pacific()))
        log(f"  OK    {'Y Combinator directory':<28} ({state}) {n} hiring US companies match your sectors "
            f"(max {cfg['yc_max_companies_per_week']} a week)")
    except Exception as e:  # noqa: BLE001
        failed += 1 if cfg.get("yc_directory", True) else 0
        log(f"  FAIL  {'Y Combinator directory':<28} ({state}) {e}")
    for feed in settings["discovery"].get("feeds") or []:
        if not isinstance(feed, dict) or not feed.get("url"):
            continue
        state = "on " if feed.get("enabled", True) else "off"
        try:
            items = read_feed(feed)
            week = datetime.now(timezone.utc) - timedelta(days=8)
            recent = [i for i in items if not i["date"] or i["date"] >= week]
            funding = [i for i in recent if feed.get("every_item")
                       or FUNDING_WORDS.search(f"{i['title']} {i['text'][:600]}")]
            log(f"  OK    {feed.get('name', feed['url']):<28} ({state}) {len(items)} items, "
                f"{len(recent)} from the last week, {len(funding)} look like funding news")
        except Exception as e:  # noqa: BLE001
            if feed.get("enabled", True):
                failed += 1
            log(f"  FAIL  {feed.get('name', feed['url']):<28} ({state}) {e}")
    return failed


# --------------------------------------------------------------------------- #
# Picking companies with Gemini
# --------------------------------------------------------------------------- #

PICK_SYSTEM = """You help a job seeker find companies worth watching. You read \
startup-funding news and pick out companies that just raised money. The job \
seeker's profile is below.

For every company in the articles that itself RAISED funding (ignore investors, \
VC funds raising their own funds, acquirers, and public-company earnings), return:
{"article_id": "<id>", "company": "<company name>", "website": "<company domain, \
e.g. acme.com, only if stated in the article or you are confident; else empty>", \
"sector": "<2-5 words>", "round": "<e.g. Seed, Series A; or empty>", "amount": \
"<e.g. $12M; or empty>", "hq": "<city/country if known>", "fit_score": <0-100>, \
"hires_non_engineering": <true/false>, "reason": "<one sentence on why it fits the \
profile or not>"}

fit_score: how well the company matches the candidate's favorite sectors AND \
could plausibly hire them (fully remote, US-based). Companies clearly based and \
hiring only outside the US score under 40. hires_non_engineering: true if a \
company of this size and stage is likely to hire program/project management, \
operations, strategy or business-analyst roles (Series A and later usually; seed \
companies mostly hire engineers, except a Chief of Staff).

Reply with JSON only: a list of those objects (an empty list if none).

CANDIDATE PROFILE:
"""


def recently_considered(state: dict, key: str, today: str) -> bool:
    """Added companies are never re-added (even if you delete them). Ones with no
    job board are looked at again after 90 days, in case they've set one up."""
    prev = state["companies"].get(key)
    if not prev:
        return False
    if prev.get("status") != "no_board":
        return True
    cutoff = (datetime.fromisoformat(today) - timedelta(days=90)).date().isoformat()
    return (prev.get("date") or "") >= cutoff


def pick_companies(gemini: Gemini, profile: str, articles: list[dict], per_call: int,
                   notes: list[str]) -> tuple[list[dict], set[str]]:
    """Returns (companies, links of articles actually read)."""
    found: list[dict] = []
    read: set[str] = set()
    for start in range(0, len(articles), per_call):
        batch = articles[start:start + per_call]
        prompt = "Pick out the funded companies in these articles.\n\n" + "\n".join(
            f"### Article id: {i}\nSource: {a['feed']}\nHeadline: {a['title']}\n"
            f"Text: {a['text'][:a['max_chars']]}\n" for i, a in enumerate(batch, start + 1))
        try:
            data = gemini.ask_json(PICK_SYSTEM + profile.strip(), prompt)
        except QuotaExhausted as e:
            notes.append(f"{e}; {len(articles) - start} articles wait until next week.")
            break
        except Exception as e:  # noqa: BLE001
            log(f"  AI batch failed: {e}")
            notes.append(f"Reading a batch of articles with the AI failed ({e}).")
            continue
        read.update(a["link"] for a in batch)
        for c in as_list(data, "companies"):
            if not isinstance(c, dict) or not str(c.get("company") or "").strip():
                continue
            try:
                idx = int(str(c.get("article_id")).strip().lstrip("#")) - 1
                c["article"] = articles[idx]["link"] if 0 <= idx < len(articles) else ""
            except (TypeError, ValueError):
                c["article"] = ""
            try:
                c["fit_score"] = int(float(c.get("fit_score") or 0))
            except (TypeError, ValueError):
                c["fit_score"] = 0
            c["company"] = str(c["company"]).strip()
            c["found_via"] = "funding news"
            found.append(c)
        log(f"  read {len(batch)} articles -> {len(found)} funded companies so far")
    return found, read


# --------------------------------------------------------------------------- #
# Y Combinator directory
# --------------------------------------------------------------------------- #

YC_SYSTEM = """You help a job seeker decide which startups to watch. Below are \
Y Combinator companies that say they are hiring, and the job seeker's profile.

For EACH company return:
{"id": "<id>", "fit_score": <0-100>, "hires_non_engineering": <true/false>, \
"sector": "<2-5 words>", "reason": "<one sentence on why it fits the profile or not>"}

fit_score: how well the company matches the candidate's favorite sectors AND could \
plausibly hire them (fully remote, US-based). hires_non_engineering: true if a \
company of this size and stage is likely to hire program/project management, \
operations, strategy or business-analyst roles (under ~15 people mostly hire \
engineers, except a Chief of Staff).

Reply with JSON only: a list with one object per company.

CANDIDATE PROFILE:
"""


def yc_candidates(cfg: dict, state: dict, taken: set[str], today: str) -> list[dict]:
    """Hiring YC companies in the US, in your sectors, not looked at recently."""
    data = get_with_retries(lambda: http_json(YC_HIRING_URL, timeout=90), "Y Combinator directory")
    if not isinstance(data, list):
        raise ValueError("unexpected Y Combinator directory shape")
    words = [w.lower() for w in (cfg.get("yc_sector_keywords") or DEFAULT_YC_KEYWORDS)]
    pattern = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")", re.I) if words else None
    cutoff = (datetime.fromisoformat(today) - timedelta(days=180)).date().isoformat()
    out = []
    for c in data:
        if c.get("status") != "Active" or not c.get("isHiring"):
            continue
        if not YC_US_REGIONS & set(c.get("regions") or []):
            continue
        if int(c.get("team_size") or 0) < int(cfg["yc_min_team_size"]):
            continue
        key = norm_name(c.get("name") or "")
        if not key or key in taken or recently_considered(state, key, today):
            continue
        if (state["yc_seen"].get(c.get("slug") or key) or "") >= cutoff:
            continue
        text = " ".join([c.get("one_liner") or "", c.get("long_description") or "",
                         " ".join(c.get("tags") or []), " ".join(c.get("industries") or [])])
        hits = len(set(m.lower() for m in pattern.findall(text))) if pattern else 1
        if hits:
            c["_hits"] = hits
            out.append(c)
    out.sort(key=lambda c: (-c["_hits"], -int(c.get("team_size") or 0)))
    return out[: int(cfg["yc_max_companies_per_week"])]


def score_yc(gemini: Gemini, profile: str, companies: list[dict]) -> list[dict]:
    blocks = [f"### Company id: {i}\nName: {c.get('name')}\nOne-liner: {c.get('one_liner')}\n"
              f"Industries: {', '.join(c.get('industries') or [])}; tags: {', '.join(c.get('tags') or [])}\n"
              f"Team size: {c.get('team_size')}; stage: {c.get('stage')}; batch: {c.get('batch')}\n"
              f"Locations: {c.get('all_locations') or ', '.join(c.get('regions') or [])}\n"
              f"About: {(c.get('long_description') or '')[:500]}\n"
              for i, c in enumerate(companies, 1)]
    data = gemini.ask_json(YC_SYSTEM + profile.strip(), "Score these companies.\n\n" + "\n".join(blocks))
    out = []
    for r in as_list(data, "companies"):
        try:
            c = companies[int(str(r.get("id")).strip().lstrip("#")) - 1]
            fit = int(float(r.get("fit_score") or 0))
        except (TypeError, ValueError, IndexError, AttributeError):
            continue
        out.append({"company": c["name"], "website": c.get("website") or "", "sector": r.get("sector") or "",
                    "round": f"YC {c.get('batch')}" if c.get("batch") else "", "amount": "",
                    "fit_score": fit, "hires_non_engineering": r.get("hires_non_engineering", True),
                    "reason": r.get("reason") or "", "found_via": "Y Combinator directory",
                    "yc_slug": c.get("slug") or ""})
    return out


# --------------------------------------------------------------------------- #
# companies.yaml
# --------------------------------------------------------------------------- #

def existing_keys() -> set[str]:
    data = yaml.safe_load(COMPANIES_FILE.read_text(encoding="utf-8")) or {}
    keys = set()
    for c in (data.get("companies") if isinstance(data, dict) else data) or []:
        if isinstance(c, dict):
            keys.add(norm_name(str(c.get("name") or "")))
            keys.add(norm_name(str(c.get("slug") or "")))
    # Also count commented-out entries ("# - name: X" / "#   slug: x") as taken.
    for m in re.finditer(r"^\s*#\s*-?\s*(?:name|slug):\s*(.+)$", COMPANIES_FILE.read_text(encoding="utf-8"), re.M):
        keys.add(norm_name(m.group(1).strip().strip('"\'')))
    keys.discard("")
    return keys


def append_companies(added: list[dict]) -> None:
    original = COMPANIES_FILE.read_text(encoding="utf-8")
    text = original.rstrip("\n") + "\n"
    if "# --- Added automatically by weekly discovery" not in text:
        text += ("\n  # --- Added automatically by weekly discovery ---\n"
                 "  # Delete any block you don't want (it won't be re-added), or add\n"
                 "  # `enabled: false` under it to pause it.\n")
    for a in added:
        text += (f"\n  - name: {json.dumps(a['name'])}\n"
                 f"    platform: {a['platform']}\n"
                 f"    slug: {json.dumps(a['slug'])}\n"
                 f"    tag: discovered\n"
                 f"    added: \"{a['date']}\"\n"
                 f"    reason: {json.dumps(a['reason'], ensure_ascii=False)}\n")
    COMPANIES_FILE.write_text(text, encoding="utf-8")
    try:
        yaml.safe_load(text)
    except yaml.YAMLError:
        COMPANIES_FILE.write_text(original, encoding="utf-8")
        raise


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #

def build_summary(added: list[dict], no_board: list[dict], notes: list[str], stats: dict) -> str:
    esc = html.escape
    parts = []
    if added:
        parts.append("<h3 style='font-size:16px;margin:20px 0 6px;'>Added to your company list</h3>")
        for a in added:
            parts.append(
                f"<div style='padding:8px 0;border-bottom:1px solid #eee;'>"
                f"<b><a href='{esc(a['careers'])}' style='color:#0b57d0;text-decoration:none;'>{esc(a['name'])}</a></b>"
                f" <span style='color:#666;'>&middot; {esc(a['sector'])}{' &middot; ' + esc(a['round']) if a['round'] else ''}"
                f"{' ' + esc(a['amount']) if a['amount'] else ''} &middot; {a['jobs']} open jobs"
                f"{' &middot; via ' + esc(a['found_via']) if a.get('found_via') else ''}</span>"
                f"<div>{esc(a['reason'])}</div></div>")
    else:
        parts.append("<p>No new companies were added this week.</p>")
    no_board = sorted(no_board, key=lambda c: -c.get("fit_score", 0))
    extra_count = max(0, len(no_board) - 15)
    no_board = no_board[:15]
    if no_board:
        parts.append("<h3 style='font-size:16px;margin:20px 0 6px;'>Strong fits with no job board I could find</h3>"
                     "<div style='color:#666;font-size:13px;'>They may use a different careers system. Worth a look.</div>")
        for c in no_board:
            site = c.get("website") or ""
            href = site if site.startswith("http") else f"https://{site}" if site else ""
            link = (f"<a href='{esc(href)}' style='color:#0b57d0;'>{esc(site)}</a>" if href
                    else f"<a href='https://www.google.com/search?q={esc(c['company'])}+careers' style='color:#0b57d0;'>search</a>")
            parts.append(
                f"<div style='padding:8px 0;border-bottom:1px solid #eee;'><b>{esc(c['company'])}</b>"
                f" <span style='color:#666;'>&middot; {esc(c.get('sector') or '')} &middot; fit {c['fit_score']}</span>"
                f" &middot; {link}<div>{esc(c.get('reason') or '')}</div></div>")
    if extra_count:
        parts.append(f"<div style='color:#666;font-size:13px;margin-top:6px;'>...and {extra_count} more lower-scoring ones.</div>")
    if notes:
        parts.append("<p style='margin-top:24px;color:#8a1c1c;font-size:13px;'><b>Problems this run</b></p><ul style='color:#8a1c1c;font-size:13px;'>"
                     + "".join(f"<li>{esc(n)}</li>" for n in notes) + "</ul>")
    return email_shell(
        "Weekly company discovery",
        f"{stats['articles']} funding stories and {stats.get('yc', 0)} Y Combinator companies read "
        f"&middot; {stats['candidates']} good fits &middot; "
        f"{len(added)} added",
        "".join(parts),
        "Added companies are checked in your daily job alerts from now on. "
        "To remove one, delete its block from companies.yaml.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def run(dry_run: bool) -> int:
    settings = load_settings()
    cfg = settings["discovery"]
    if not cfg.get("enabled", True):
        log("Weekly discovery is turned off (settings.yaml -> discovery -> enabled).")
        return 0
    missing = missing_secrets(("GEMINI_API_KEY",) if dry_run else
                              ("GEMINI_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"))
    if missing:
        log(f"ERROR: these GitHub secrets are missing or empty: {', '.join(missing)}.")
        return 2

    state = load_json_state(DISCOVERY_STATE_FILE, EMPTY_STATE)
    notes: list[str] = []
    today = today_pacific()

    log("Reading funding news...")
    articles = recent_funding_items(settings, notes, state)
    log(f"{len(articles)} new funding stories to read.\n")

    use_yc = bool(cfg.get("yc_directory", True))
    gemini = Gemini(os.environ["GEMINI_API_KEY"].strip(), settings,
                    max_calls=int(cfg["max_ai_calls"]) + (1 if use_yc else 0))
    profile = load_profile()
    found, read_links = pick_companies(gemini, profile, articles, int(cfg["articles_per_ai_call"]), notes)
    taken = existing_keys()

    yc_scored: list[dict] = []
    if use_yc:
        log("\nReading the Y Combinator directory...")
        try:
            yc = yc_candidates(cfg, state, taken, today)
            log(f"  {len(yc)} hiring US companies in your sectors not looked at recently")
            if yc:
                yc_scored = score_yc(gemini, profile, yc)
                found.extend(yc_scored)
        except QuotaExhausted as e:
            notes.append(f"Y Combinator directory: {e}; it's tried again next week.")
        except Exception as e:  # noqa: BLE001
            log(f"  FAILED - {e}")
            notes.append(f"Couldn't read the Y Combinator directory: {e}")

    # Best fit per company, minus anything already known.
    best: dict[str, dict] = {}
    for c in found:
        key = norm_name(c["company"])
        if not key or key in taken or recently_considered(state, key, today):
            continue
        if c["fit_score"] < int(cfg["min_fit_score"]) or not c.get("hires_non_engineering", True):
            continue
        if key not in best or c["fit_score"] > best[key]["fit_score"]:
            best[key] = c
    candidates = sorted(best.values(), key=lambda c: -c["fit_score"])[: int(cfg["max_companies_to_check"])]
    log(f"\n{len(candidates)} good-fit companies not already on your list. Looking for their job boards...")

    # Look up boards 6 companies at a time (each lookup is ~40 quick requests).
    with ThreadPoolExecutor(max_workers=6) as pool:
        boards = list(pool.map(lambda c: find_board(c["company"], c.get("website") or ""), candidates))

    cap = int(cfg["max_new_companies_per_week"])
    added: list[dict] = []
    no_board: list[dict] = []
    for c, found_board in zip(candidates, boards):
        key = norm_name(c["company"])
        if found_board and len(added) >= cap:
            log(f"  over this week's limit of {cap}: {c['company']} can be added another week")
            continue
        if found_board:
            platform, slug, jobs = found_board
            if norm_name(slug) in taken:
                continue
            entry = {"name": c["company"], "platform": platform, "slug": slug, "date": today,
                     "reason": c.get("reason") or "", "sector": c.get("sector") or "",
                     "found_via": c.get("found_via") or "",
                     "round": c.get("round") or "", "amount": c.get("amount") or "",
                     "jobs": len(jobs), "careers": CAREERS_URLS[platform].format(slug=slug)}
            added.append(entry)
            taken.update({key, norm_name(slug)})
            state["companies"][key] = {"name": c["company"], "status": "added", "date": today,
                                       "platform": platform, "slug": slug}
            log(f"  ADDED  {c['company']:<30} {platform}/{slug} ({len(jobs)} jobs, fit {c['fit_score']})")
        else:
            no_board.append(c)
            state["companies"][key] = {"name": c["company"], "status": "no_board", "date": today,
                                       "website": c.get("website") or ""}
            log(f"  none   {c['company']:<30} (fit {c['fit_score']}) no job board found")

    stats = {"articles": len(read_links), "candidates": len(candidates), "yc": len(yc_scored)}
    if dry_run:
        log(f"\nDry run: would add {len(added)} companies; nothing saved or emailed.")
        (DISCOVERY_STATE_FILE.parent / "preview_discovery.html").write_text(
            build_summary(added, no_board, notes, stats), encoding="utf-8")
        return 0

    if added:
        append_companies(added)
    for link in read_links:
        state["articles"][link] = today
    for c in yc_scored:
        state["yc_seen"][c["yc_slug"] or norm_name(c["company"])] = today
    state["yc_seen"] = prune_dated(state["yc_seen"], 200)
    state["articles"] = prune_dated(state["articles"], 60)
    state["last_run"] = today
    save_json_state(DISCOVERY_STATE_FILE, state)

    subject = (f"Weekly discovery: {len(added)} compan{'ies' if len(added) != 1 else 'y'} added"
               + (f", {len(no_board)} to check by hand" if no_board else "") + f" - {today}")
    send_email(subject, build_summary(added, no_board, notes, stats))
    log(f"\nEmail sent: {subject}")
    if notes:
        log("\nProblems this run:\n  - " + "\n  - ".join(notes))
    if articles and not read_links and not yc_scored:
        log("ERROR: the AI couldn't read any articles. Check GEMINI_API_KEY.")
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dry-run", action="store_true", help="show what would be added; change nothing")
    return run(p.parse_args().dry_run)


if __name__ == "__main__":
    sys.exit(main())
