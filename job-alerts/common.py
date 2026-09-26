"""Shared pieces used by the daily job alerts and the weekly company discovery:
settings, HTTP, the Greenhouse/Lever/Ashby board readers, the keyword
pre-filter, the Gemini client, state files and email.

Only dependency outside the standard library: PyYAML.
"""
from __future__ import annotations

import copy
import html
import json
import os
import re
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

HERE = Path(__file__).resolve().parent
COMPANIES_FILE = HERE / "companies.yaml"
PROFILE_FILE = HERE / "profile.md"
SETTINGS_FILE = HERE / "settings.yaml"
SEEN_FILE = HERE / "seen_jobs.json"
DISCOVERY_STATE_FILE = HERE / "discovery_state.json"

PACIFIC = ZoneInfo("America/Los_Angeles")

BOARD_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "workable": "https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true",
    "smartrecruiters": "https://api.smartrecruiters.com/v1/companies/{slug}/postings?limit=100&offset={offset}",
}
PLATFORM_LABELS = {"greenhouse": "Greenhouse", "lever": "Lever", "ashby": "Ashby",
                   "workable": "Workable", "smartrecruiters": "SmartRecruiters"}
CAREERS_URLS = {
    "greenhouse": "https://job-boards.greenhouse.io/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "workable": "https://apply.workable.com/{slug}/",
    "smartrecruiters": "https://careers.smartrecruiters.com/{slug}",
}
SMARTRECRUITERS_MAX_PAGES = 10  # 1,000 jobs; enough for any company we'd watch

# Everything here can be overridden in settings.yaml.
DEFAULT_SETTINGS = {
    "score_threshold": 65,
    "gemini_model": "gemini-flash-latest",
    "fallback_model": "gemini-flash-lite-latest",
    "jobs_per_ai_call": 20,
    "max_ai_calls_per_run": 15,
    "seconds_between_ai_calls": 7,
    "max_description_chars": 1500,
    "require_remote_mention": True,
    "forget_seen_jobs_after_days": 365,
    "sources": {
        "company_boards": True,
        "hacker_news": True,
        "remotive": True,
        "remoteok": True,
        "himalayas": True,
        "weworkremotely": True,
        "startup_boards": True,
    },
    "startup_boards": {
        "min_team_size": 5,
        "new_companies_per_run": 400,
        "recheck_missing_after_days": 90,
        "recheck_found_after_days": 60,
    },
    "hacker_news_max_ai_calls": 3,
    "hacker_news_posts_per_ai_call": 12,
    "weworkremotely_feeds": [
        "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
        "https://weworkremotely.com/categories/remote-product-jobs.rss",
        "https://weworkremotely.com/categories/all-other-remote-jobs.rss",
    ],
    "himalayas_searches": [
        "technical program manager", "program manager", "product operations",
        "strategy and operations", "business analyst", "product owner",
        "chief of staff", "special projects", "implementation lead",
    ],
    "my_target_titles": [],
    "too_senior_title_words": [
        "director", "vp", "svp", "evp", "vice president", "head of", "chief", "principal",
        "staff", "president", "partner", "general manager",
    ],
    "drop_if_ai_says_not_remote_us": True,
    "job_board_title_keywords": [
        "program", "project", "operations", "ops", "strategy", "analyst",
        "product owner", "chief of staff", "special projects", "implementation",
        "process", "delivery", "tpm", "r&d", "portfolio", "transformation",
    ],
    "discovery": {
        "enabled": True,
        "max_new_companies_per_week": 25,
        "lookback_days": 8,
        "min_fit_score": 60,
        "max_ai_calls": 4,
        "articles_per_ai_call": 25,
        "max_companies_to_check": 60,
        "feeds": [],
        "yc_directory": True,
        "yc_min_team_size": 15,
        "yc_max_companies_per_week": 40,
        "yc_sector_keywords": [],
    },
}

USER_AGENT = "job-alerts/1.0 (personal daily job alert; runs on GitHub Actions)"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def log(msg: str = "") -> None:
    print(msg, flush=True)


