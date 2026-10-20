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

  * VC portfolio job boards (Getro): job boards that venture firms run for all
    their portfolio companies (Lux, DCVC, Khosla...). One search per title
    keyword per board; only remote US jobs are kept. Each job links to the
    company's own posting.
  * Jobicy: free remote-jobs API, US-eligible jobs; asks for a link back and
    at most one request an hour. We use 1 a day.
  * Working Nomads: free public job feed; one request a day, links to their page.

  * Job alert emails from LinkedIn, Indeed, Wellfound, Glassdoor, Built In,
    Welcome to the Jungle (Otta), ZipRecruiter, Climatebase and Idealist: none
    of these has a public job feed,
    so instead the job alerts they email you are read from your Gmail inbox
    (with the same Gmail app password that sends the digest). Nothing is
    fetched from LinkedIn or Indeed themselves; each job links to its page there.

These three need a free key (a GitHub secret); each is skipped until its key is added:
  * JSearch (RapidAPI): Google for Jobs results. The free plan has a small
    monthly allowance, so searches are capped per day and per month.
  * Adzuna: a big job search site (lots of Indeed-style listings). Free
    developer key, 250 requests a day; we use one per search.
  * USAJobs: US federal jobs. Free key; asks for your email as the User-Agent.
"""
from __future__ import annotations

import base64
import email
import email.utils
import gzip
import hashlib
import html
import imaplib
import json
import os
import re
import time
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

from common import (REMOTE_WORD, Gemini, Job, as_list, get_with_retries, http_json, http_text,
                    log, strip_html)

UA_NOTE = "personal job alert emailed to one person"

SOURCE_HOMES = {
    "Hacker News": "https://news.ycombinator.com",
    "Remotive": "https://remotive.com",
    "Remote OK": "https://remoteok.com",
    "Himalayas": "https://himalayas.app",
    "We Work Remotely": "https://weworkremotely.com",
    "Jobicy": "https://jobicy.com",
    "VC job boards": "https://www.getro.com",
    "Working Nomads": "https://www.workingnomads.com",
    "Google Jobs": "https://www.google.com/search?q=jobs&ibp=htl;jobs",
    "Adzuna": "https://www.adzuna.com",
    "USAJobs": "https://www.usajobs.gov",
    "LinkedIn": "https://www.linkedin.com/jobs/",
    "Indeed": "https://www.indeed.com",
    "Wellfound": "https://wellfound.com/jobs",
    "Glassdoor": "https://www.glassdoor.com",
    "Built In": "https://builtin.com/jobs",
    "Welcome to the Jungle": "https://www.welcometothejungle.com",
    "ZipRecruiter": "https://www.ziprecruiter.com",
    "Climatebase": "https://climatebase.org",
    "Idealist": "https://www.idealist.org",
}


def env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def has_keys(key: str) -> bool:
    """Whether the GitHub secrets a keyed source needs are set."""
    need = {"jsearch": ("RAPIDAPI_KEY",), "adzuna": ("ADZUNA_APP_ID", "ADZUNA_APP_KEY"),
            "usajobs": ("USAJOBS_API_KEY",),
            "email_alerts": ("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")}.get(key, ())
    return all(env(n) for n in need)


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
# Venture capital portfolio job boards (Getro)
# --------------------------------------------------------------------------- #

def _getro_collection(board_url: str) -> str:
    """The board's Getro collection id, read from its own jobs page."""
    html_text = get_with_retries(lambda: http_text(board_url.rstrip("/") + "/jobs", timeout=60), board_url)
    m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html_text, re.S)
    if m:
        try:
            net = (json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("network") or {})
            if net.get("id"):
                return str(net["id"])
        except (ValueError, AttributeError):
            pass
    m = re.search(r'"network"\s*:\s*\{\s*"id"\s*:\s*"?(\d+)', html_text) or re.search(r'collections/(\d+)', html_text)
    if not m:
        raise ValueError(f"couldn't find the job board id on {board_url}")
    return m.group(1)


