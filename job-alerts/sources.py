"""Job sources beyond your company list: Hacker News "Who is hiring?",
Remotive, Remote OK and Himalayas.

Every source here is free and needs no key. Each one's terms ask for
attribution: say where the job came from and link to the listing on their
site. The digest does that for every job (see "via ..." under each one), and
jobs are only emailed to you, never republished.

  * Hacker News (Algolia API): 10,000 requests/hour limit. We use 2 a day.
  * Remotive: asks for at most 4 requests a day and a link back. We use 1.
  * Remote OK: asks for a direct link to the Remote OK listing and credit.
    We use 1 request a day and link straight to their page.
  * Himalayas: rate limited, refreshed daily. We send one search per line
    of `himalayas_searches` in settings.yaml, 2 seconds apart.
  * We Work Remotely: public RSS feeds, one request per feed a day. Every
    job links to its We Work Remotely page and is credited to them.
"""
from __future__ import annotations

import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from common import (REMOTE_WORD, Gemini, Job, as_list, get_with_retries, http_json, http_text,
                    log, strip_html)

UA_NOTE = "personal job alert emailed to one person"

SOURCE_HOMES = {
    "Hacker News": "https://news.ycombinator.com",
    "Remotive": "https://remotive.com",
    "Remote OK": "https://remoteok.com",
    "Himalayas": "https://himalayas.app",
    "We Work Remotely": "https://weworkremotely.com",
}


def _salary_extra(lo, hi) -> dict:
    """{'salary': (lo, hi)} when a board gives a sensible yearly USD range."""
    try:
        lo, hi = float(lo or 0), float(hi or 0)
    except (TypeError, ValueError):
        return {}
    lo, hi = lo or hi, hi or lo
    return {"salary": (lo, hi)} if 20000 <= lo <= hi <= 1_000_000 else {}


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")[:60]


# --------------------------------------------------------------------------- #
# Remotive
# --------------------------------------------------------------------------- #

def fetch_remotive() -> list[Job]:
    data = get_with_retries(lambda: http_json("https://remotive.com/api/remote-jobs", timeout=90), "Remotive")
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("unexpected Remotive response shape")
    jobs = []
    for j in data["jobs"]:
        jobs.append(Job(
            uid=f"remotive:{j.get('id')}",
            company=(j.get("company_name") or "").strip(),
            title=(j.get("title") or "").strip(),
            url=j.get("url") or "",                      # Remotive's own page, as their terms ask
            location=j.get("candidate_required_location") or "",
            workplace="remote",
            description=((f"Salary: {j['salary']}. " if j.get("salary") else "")
                         + strip_html(j.get("description") or "")),
            source="Remotive", source_url=SOURCE_HOMES["Remotive"], kind="aggregator",
        ))
    return jobs


# --------------------------------------------------------------------------- #
# Remote OK
# --------------------------------------------------------------------------- #

def fetch_remoteok() -> list[Job]:
    data = get_with_retries(lambda: http_json("https://remoteok.com/api", timeout=90), "Remote OK")
    if not isinstance(data, list):
        raise ValueError("unexpected Remote OK response shape")
    jobs = []
    for j in data:
        if not isinstance(j, dict) or "legal" in j or not j.get("id"):
            continue  # the first item is their terms of service
        url = j.get("url") or f"https://remoteok.com/remote-jobs/{j.get('slug') or j.get('id')}"
        jobs.append(Job(
            uid=f"remoteok:{j.get('id')}",
            company=(j.get("company") or "").strip(),
            title=(j.get("position") or "").strip(),
            url=url,                                     # direct link to Remote OK, as their terms ask
            location=j.get("location") or "",
            workplace="remote",
            description=strip_html(j.get("description") or ""),
            source="Remote OK", source_url=SOURCE_HOMES["Remote OK"], kind="aggregator",
            extra=_salary_extra(j.get("salary_min"), j.get("salary_max")),
        ))
    return jobs


# --------------------------------------------------------------------------- #
# Himalayas
# --------------------------------------------------------------------------- #

def fetch_himalayas(searches: list[str]) -> list[Job]:
    jobs: dict[str, Job] = {}
    errors = []
    for q in searches:
        url = ("https://himalayas.app/jobs/api/search?"
               + urllib.parse.urlencode({"q": q, "country": "US", "sort": "recent"}))
        try:
            data = get_with_retries(lambda: http_json(url, timeout=60), f"Himalayas search '{q}'")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            continue
        finally:
            time.sleep(2)
        for j in (data or {}).get("jobs") or []:
            link = j.get("guid") or j.get("applicationLink") or ""
            uid = f"himalayas:{link.rstrip('/').split('himalayas.app/')[-1] or _slug(j.get('title', ''))}"
            restrictions = j.get("locationRestrictions") or []
            jobs[uid] = Job(
                uid=uid,
                company=(j.get("companyName") or "").strip(),
                title=(j.get("title") or "").strip(),
                url=j.get("applicationLink") or link,
                location=", ".join(restrictions) if restrictions else "Anywhere",
                workplace="remote",
                description=strip_html(j.get("description") or j.get("excerpt") or ""),
                source="Himalayas", source_url=SOURCE_HOMES["Himalayas"], kind="aggregator",
                extra=_salary_extra(j.get("minSalary"), j.get("maxSalary"))
                if (j.get("currency") or "USD") == "USD" and (j.get("salaryPeriod") or "annual") == "annual" else {},
            )
    if errors and not jobs:
        raise RuntimeError("; ".join(errors[:3]))
    return list(jobs.values())


# --------------------------------------------------------------------------- #
# We Work Remotely
# --------------------------------------------------------------------------- #