def load_yaml(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return default if data is None else data


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_settings() -> dict:
    return _merge(DEFAULT_SETTINGS, load_yaml(SETTINGS_FILE, {}) or {})


def source_on(settings: dict, name: str) -> bool:
    return bool((settings.get("sources") or {}).get(name, True))


def load_companies() -> list[dict]:
    data = load_yaml(COMPANIES_FILE, {})
    companies = data.get("companies", []) if isinstance(data, dict) else data
    cleaned = []
    for c in companies or []:
        if not isinstance(c, dict) or not c.get("platform") or not c.get("slug"):
            log(f"  ! Skipping a malformed entry in companies.yaml: {c!r}")
            continue
        if c.get("enabled") is False:
            continue
        cleaned.append({
            "name": str(c.get("name") or c["slug"]),
            "platform": str(c["platform"]).strip().lower(),
            "slug": str(c["slug"]).strip(),
        })
    return cleaned


def load_profile() -> str:
    return PROFILE_FILE.read_text(encoding="utf-8")


def _request(url: str, *, method: str = "GET", body: dict | None = None,
             headers: dict | None = None, timeout: int = 60, accept: str = "application/json") -> bytes:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", accept)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def http_json(url: str, **kw):
    """Fetch JSON. Raises urllib.error.HTTPError / URLError / ValueError."""
    return json.loads(_request(url, **kw).decode("utf-8"))


def http_text(url: str, **kw) -> str:
    kw.setdefault("accept", "application/rss+xml, application/atom+xml, application/xml, text/xml, */*")
    return _request(url, **kw).decode("utf-8", "replace")


def get_with_retries(fetch, what: str, attempts: int = 3):
    """Call fetch(); retry on 429/5xx/network errors; a 404 fails immediately."""
    last: Exception | None = None
    for i in range(attempts):
        try:
            return fetch()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"{what} not found (HTTP 404)") from None
            if e.code != 429 and e.code < 500:
                raise RuntimeError(f"{what} refused the request (HTTP {e.code})") from None
            last = e
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last = e
        if i + 1 < attempts:
            time.sleep(3 * (i + 1))
    raise RuntimeError(f"{what} failed: {last}")


def strip_html(text: str) -> str:
    # Greenhouse double-escapes its HTML, so unescape before and after.
    text = html.unescape(text or "")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<(br|p|li|div|h\d)[^>]*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    return re.sub(r"\s*\n\s*", "\n", text).strip()


def norm_name(name: str) -> str:
    """'Acme Robotics, Inc.' -> 'acmerobotics' (for duplicate checks)."""
    n = (name or "").lower()
    n = re.sub(r"\b(inc|llc|ltd|corp|corporation|co|company|the|technologies|technology|labs?|hq)\b\.?", " ", n)
    return re.sub(r"[^a-z0-9]", "", n)


def today_pacific() -> str:
    return datetime.now(PACIFIC).date().isoformat()


# --------------------------------------------------------------------------- #
# Jobs and company boards
# --------------------------------------------------------------------------- #

@dataclass
class Job:
    uid: str
    company: str
    title: str
    url: str
    location: str
    workplace: str          # "remote" / "hybrid" / "onsite" / "" when unknown
    description: str
    source: str = ""        # shown in the email, e.g. "Remotive"
    source_url: str = ""    # link for the source label (attribution)
    kind: str = "board"     # "board" = a company in companies.yaml, "aggregator" otherwise
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Job":
        return cls(**{k: d.get(k, v) for k, v in asdict(cls("", "", "", "", "", "", "")).items()})

    def dedupe_key(self) -> str:
        return f"ct:{norm_name(self.company)}|{re.sub(r'[^a-z0-9]', '', self.title.lower())}"


def fetch_board(company: dict) -> list[Job]:
    platform, slug, name = company["platform"], company["slug"], company["name"]
    if platform not in BOARD_URLS:
        raise ValueError(f"unknown platform '{platform}' (use one of: {', '.join(BOARD_URLS)})")
    what = f"{platform} board '{slug}'"
    if platform == "smartrecruiters":
        jobs = _fetch_smartrecruiters(name, slug, what)
    else:
        url = BOARD_URLS[platform].format(slug=urllib.parse.quote(slug))
        data = get_with_retries(lambda: http_json(url, timeout=90), what)
        parse = {"greenhouse": _parse_greenhouse, "lever": _parse_lever, "ashby": _parse_ashby,
                 "workable": _parse_workable}[platform]
        jobs = parse(data, name, slug)
    label = f"{name} careers ({PLATFORM_LABELS[platform]})"
    for j in jobs:
        j.source, j.kind = label, "board"
    return jobs