def fetch_vc_boards(boards: list[dict], searches: list[str]) -> list[Job]:
    """Remote US jobs from VC portfolio job boards. boards: [{name, url}]."""
    jobs: dict[str, Job] = {}
    errors = []
    for b in boards:
        name, url = b.get("name") or b.get("url"), str(b.get("url") or "").rstrip("/")
        if not url or b.get("enabled") is False:
            continue
        try:
            coll = _getro_collection(url)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: {e}")
            continue
        for q in searches:
            api = f"https://api.getro.com/api/v2/collections/{coll}/search/jobs"
            try:
                data = get_with_retries(lambda: http_json(api, method="POST", timeout=60,
                                                          body={"hitsPerPage": 100, "page": 0, "filters": {}, "query": q}),
                                        f"{name} job board search '{q}'")
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: {e}")
                break
            finally:
                time.sleep(1)
            for j in ((data or {}).get("results") or {}).get("jobs") or []:
                if not isinstance(j, dict) or not j.get("url"):
                    continue
                mode = str(j.get("work_mode") or "").lower()
                locs = j.get("searchable_locations") or j.get("locations") or []
                us = any("united states" in str(l).lower() for l in locs) or not locs
                if mode != "remote" or not us:
                    continue
                org = j.get("organization") or {}
                uid = f"getro:{j.get('id') or j['url']}"
                extra = {"country": "US"}
                if j.get("compensation_public") and (j.get("compensation_currency") or "USD") == "USD" \
                        and (j.get("compensation_period") or "year") in ("year", "yearly", "annual"):
                    extra.update(_salary_extra((j.get("compensation_amount_min_cents") or 0) / 100,
                                               (j.get("compensation_amount_max_cents") or 0) / 100))
                tags = ", ".join(org.get("industry_tags") or org.get("industryTags") or [])
                jobs[uid] = Job(
                    uid=uid,
                    company=(org.get("name") or "").strip(),
                    title=(j.get("title") or "").strip(),
                    url=j["url"],
                    location="Remote (US)",
                    workplace="remote",
                    description=(f"Backed by {name}. Company: {org.get('name') or ''}"
                                 + (f" ({tags})" if tags else "") + (f", stage {org.get('stage')}" if org.get("stage") else "")
                                 + (". Skills: " + ", ".join(j.get("skills") or []) if j.get("skills") else "")
                                 + (f". Seniority: {j.get('seniority')}" if j.get("seniority") else "") + "."),
                    source=f"{name} job board", source_url=url, kind="aggregator",
                    extra=extra,
                )
    if errors and not jobs:
        raise RuntimeError("; ".join(errors[:3]))
    return list(jobs.values())


# --------------------------------------------------------------------------- #
# Jobicy and Working Nomads
# --------------------------------------------------------------------------- #

def fetch_jobicy() -> list[Job]:
    url = "https://jobicy.com/api/v2/remote-jobs?count=100&geo=usa"
    data = get_with_retries(lambda: http_json(url, timeout=90), "Jobicy")
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("unexpected Jobicy response shape")
    jobs = []
    for j in data["jobs"]:
        if not isinstance(j, dict) or not j.get("id"):
            continue
        usd = (j.get("salaryCurrency") or "USD").upper() == "USD"
        jobs.append(Job(
            uid=f"jobicy:{j['id']}",
            company=strip_html(j.get("companyName") or "").strip(),
            title=strip_html(j.get("jobTitle") or "").strip(),
            url=j.get("url") or "",                      # Jobicy's own page, as their terms ask
            location=j.get("jobGeo") or "USA",
            workplace="remote",
            description=strip_html(j.get("jobDescription") or j.get("jobExcerpt") or ""),
            source="Jobicy", source_url=SOURCE_HOMES["Jobicy"], kind="aggregator",
            extra=_salary_extra(j.get("annualSalaryMin"), j.get("annualSalaryMax")) if usd else {},
        ))
    return jobs