def fetch_weworkremotely(feeds: list[str]) -> list[Job]:
    jobs: dict[str, Job] = {}
    errors = []
    for url in feeds:
        try:
            xml = get_with_retries(lambda: http_text(url, timeout=60), "We Work Remotely feed")
            root = ET.fromstring(xml.encode("utf-8"))
        except Exception as e:  # noqa: BLE001
            errors.append(f"{url.rsplit('/', 1)[-1]}: {e}")
            continue
        finally:
            time.sleep(1)
        for it in root.iter("item"):
            link = (it.findtext("link") or it.findtext("guid") or "").strip()
            raw_title = (it.findtext("title") or "").strip()
            company, _, title = raw_title.partition(": ")
            if not title:
                company, title = "", raw_title
            region = (it.findtext("region") or "").strip()
            country = re.sub(r"[^\w\s,().-]", "", it.findtext("country") or "").strip()
            location = ", ".join(x for x in (region, country) if x)
            uid = f"weworkremotely:{link.rstrip('/').rsplit('/', 1)[-1] or _slug(raw_title)}"
            jobs[uid] = Job(
                uid=uid,
                company=company.strip(),
                title=title.strip(),
                url=link,                                  # their page, credited in the email
                location=location,
                workplace="remote",
                description=strip_html(it.findtext("description") or ""),
                source="We Work Remotely", source_url=SOURCE_HOMES["We Work Remotely"], kind="aggregator",
            )
    if errors and not jobs:
        raise RuntimeError("; ".join(errors[:3]))
    return list(jobs.values())


# --------------------------------------------------------------------------- #
# Hacker News "Ask HN: Who is hiring?"
# --------------------------------------------------------------------------- #

HN_ROLE_WORDS = re.compile(
    r"program|project|operations|\bops\b|strategy|analyst|product owner|product manager|"
    r"chief of staff|special projects|implementation|\btpm\b|business|process|delivery|"
    r"customer success|solutions", re.I)


def latest_hn_thread() -> dict:
    """The newest 'Ask HN: Who is hiring?' story, with its top-level comments."""
    url = "https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=10"
    data = get_with_retries(lambda: http_json(url, timeout=60), "Hacker News search")
    hits = [h for h in data.get("hits") or [] if "who is hiring" in (h.get("title") or "").lower()]
    if not hits:
        raise ValueError("couldn't find a 'Who is hiring?' thread")
    story_id = hits[0]["objectID"]
    item = get_with_retries(
        lambda: http_json(f"https://hn.algolia.com/api/v1/items/{story_id}", timeout=90), "Hacker News thread")
    comments = []
    for c in item.get("children") or []:
        text = c.get("text") or ""
        if not text or c.get("author") is None:
            continue  # deleted or flagged
        comments.append({"id": str(c["id"]), "text": strip_html(text), "created": c.get("created_at", "")})
    return {"id": str(story_id), "title": hits[0].get("title", ""), "comments": comments}


def hn_worth_extracting(text: str) -> bool:
    """Cheap check before spending AI on a post: mentions remote and a role we might want."""
    return bool(REMOTE_WORD.search(text)) and bool(HN_ROLE_WORDS.search(text))


HN_SYSTEM = """You turn Hacker News "Who is hiring?" posts into structured job \
listings. Each post is written by the hiring company and usually starts with a \
line like "Company | Role(s) | Location | REMOTE/ONSITE | Salary | URL".

For each post, list every distinct role it advertises (at most 6 per post; if a \
post just says "hiring engineers" list that as one role). Do not invent roles.

Reply with JSON only: a list of objects shaped:
{"post_id": "<the post id>", "company": "<company name>", "title": "<role title>", \
"remote": "<one of: Remote (US), Remote (US + other countries), Remote (non-US), \
Hybrid, Onsite, Unclear>", "location": "<location text from the post, or empty>", \
"link": "<the best apply/careers/job URL in the post for this role, or empty>"}
"""


def hn_extract(gemini: Gemini, posts: list[dict], thread_id: str, max_chars: int = 2500) -> list[Job]:
    """One Gemini call: pull the roles out of a batch of HN posts."""
    prompt = "Extract the roles from these posts.\n\n" + "\n".join(
        f"### Post id: {p['id']}\n{p['text'][:max_chars]}\n" for p in posts)
    items = as_list(gemini.ask_json(HN_SYSTEM, prompt), "roles", "jobs")
    by_id = {p["id"]: p for p in posts}
    jobs = []
    for it in items:
        if not isinstance(it, dict):
            continue
        pid = str(it.get("post_id") or "").strip().lstrip("#")
        post = by_id.get(pid)
        title = str(it.get("title") or "").strip()
        if not post or not title:
            continue
        remote = str(it.get("remote") or "Unclear")
        low = remote.lower()
        workplace = "onsite" if low == "onsite" else "hybrid" if low == "hybrid" else \
            "remote" if low.startswith("remote") else ""
        hn_url = f"https://news.ycombinator.com/item?id={pid}"
        link = str(it.get("link") or "").strip()
        if not link.startswith("http"):
            link = hn_url
        location = str(it.get("location") or "").strip()
        jobs.append(Job(
            uid=f"hn:{pid}:{_slug(title)}",
            company=str(it.get("company") or "").strip() or "Unknown company",
            title=title,
            url=link,
            location=location or remote,
            workplace=workplace,
            description=post["text"],
            source="Hacker News: Who is hiring?", source_url=hn_url, kind="aggregator",
            extra={"hn_post": pid, "hn_thread": thread_id, "non_us": low == "remote (non-us)"},
        ))
    return jobs


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