def _parse_greenhouse(data, name, slug) -> list[Job]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("unexpected Greenhouse response shape")
    jobs = []
    for j in data["jobs"]:
        loc = (j.get("location") or {}).get("name") or ""
        offices = ", ".join(o.get("name", "") for o in j.get("offices") or [] if o.get("name"))
        jobs.append(Job(
            uid=f"greenhouse:{slug}:{j.get('id')}",
            company=name,
            title=(j.get("title") or "").strip(),
            url=j.get("absolute_url") or "",
            location=loc if loc else offices,
            workplace="",
            description=strip_html(j.get("content") or ""),
            extra={"offices": offices},
        ))
    return jobs


def _parse_lever(data, name, slug) -> list[Job]:
    if not isinstance(data, list):
        raise ValueError("unexpected Lever response shape")
    jobs = []
    for j in data:
        cats = j.get("categories") or {}
        locs = cats.get("allLocations") or ([cats["location"]] if cats.get("location") else [])
        desc_parts = [j.get("descriptionPlain") or ""]
        for lst in j.get("lists") or []:
            desc_parts.append(f"{lst.get('text', '')}: {strip_html(lst.get('content', ''))}")
        desc_parts.append(j.get("additionalPlain") or "")
        wt = (j.get("workplaceType") or "").lower()
        jobs.append(Job(
            uid=f"lever:{slug}:{j.get('id')}",
            company=name,
            title=(j.get("text") or "").strip(),
            url=j.get("hostedUrl") or j.get("applyUrl") or "",
            location="; ".join(locs),
            workplace={"on-site": "onsite"}.get(wt, wt if wt in ("remote", "hybrid", "onsite") else ""),
            description=re.sub(r"\s+", " ", " ".join(desc_parts)).strip(),
            extra={"country": j.get("country") or ""},
        ))
    return jobs