def fetch_workingnomads() -> list[Job]:
    data = get_with_retries(lambda: http_json("https://www.workingnomads.com/api/exposed_jobs/", timeout=90),
                            "Working Nomads")
    if not isinstance(data, list):
        raise ValueError("unexpected Working Nomads response shape")
    jobs = []
    for j in data:
        if not isinstance(j, dict) or not j.get("url"):
            continue
        jobs.append(Job(
            uid=f"workingnomads:{j['url'].rstrip('/').rsplit('/', 1)[-1]}",
            company=strip_html(j.get("company_name") or "").strip(),
            title=strip_html(j.get("title") or "").strip(),
            url=j["url"],                                # Working Nomads' own page
            location=j.get("location") or "",
            workplace="remote",
            description=strip_html(j.get("description") or ""),
            source="Working Nomads", source_url=SOURCE_HOMES["Working Nomads"], kind="aggregator",
        ))
    return jobs


# --------------------------------------------------------------------------- #
# Google Jobs, through JSearch on RapidAPI
# --------------------------------------------------------------------------- #

# Sites that re-post other companies' jobs under their own name (duplicates, often spammy).
JSEARCH_REPOSTERS = re.compile(r"mysmartpros|remotepromsp|remote jobs usa|jobgether|virtualvocations|"
                               r"talent\.com|jooble|lensa|jobright|hiring cafe|dailyremote", re.I)


def fetch_jsearch(searches: list[str], usage: dict, per_day: int, per_month: int) -> list[Job]:
    """One request (10 results, remote US, posted in the last 3 days) per search.
    `usage` ({"month": "YYYY-MM", "used": n}) is kept in seen_jobs.json so the
    free monthly allowance is never exceeded."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    if usage.get("month") != month:
        usage.clear()
        usage.update({"month": month, "used": 0})
    budget = max(0, min(per_day, per_month - int(usage.get("used") or 0)))
    if not budget:
        log(f"  JSearch: this month's {per_month} searches are used up")
        return []
    jobs: dict[str, Job] = {}
    errors = []
    headers = {"X-RapidAPI-Key": env("RAPIDAPI_KEY"), "X-RapidAPI-Host": "jsearch.p.rapidapi.com"}
    for q in searches[:budget]:
        url = "https://jsearch.p.rapidapi.com/search-v2?" + urllib.parse.urlencode({
            "query": f"{q} remote", "page": 1, "num_pages": 1, "country": "us",
            "date_posted": "3days", "work_from_home": "true", "remote_jobs_only": "true"})
        usage["used"] = int(usage.get("used") or 0) + 1
        try:
            data = get_with_retries(lambda: http_json(url, headers=headers, timeout=60), f"JSearch '{q}'")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            continue
        finally:
            time.sleep(1.5)
        found = (data or {}).get("data") or []
        if isinstance(found, dict):          # search-v2 returns {"jobs": [...], "cursor": ...}
            found = found.get("jobs") or []
        for j in found:
            if not isinstance(j, dict) or not j.get("job_id"):
                continue
            if JSEARCH_REPOSTERS.search(f"{j.get('employer_name') or ''} {j.get('job_publisher') or ''}"):
                continue                     # sites that copy other companies' listings
            loc = ", ".join(x for x in (j.get("job_city"), j.get("job_state"), j.get("job_country")) if x)
            period = str(j.get("job_salary_period") or "").upper()
            publisher = (j.get("job_publisher") or "").strip()
            uid = f"jsearch:{j['job_id']}"
            jobs[uid] = Job(
                uid=uid,
                company=(j.get("employer_name") or "").strip(),
                title=(j.get("job_title") or "").strip(),
                url=j.get("job_apply_link") or j.get("job_google_link") or "",
                location=("Remote" + (f" ({loc})" if loc else "")) if j.get("job_is_remote") else (loc or j.get("job_location") or ""),
                workplace="remote" if j.get("job_is_remote") else "",
                description=strip_html(j.get("job_description") or ""),
                source="Google Jobs" + (f" (from {publisher})" if publisher else ""),
                source_url=SOURCE_HOMES["Google Jobs"], kind="aggregator",
                extra={"country": (j.get("job_country") or "").upper(),
                       **(_salary_extra(j.get("job_min_salary"), j.get("job_max_salary")) if period in ("", "YEAR") else {})},
            )
    if errors and not jobs:
        raise RuntimeError("; ".join(errors[:3]))
    return list(jobs.values())


# --------------------------------------------------------------------------- #
# Adzuna
# --------------------------------------------------------------------------- #

def fetch_adzuna(searches: list[str]) -> list[Job]:
    """Jobs whose TITLE matches each search and that mention remote, from the last 3 days."""
    jobs: dict[str, Job] = {}
    errors = []
    for q in searches:
        url = "https://api.adzuna.com/v1/api/jobs/us/search/1?" + urllib.parse.urlencode({
            "app_id": env("ADZUNA_APP_ID"), "app_key": env("ADZUNA_APP_KEY"), "results_per_page": 50,
            "title_only": q, "what": "remote", "max_days_old": 3, "sort_by": "date",
            "content-type": "application/json"})
        try:
            data = get_with_retries(lambda: http_json(url, timeout=60), f"Adzuna search '{q}'")
        except Exception as e:  # noqa: BLE001
            key = env("ADZUNA_APP_KEY")
            errors.append(str(e).replace(key, "***") if key else str(e))
            continue
        finally:
            time.sleep(2.5)
        for j in (data or {}).get("results") or []:
            if not isinstance(j, dict) or not j.get("id"):
                continue
            title = strip_html(j.get("title") or "").strip()
            desc = strip_html(j.get("description") or "")
            loc = ((j.get("location") or {}).get("display_name") or "").strip()
            uid = f"adzuna:{j['id']}"
            jobs[uid] = Job(
                uid=uid,
                company=strip_html((j.get("company") or {}).get("display_name") or "").strip(),
                title=title,
                url=j.get("redirect_url") or "",           # Adzuna's own page, as their terms ask
                location=loc,
                workplace="remote" if REMOTE_WORD.search(f"{title} {loc} {desc}") else "",
                description=desc,
                source="Adzuna", source_url=SOURCE_HOMES["Adzuna"], kind="aggregator",
                extra={"country": "US",
                       **({} if str(j.get("salary_is_predicted")) == "1" else _salary_extra(j.get("salary_min"), j.get("salary_max")))},
            )
    if errors and not jobs:
        raise RuntimeError("; ".join(errors[:3]))
    return list(jobs.values())


# --------------------------------------------------------------------------- #
# USAJobs (federal jobs)
# --------------------------------------------------------------------------- #

def fetch_usajobs(searches: list[str]) -> list[Job]:
    """Remote federal jobs posted in the last 3 days, one request per search."""
    headers = {"Host": "data.usajobs.gov", "Authorization-Key": env("USAJOBS_API_KEY"),
               "User-Agent": env("USAJOBS_EMAIL") or env("GMAIL_ADDRESS")}
    jobs: dict[str, Job] = {}
    errors = []
    for q in searches:
        url = "https://data.usajobs.gov/api/search?" + urllib.parse.urlencode({
            "Keyword": q, "RemoteIndicator": "True", "DatePosted": 3, "ResultsPerPage": 100})
        try:
            data = get_with_retries(lambda: http_json(url, headers=headers, timeout=60), f"USAJobs search '{q}'")
        except Exception as e:  # noqa: BLE001
            errors.append(str(e))
            continue
        finally:
            time.sleep(1)
        for item in ((data or {}).get("SearchResult") or {}).get("SearchResultItems") or []:
            d = (item or {}).get("MatchedObjectDescriptor") or {}
            if not d.get("PositionID") and not d.get("PositionURI"):
                continue
            details = ((d.get("UserArea") or {}).get("Details") or {})
            pay = next((p for p in d.get("PositionRemuneration") or [] if p.get("RateIntervalCode") == "PA"), {})
            uid = f"usajobs:{d.get('PositionID') or d.get('PositionURI')}"
            org = d.get("OrganizationName") or ""
            dept = d.get("DepartmentName") or ""
            jobs[uid] = Job(
                uid=uid,
                company=org if not dept or dept == org else f"{org} ({dept})",
                title=(d.get("PositionTitle") or "").strip(),
                url=d.get("PositionURI") or (d.get("ApplyURI") or [""])[0],
                location=d.get("PositionLocationDisplay") or "Remote (US)",
                workplace="remote",
                description=strip_html(" ".join(x for x in (details.get("JobSummary"), d.get("QualificationSummary"))
                                                 if isinstance(x, str))),
                source="USAJobs", source_url=SOURCE_HOMES["USAJobs"], kind="aggregator",
                extra={"country": "US", **_salary_extra(pay.get("MinimumRange"), pay.get("MaximumRange"))},
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
# LinkedIn and Indeed job alert emails (read from your Gmail)
# --------------------------------------------------------------------------- #

# Job sites whose alert emails are read: who sends them, how to find a job's id in
# a link, and the job's own address (None = keep the email's link).
ALERT_SITES = {
    "LinkedIn": {"from": ("linkedin.com",), "id": r"linkedin\.com/\S*?/jobs/view/(?:[^/?\s]*-)?(\d{6,})",
                 "url": "https://www.linkedin.com/jobs/view/{id}/"},
    "Indeed": {"from": ("indeed.com",), "id": None, "url": "https://www.indeed.com/viewjob?jk={id}"},
    "Wellfound": {"from": ("wellfound.com", "angel.co"),
                  "id": r"(?:wellfound\.com|angel\.co)/(?:company/[^/\s]+/)?jobs/(\d{4,})",
                  "url": "https://wellfound.com/jobs/{id}"},
    "Glassdoor": {"from": ("glassdoor.com",), "id": r"glassdoor\.com/\S*?[?&](?:jl|jobListingId)=(\d{6,})",
                  "url": "https://www.glassdoor.com/partner/jobListing.htm?jobListingId={id}"},
    "Built In": {"from": ("builtin.com",), "id": r"builtin\.com/job/[^\s\"'?#]*?/(\d{5,})", "url": None},
    "Welcome to the Jungle": {"from": ("welcometothejungle.com", "otta.com"),
                              "id": r"(?:welcometothejungle\.com|otta\.com)/(?:\S*?/)?jobs/([A-Za-z0-9_-]{6,})",
                              "url": None},
    "ZipRecruiter": {"from": ("ziprecruiter.com",), "id": r"ziprecruiter\.com/\S*?[?&](?:jid|lvk)=([A-Za-z0-9_-]{8,})",
                     "url": None},
    "Climatebase": {"from": ("climatebase.org",), "id": r"climatebase\.org/job/(\d+)",
                    "url": "https://climatebase.org/job/{id}"},
    "Idealist": {"from": ("idealist.org",), "id": r"idealist\.org/\S*?-job/([0-9a-f-]{20,})", "url": None},
}
# Tracked click links (no visible job id) that still look like they open a job.
ALERT_TRACKED = re.compile(r"/(v3/|rc/clk|pagead/clk|viewjob|m/viewjob|jobs?/|job-listing|k/|ekr/|clk|partner/)", re.I)
ALERT_LINK = re.compile(r"<a\b[^>]*?href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", re.S | re.I)
# Card lines that aren't the job itself (badges, buttons, footers).
ALERT_NOISE = re.compile(
    r"^(view (job|all|more)\b.*|see (all|more)\b.*|search (for )?(more )?jobs.*|apply( now)?|easy ?apply|easily apply|actively recruiting|"
    r"promoted|new|just posted|be an early applicant|\d+ (connections?|alumni|applicants?)\b.*|"
    r"responsive employer|urgently hiring|hiring multiple candidates|job alert.*|unsubscribe.*|"
    r"manage (job )?alerts.*|.*school alumni.*|.*works here.*|\d+\+? days? ago|today|"
    r"(more|similar|other|recommended|new|top|all) .*\bjobs?|jobs? (for you|you may like).*|"
    r"posted \d+.*|active \d+.*|\W*)$", re.I)
ALERT_FOOTER = re.compile(r"unsubscribe|manage (your )?(job )?alerts|you are receiving|privacy policy|"
                          r"this email was (intended|sent)|help center|\u00a9|copyright", re.I)
MONEY = re.compile(r"\$\s?(\d[\d,.]*)\s?(k)?\b(?:\s*(?:-|–|to)\s*\$?\s?(\d[\d,.]*)\s?(k)?)?", re.I)


def _indeed_jk(href: str) -> str:
    m = re.search(r"[?&](?:jk|vjk)=([0-9a-f]{16})\b", href)
    if m:
        return m.group(1)
    m = re.search(r"/v3/([A-Za-z0-9_\-]{20,})", href)         # cts.indeed.com tracking links
    if m:
        try:
            raw = base64.urlsafe_b64decode(m.group(1) + "=" * (-len(m.group(1)) % 4))
            raw = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
            m = re.search(rb"jk=([0-9a-f]{16})", raw)
            return m.group(1).decode() if m else ""
        except Exception:  # noqa: BLE001
            return ""
    return ""


def _alert_key(site: str, href: str) -> str:
    """The job's id on that site, or "" when a link isn't (visibly) a job."""
    href = html.unescape(href)
    if site == "Indeed":
        return _indeed_jk(href) if re.search(r"indeed\.com", href, re.I) else ""
    m = re.search(ALERT_SITES[site]["id"], href, re.I)
    return m.group(1) if m else ""


def _site_slug(site: str) -> str:
    return re.sub(r"[^a-z0-9]", "", site.lower())


def _yearly(n: str, k: str) -> float:
    v = float(n.replace(",", "") or 0)
    return v * 1000 if k else v


def parse_alert_email(site: str, body: str) -> list[dict]:
    """Job cards from one alert email: [{id, title, lines}] in the email's order."""
    marks = {}

    def mark(m):
        key = _alert_key(site, m.group(1))
        text = strip_html(m.group(2)).replace("\n", " ").strip()
        href = html.unescape(m.group(1))
        if (not key and site != "LinkedIn" and text and 4 <= len(text) <= 120 and not ALERT_NOISE.match(text)
                and any(d in href.lower() for d in ALERT_SITES[site]["from"]) and ALERT_TRACKED.search(href)):
            key = "h" + hashlib.sha1(text.lower().encode()).hexdigest()[:15]   # tracking link with no visible id
        if not key:
            return f"\n{text}\n"
        marks.setdefault(key, m.group(1))
        return f"\n\x00{key}\x00{text}\n"
    body = re.sub(r"<(tr|td|th|table|tbody)\b[^>]*>", "\n", body or "", flags=re.I)  # email layouts are tables
    lines = strip_html(ALERT_LINK.sub(mark, body)).split("\n")
    cards: dict[str, dict] = {}
    current = None
    for line in lines:
        line = line.strip()
        m = re.match(r"\x00(\w+)\x00(.*)", line)
        if m:
            key, text = m.group(1), m.group(2).strip()
            current = cards.setdefault(key, {"id": key, "title": "", "lines": [], "href": marks[key]})
            if text and not ALERT_NOISE.match(text):
                if not current["title"]:
                    current["title"] = text
                elif text != current["title"] and text not in current["lines"]:
                    current["lines"].append(text)
            continue
        if current is None or not line:
            continue
        if ALERT_FOOTER.search(line):
            current = None
            continue
        if not ALERT_NOISE.match(line) and line != current["title"] and len(current["lines"]) < 8:
            current["lines"].append(line)
    return [c for c in cards.values() if c["title"]]