def _parse_ashby(data, name, slug) -> list[Job]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("unexpected Ashby response shape")
    jobs = []
    for j in data["jobs"]:
        if j.get("isListed") is False:
            continue
        locs = [j.get("location") or ""]
        locs += [s.get("location", "") for s in j.get("secondaryLocations") or []]
        wt = (j.get("workplaceType") or "").lower().replace("-", "")
        if j.get("isRemote") and wt != "hybrid":
            wt = "remote"
        country = (((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry")) or ""
        jobs.append(Job(
            uid=f"ashby:{slug}:{j.get('id')}",
            company=name,
            title=(j.get("title") or "").strip(),
            url=j.get("jobUrl") or j.get("applyUrl") or "",
            location="; ".join(l for l in locs if l),
            workplace=wt if wt in ("remote", "hybrid", "onsite") else "",
            description=(j.get("descriptionPlain") or strip_html(j.get("descriptionHtml") or "")).strip(),
            extra={"country": country},
        ))
    return jobs


def _parse_workable(data, name, slug) -> list[Job]:
    if not isinstance(data, dict) or not isinstance(data.get("jobs"), list):
        raise ValueError("unexpected Workable response shape")
    jobs = []
    for j in data["jobs"]:
        locs = []
        for l in j.get("locations") or [{"city": j.get("city"), "region": j.get("state"), "country": j.get("country")}]:
            locs.append(", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x))
        codes = {(l.get("countryCode") or "").upper() for l in j.get("locations") or []} - {""}
        jobs.append(Job(
            uid=f"workable:{slug}:{j.get('shortcode')}",
            company=name,
            title=(j.get("title") or "").strip(),
            url=j.get("url") or j.get("shortlink") or "",
            location="; ".join(l for l in locs if l),
            workplace="remote" if j.get("telecommuting") else "",
            description=strip_html(j.get("description") or ""),
            extra={"country": "US" if "US" in codes else (sorted(codes)[0] if len(codes) == 1 else ""),
                   "board_name": data.get("name") or ""},
        ))
    return jobs


def _fetch_smartrecruiters(name, slug, what) -> list[Job]:
    """The list API has no descriptions; fill_details() fetches them later, only
    for the few jobs that survive the keyword filter."""
    jobs = []
    for page in range(SMARTRECRUITERS_MAX_PAGES):
        url = BOARD_URLS["smartrecruiters"].format(slug=urllib.parse.quote(slug), offset=page * 100)
        data = get_with_retries(lambda: http_json(url, timeout=60), what)
        if not isinstance(data, dict) or not isinstance(data.get("content"), list):
            raise ValueError("unexpected SmartRecruiters response shape")
        for j in data["content"]:
            loc = j.get("location") or {}
            workplace = "remote" if loc.get("remote") else "hybrid" if loc.get("hybrid") else "onsite"
            jobs.append(Job(
                uid=f"smartrecruiters:{slug}:{j.get('id')}",
                company=name,
                title=(j.get("name") or "").strip(),
                url=f"https://jobs.smartrecruiters.com/{slug}/{j.get('id')}",
                location=loc.get("fullLocation") or "",
                workplace=workplace,
                description="",
                extra={"country": (loc.get("country") or "").upper(),
                       "board_name": (j.get("company") or {}).get("name") or "",
                       "detail_url": f"https://api.smartrecruiters.com/v1/companies/{urllib.parse.quote(slug)}/postings/{j.get('id')}"},
            ))
        if len(data["content"]) < 100 or len(jobs) >= int(data.get("totalFound") or 0):
            break
    return jobs


def fill_details(jobs: list[Job], limit: int = 80) -> None:
    """Fetch full descriptions for jobs whose board only lists titles (SmartRecruiters)."""
    for j in [j for j in jobs if j.extra.get("detail_url") and not j.description][:limit]:
        try:
            d = get_with_retries(lambda: http_json(j.extra["detail_url"], timeout=60), "job details", attempts=2)
            sections = ((d.get("jobAd") or {}).get("sections") or {})
            j.description = "\n".join(strip_html((sections.get(k) or {}).get("text") or "")
                                      for k in ("jobDescription", "qualifications", "additionalInformation",
                                                "companyDescription")).strip()
            j.url = d.get("postingUrl") or j.url
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.3)


SLUG_SUFFIXES = ("inc", "hq", "ai", "labs", "technologies", "tech", "industries")


def slug_candidates(name: str, website: str = "", quick: bool = False) -> list[str]:
    """Likely board slugs for a company, most likely first. quick=True skips the
    long tail of suffix guesses ("acmeinc", "acmelabs"...), for bulk lookups."""
    raw = (name or "").lower()
    base = re.sub(r"[^a-z0-9]", "", raw)
    hyph = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    core = norm_name(name)
    out = [base, hyph, core]
    host = urllib.parse.urlparse(website if "//" in (website or "") else f"//{website}").hostname or ""
    host = re.sub(r"^www\.", "", host)
    if host:
        parts = host.split(".")
        out.append(re.sub(r"[^a-z0-9]", "", parts[0]))
        if len(parts) > 2 or parts[-1] not in ("com", "org", "net", "co", "us"):
            out.append(re.sub(r"[^a-z0-9]", "", "".join(parts[:-1])) + parts[-1])  # hubble.network -> hubblenetwork
    if not quick:
        out += [core + s for s in SLUG_SUFFIXES]
    # SmartRecruiters ids are often CamelCase, e.g. "BoschGroup".
    words = re.findall(r"[A-Za-z0-9]+", name or "")
    if len(words) > 1:
        out.append("".join(w[:1].upper() + w[1:] for w in words))
    return [s for s in dict.fromkeys(out) if len(s) >= 2]


def board_matches_company(platform: str, slug: str, jobs: list[Job], name: str) -> bool:
    """Guard against a slug like 'atlas' belonging to a different company."""
    target = norm_name(name)
    if not target:
        return False
    board = norm_name(next((j.extra.get("board_name") for j in jobs if j.extra.get("board_name")), ""))
    if board:
        return board in target or target in board
    if platform == "greenhouse":
        try:
            info = http_json(f"https://boards-api.greenhouse.io/v1/boards/{urllib.parse.quote(slug)}", timeout=30)
            board = norm_name(info.get("name", ""))
            if board and (board in target or target in board):
                return True
        except Exception:  # noqa: BLE001
            pass
    if slug.replace("-", "") == target and len(target) >= 8:
        return True
    needle = re.compile(re.escape(name.strip()), re.I)
    return any(needle.search(j.description[:5000]) or needle.search(j.title) for j in jobs[:25])


def find_board(name: str, website: str = "", verify: bool = True, pause: float = 0.3,
               extra_slugs: tuple = (), quick: bool = False):
    """Try likely slugs on every platform. Returns (platform, slug, jobs) or None."""
    slugs = list(dict.fromkeys([s for s in extra_slugs if s] + slug_candidates(name, website, quick)))
    for slug in slugs:
        for platform in BOARD_URLS:
            try:
                jobs = fetch_board({"name": name, "platform": platform, "slug": slug})
            except Exception:  # noqa: BLE001
                jobs = None
            time.sleep(pause)
            if not jobs:
                continue
            if not verify or board_matches_company(platform, slug, jobs, name):
                return platform, slug, jobs
    return None


# --------------------------------------------------------------------------- #
# Cheap pre-filter (no AI)
# --------------------------------------------------------------------------- #

ENGINEERING_TITLE = re.compile(
    r"\b(engineer|engineers|engineering|developer|developers|swe|sde|scientist|scientists)\b", re.I)
PROGRAM_OR_PROJECT = re.compile(r"\b(program|programme|project)s?\b", re.I)
REMOTE_WORD = re.compile(r"\bremote(ly)?\b|\bwork from home\b|\bwfh\b|\bdistributed\b", re.I)
HYBRID_OR_ONSITE = re.compile(r"\bhybrid\b|\bon-?site\b|\bin[- ]office\b|\bin[- ]person\b", re.I)
US_HINT = re.compile(
    r"\b(?i:united states|america|americas|nationwide|anywhere in the us)\b|\bU\.?S\.?A?\b|"
    r"\b(AL|AK|AZ|AR|CA|CO|CT|DE|DC|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|"
    r"NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)\b|"
    r"\b(?i:california|texas|new york|washington|colorado|virginia|massachusetts|florida|illinois|"
    r"georgia|arizona|oregon|utah|maryland|north carolina)\b")
# Phrases where "remote" is about the technology, not where you work.
REMOTE_TECH = re.compile(
    r"\bremote(ly)?[- ](sensing|sensed|piloted|operated|weapons?|control(led)?|access|"
    r"monitoring|systems?|vehicles?|operations)\b", re.I)
NON_US = re.compile(
    r"\b(uk|united kingdom|england|london|scotland|ireland|dublin|canada|toronto|vancouver|montreal|"
    r"india|bangalore|bengaluru|hyderabad|pune|germany|berlin|munich|france|paris|spain|madrid|"
    r"netherlands|amsterdam|poland|warsaw|israel|tel aviv|australia|sydney|melbourne|japan|tokyo|"
    r"singapore|korea|seoul|taiwan|brazil|mexico|argentina|switzerland|zurich|sweden|stockholm|"
    r"denmark|norway|finland|italy|romania|ukraine|portugal|lisbon|emea|apac|latam|europe|"
    r"philippines|vietnam|turkey|estonia|south africa|nigeria|kenya|pakistan|colombia)\b", re.I)


def prefilter(job: Job, settings: dict) -> str | None:
    """Return a short reason to drop the job, or None to keep it for the AI."""
    title = job.title
    if not title:
        return "no title"
    if ENGINEERING_TITLE.search(title) and not PROGRAM_OR_PROJECT.search(title):
        return "engineering/science title"

    # Your own target titles always count, even if a word in them looks senior
    # ("chief" in "Chief of Staff"). Anything else must be mid-level.
    low = title.lower()
    target = next((t for t in (x.lower().strip() for x in settings.get("my_target_titles") or [])
                   if t and re.search(r"\b" + re.escape(t) + r"\b", low)), None)
    rest = low.replace(target, " ") if target else low
    for w in (x.lower().strip() for x in settings.get("too_senior_title_words") or []):
        if w and re.search(r"\b" + re.escape(w) + r"\b", rest):
            return "too senior"

    if job.kind == "aggregator" and not target:
        words = [w.lower() for w in settings.get("job_board_title_keywords") or []]
        if words and not any(re.search(r"\b" + re.escape(w) + r"\b", low) for w in words):
            return "job-board title not in your target list"

    loc = job.location or ""
    if job.workplace in ("onsite", "hybrid"):
        return f"listed as {job.workplace}"
    # Startup-list boards: "remote" buried in a description is usually boilerplate,
    # so the job itself must be marked remote, or say so in its title/location.
    if job.extra.get("sweep") and job.workplace != "remote" and not REMOTE_WORD.search(f"{title} {loc}"):
        return "startup job not listed as remote"
    if job.workplace != "remote":
        if HYBRID_OR_ONSITE.search(loc) and not REMOTE_WORD.search(loc):
            return "location says onsite/hybrid"
        if settings.get("require_remote_mention", True):
            haystack = REMOTE_TECH.sub(" ", f"{title} {loc} {job.description}")
            if not REMOTE_WORD.search(haystack):
                return "no mention of remote anywhere"

    if job.extra.get("non_us"):
        return "remote, but not open to the US"
    country = (job.extra.get("country") or "").upper()
    if country and country not in ("US", "USA", "UNITED STATES"):
        if not US_HINT.search(loc):
            return f"based outside the US ({country})"
    if NON_US.search(loc) and not US_HINT.search(loc):
        return "location outside the US"
    return None


TARGET_WORDS = re.compile(
    r"program|project|operations|strategy|analyst|product owner|chief of staff|special projects|"
    r"implementation|process|delivery|r&d|research|quantum|space|satellite|energy|fusion", re.I)


def priority(job: Job) -> tuple:
    """Most promising first, so they get the AI's limited daily calls. Company boards win ties."""
    return (-len(TARGET_WORDS.findall(job.title)), job.kind != "board")


# --------------------------------------------------------------------------- #
# Gemini
# --------------------------------------------------------------------------- #

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


class QuotaExhausted(Exception):
    pass


class Gemini:
    """Tiny Gemini REST client with a per-run call budget and free-tier handling."""

    def __init__(self, api_key: str, settings: dict, max_calls: int | None = None):
        self.api_key = api_key
        self.settings = settings
        self.models = [m for m in (settings["gemini_model"], settings.get("fallback_model")) if m]
        self.model_idx = 0
        self.calls_made = 0        # requests Google counted (answers and 4xx), not 5xx/network failures
        self.max_calls = max_calls if max_calls is not None else int(settings["max_ai_calls_per_run"])
        self._last_call = 0.0

    @property
    def model(self) -> str:
        return self.models[self.model_idx]

    @property
    def calls_left(self) -> int:
        return max(0, self.max_calls - self.calls_made)

    def ask_json(self, system: str, prompt: str):
        """Send one prompt and return the parsed JSON reply."""
        if self.calls_left <= 0:
            raise QuotaExhausted(f"used this run's budget of {self.max_calls} AI calls")
        text = self._call(system, prompt)
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
        return json.loads(text)

    def _call(self, system: str, prompt: str) -> str:
        wait = float(self.settings["seconds_between_ai_calls"]) - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)
        body = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        }
        attempts = 0
        while True:
            attempts += 1
            self._last_call = time.time()
            try:
                resp = http_json(GEMINI_URL.format(model=self.model), method="POST", body=body,
                                 headers={"x-goog-api-key": self.api_key}, timeout=180)
                self.calls_made += 1
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code < 500:
                    self.calls_made += 1  # Google counts these; overload errors (5xx) don't use quota
                if e.code == 429:
                    if "PerDay" in detail or "per day" in detail.lower():
                        if self._next_model(f"daily free quota used up on {self.model}"):
                            continue
                        raise QuotaExhausted("Gemini's daily free-tier quota is used up") from None
                    if attempts <= 4:
                        delay = _retry_delay(detail, default=30 * attempts)
                        log(f"    Gemini rate limit hit, waiting {delay:.0f}s...")
                        time.sleep(delay)
                        continue
                    raise QuotaExhausted("Gemini kept rate-limiting (429)") from None
                if e.code == 404 and self._next_model(f"model {self.model} not found"):
                    continue
                if e.code >= 500:
                    # "Model is overloaded": retry once, then move to the lighter backup model,
                    # which is usually less busy, and stay on it for the rest of the run.
                    if attempts == 1:
                        log(f"    Gemini ({self.model}) is busy (HTTP {e.code}); retrying in 15s...")
                        time.sleep(15)
                        continue
                    if self._next_model(f"{self.model} is overloaded (HTTP {e.code})"):
                        attempts = 0
                        continue
                    if attempts <= 3:
                        time.sleep(30)
                        continue
                    raise RuntimeError(f"Gemini is overloaded right now (HTTP {e.code}); will retry next run") from None
                raise RuntimeError(f"Gemini HTTP {e.code}: {detail[:300]}") from None
            except (urllib.error.URLError, TimeoutError) as e:
                if attempts <= 3:
                    time.sleep(10 * attempts)
                    continue
                raise RuntimeError(f"Gemini network error: {e}") from None

            parts = (((resp.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
            text = "".join(p.get("text", "") for p in parts if not p.get("thought"))
            if not text:
                reason = (resp.get("candidates") or [{}])[0].get("finishReason") or resp.get("promptFeedback")
                raise RuntimeError(f"Gemini returned no text ({reason})")
            return text

    def _next_model(self, why: str) -> bool:
        if self.model_idx + 1 < len(self.models):
            log(f"    {why}; switching to {self.models[self.model_idx + 1]}")
            self.model_idx += 1
            return True
        return False


def _retry_delay(detail: str, default: float) -> float:
    m = re.search(r'"retryDelay":\s*"(\d+(?:\.\d+)?)s"', detail)
    return min(float(m.group(1)) + 2, 120) if m else default


def as_list(data, *keys) -> list:
    """Gemini sometimes wraps a list in {"jobs": [...]}; unwrap it."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for k in keys + ("results", "items", "data"):
            if isinstance(data.get(k), list):
                return data[k]
        return [data]
    return []


# --------------------------------------------------------------------------- #
# State files
# --------------------------------------------------------------------------- #

def load_json_state(path: Path, default: dict) -> dict:
    if not path.exists():
        return copy.deepcopy(default)
    try:
        data = json.loads(path.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        log(f"  ! {path.name} was unreadable; starting a fresh one")
        return copy.deepcopy(default)
    if not isinstance(data, dict):
        data = {}
    for k, v in default.items():
        data.setdefault(k, copy.deepcopy(v))
    return data


def save_json_state(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def prune_dated(d: dict, days: int) -> dict:
    """Drop {key: 'YYYY-MM-DD'} entries older than `days`."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()
    return {k: v for k, v in sorted(d.items()) if not isinstance(v, str) or v >= cutoff}


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #

def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"].strip()
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
    recipients = [a.strip() for a in (os.environ.get("TO_EMAIL") or sender).split(",") if a.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Job Alerts <{sender}>"
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText("Your email app doesn't show HTML. Open this message in Gmail to read it.", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(sender, password)
        s.sendmail(sender, recipients, msg.as_string())


def email_shell(heading: str, subheading: str, body_html: str, footer_html: str = "") -> str:
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f6f6f6;">
<div style="max-width:640px;margin:0 auto;padding:24px 20px;background:#fff;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.45;color:#222;">
<h2 style="margin:0 0 4px;font-size:20px;">{heading}</h2>
<div style="color:#666;font-size:13px;">{subheading}</div>
{body_html}
<div style="color:#999;font-size:12px;margin-top:24px;">{footer_html}</div>
</div></body></html>"""


def missing_secrets(names: tuple[str, ...]) -> list[str]:
    return [k for k in names if not os.environ.get(k, "").strip()]