def _alert_job(site: str, card: dict, received: str) -> Job:
    details = []
    for ln in card["lines"]:
        details.extend(p.strip() for p in re.split(r"\s+[·•|–-]\s+", ln) if p.strip())
    company = details[0] if details else ""
    rest = details[1:]
    location = next((d for d in rest if REMOTE_WORD.search(d) or re.search(
        r",\s*[A-Z]{2}\b|united states|\bUS\b|\bUSA\b|hybrid|on-?site", d, re.I)), "")
    extra = {"country": "US", "alert_received": received}
    money = next((MONEY.search(ln) for ln in card["lines"][1:] or card["lines"] if MONEY.search(ln)), None)
    if money:
        lo = _yearly(money.group(1), money.group(2))
        hi = _yearly(money.group(3), money.group(4)) if money.group(3) else lo
        extra.update(_salary_extra(lo, hi))
    template = ALERT_SITES[site]["url"]
    url = (template.format(id=card["id"]) if template and not card["id"].startswith("h")
           else html.unescape(card["href"]))
    uid = f"{_site_slug(site)}:{card['id']}"
    text = "\n".join(x for x in (card["title"], *card["lines"]) if x)
    return Job(
        uid=uid, company=company, title=card["title"], url=url, location=location,
        workplace="remote" if REMOTE_WORD.search(location) else "",
        description=(f"{text}\n(From {'an' if site[0] in 'AEIOU' else 'a'} {site} job alert email. Only the title, company, location and any "
                     f"pay are known; the full description is on {site}.)"),
        source=f"{site} job alert", source_url=SOURCE_HOMES[site], kind="aggregator", extra=extra,
    )


def _html_body(msg) -> str:
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            raw = part.get_payload(decode=True) or b""
            return raw.decode(part.get_content_charset() or "utf-8", "replace")
    return ""


def fetch_email_alerts(days: int = 3) -> list[Job]:
    """Jobs from LinkedIn and Indeed job alert emails in your Gmail from the last `days` days.
    Opens the mailbox read-only, so nothing is marked read, moved or deleted."""
    imap = imaplib.IMAP4_SSL("imap.gmail.com", timeout=60)
    jobs: dict[str, Job] = {}
    try:
        imap.login(env("GMAIL_ADDRESS"), env("GMAIL_APP_PASSWORD").replace(" ", ""))
        # All Mail, so alerts a Gmail filter skipped the inbox for still count.
        for box in ('"[Gmail]/All Mail"', '"[Google Mail]/All Mail"', "INBOX"):
            if imap.select(box, readonly=True)[0] == "OK":
                break
        since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%d-%b-%Y")
        emails = 0
        for site, info in ALERT_SITES.items():
            ids = []
            for domain in info["from"]:
                status, data = imap.search(None, "FROM", f'"{domain}"', "SINCE", since)
                ids += (data[0] or b"").split()[-60:] if status == "OK" else []
            for num in ids:
                status, parts = imap.fetch(num, "(BODY.PEEK[])")
                if status != "OK" or not parts or not isinstance(parts[0], tuple):
                    continue
                msg = email.message_from_bytes(parts[0][1])
                cards = parse_alert_email(site, _html_body(msg))
                if not cards:
                    continue                  # not a job alert (messages, news, receipts)
                emails += 1
                received = email.utils.parsedate_to_datetime(msg.get("Date")).date().isoformat() \
                    if msg.get("Date") else ""
                for card in cards:
                    job = _alert_job(site, card, received)
                    jobs.setdefault(job.uid, job)
        per_site = {site: sum(1 for j in jobs.values() if j.source.startswith(site)) for site in ALERT_SITES}
        no_company = sum(1 for j in jobs.values() if not j.company)
        log(f"  {emails} job alert emails from the last {days} days: "
            + ", ".join(f"{n} {site}" for site, n in per_site.items() if n)
            + (f" ({no_company} with no company found)" if no_company else ""))
    finally:
        try:
            imap.logout()
        except Exception:  # noqa: BLE001
            pass
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
