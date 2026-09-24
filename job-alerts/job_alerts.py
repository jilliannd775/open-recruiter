"""Daily AI job alerts, built to run on GitHub Actions.

What one run does, in order:
  1. Reads companies.yaml and pulls every open job from each company's public
     Greenhouse / Lever / Ashby board. A board that fails is skipped and noted.
  2. Drops jobs we have already scored (seen_jobs.json) and jobs a cheap
     keyword check can rule out: engineering titles, onsite, hybrid, non-US.
  3. Sends what is left to Gemini in batches and gets back a 0-100 score, a
     one-sentence reason and the remote status for each job.
  4. Emails one digest of every job at or above the score threshold.
  5. Saves the scored job IDs to seen_jobs.json (the workflow commits it back).

Usage:
  python job_alerts.py            # normal run (what the daily schedule does)
  python job_alerts.py --check    # only test every board in companies.yaml
  python job_alerts.py --dry-run  # everything except sending email / saving
  python job_alerts.py --scheduled  # like a normal run, but skips itself if it
                                    # is not yet 7am Pacific or already ran today

Only dependency outside the standard library: PyYAML.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
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

PACIFIC = ZoneInfo("America/Los_Angeles")
SEND_HOUR_PACIFIC = 7

BOARD_URLS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
}

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
}

USER_AGENT = "job-alerts/1.0 (+https://github.com/features/actions)"


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #

def log(msg: str) -> None:
    print(msg, flush=True)


def load_yaml(path: Path, default):
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return default if data is None else data


def load_settings() -> dict:
    settings = dict(DEFAULT_SETTINGS)
    settings.update(load_yaml(SETTINGS_FILE, {}) or {})
    return settings


def load_companies() -> list[dict]:
    data = load_yaml(COMPANIES_FILE, {})
    companies = data.get("companies", []) if isinstance(data, dict) else data
    cleaned = []
    for c in companies or []:
        if not isinstance(c, dict) or not c.get("platform") or not c.get("slug"):
            log(f"  ! Skipping a malformed entry in companies.yaml: {c!r}")
            continue
        cleaned.append({
            "name": str(c.get("name") or c["slug"]),
            "platform": str(c["platform"]).strip().lower(),
            "slug": str(c["slug"]).strip(),
        })
    return cleaned


def http_json(url: str, *, method: str = "GET", body: dict | None = None,
              headers: dict | None = None, timeout: int = 60):
    """Fetch JSON. Raises urllib.error.HTTPError / URLError / ValueError."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("User-Agent", USER_AGENT)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/json")
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def strip_html(text: str) -> str:
    # Greenhouse double-escapes its HTML, so unescape before and after.
    text = html.unescape(text or "")
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


# --------------------------------------------------------------------------- #
# Fetching jobs
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
    extra: dict = field(default_factory=dict)


def fetch_board(company: dict) -> list[Job]:
    platform, slug, name = company["platform"], company["slug"], company["name"]
    if platform not in BOARD_URLS:
        raise ValueError(f"unknown platform '{platform}' (use greenhouse, lever or ashby)")
    url = BOARD_URLS[platform].format(slug=urllib.parse.quote(slug))

    last_err: Exception | None = None
    for attempt in range(3):
        try:
            data = http_json(url, timeout=60)
            break
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise ValueError(f"board '{slug}' not found on {platform} (HTTP 404)") from None
            last_err = e
            if e.code not in (429,) and e.code < 500:
                raise
        except (urllib.error.URLError, TimeoutError, ValueError) as e:
            last_err = e
        time.sleep(2 * (attempt + 1))
    else:
        raise RuntimeError(f"{platform} board '{slug}' failed: {last_err}")

    if platform == "greenhouse":
        return _parse_greenhouse(data, name, slug)
    if platform == "lever":
        return _parse_lever(data, name, slug)
    return _parse_ashby(data, name, slug)


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


# --------------------------------------------------------------------------- #
# Cheap pre-filter (no AI)
# --------------------------------------------------------------------------- #

ENGINEERING_TITLE = re.compile(
    r"\b(engineer|engineers|engineering|developer|developers|swe|sde|scientist|scientists)\b", re.I)
PROGRAM_OR_PROJECT = re.compile(r"\b(program|programme|project)s?\b", re.I)
REMOTE_WORD = re.compile(r"\bremote(ly)?\b|\bwork from home\b|\bwfh\b|\bdistributed\b", re.I)
HYBRID_OR_ONSITE = re.compile(r"\bhybrid\b|\bon-?site\b|\bin[- ]office\b|\bin[- ]person\b", re.I)
US_HINT = re.compile(
    r"\b(?i:united states|america|nationwide|anywhere in the us)\b|\bU\.?S\.?A?\b|"
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
    r"denmark|norway|finland|italy|romania|ukraine|portugal|lisbon|emea|apac|latam|europe)\b", re.I)


def prefilter(job: Job, settings: dict) -> str | None:
    """Return a short reason to drop the job, or None to keep it for the AI."""
    title = job.title
    if ENGINEERING_TITLE.search(title) and not PROGRAM_OR_PROJECT.search(title):
        return "engineering/science title"

    loc = job.location or ""
    if job.workplace in ("onsite", "hybrid"):
        return f"listed as {job.workplace}"
    if job.workplace != "remote":
        if HYBRID_OR_ONSITE.search(loc) and not REMOTE_WORD.search(loc):
            return "location says onsite/hybrid"
        if settings.get("require_remote_mention", True):
            haystack = REMOTE_TECH.sub(" ", f"{title} {loc} {job.description}")
            if not REMOTE_WORD.search(haystack):
                return "no mention of remote anywhere"

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


def priority(job: Job) -> int:
    """Rough ordering so the most promising jobs get the AI's limited daily calls first."""
    return -len(TARGET_WORDS.findall(job.title))


# --------------------------------------------------------------------------- #
# Gemini scoring
# --------------------------------------------------------------------------- #

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

SYSTEM_PROMPT = """You are a careful recruiting assistant. You score job postings \
for ONE candidate, whose profile is given below. Be honest and calibrated: most \
jobs should NOT score highly.

Scoring guide:
- 85-100: target title AND fully remote in the US AND strong sector/skills fit.
- 65-84: good fit worth applying to, with at most one soft gap.
- 40-64: partial fit (adjacent title, weak sector match, or remote status unclear).
- 0-39: wrong kind of role (engineering/coding, sales, etc.), onsite/hybrid only, \
or outside the US.
A job that is not fully remote or not open to US-based candidates must score below 40.

Reply with JSON only: a list with one object per job, in the same order, shaped:
{"id": "<the job's id>", "score": <integer 0-100>, "reason": "<one sentence on why \
it fits or doesn't>", "remote": "<one of: Remote (US), Remote (US + other countries), \
Remote (non-US), Hybrid, Onsite, Unclear>"}

CANDIDATE PROFILE:
"""


class QuotaExhausted(Exception):
    pass


class GeminiScorer:
    def __init__(self, api_key: str, settings: dict, profile: str):
        self.api_key = api_key
        self.settings = settings
        self.system = SYSTEM_PROMPT + profile.strip()
        self.models = [m for m in (settings["gemini_model"], settings.get("fallback_model")) if m]
        self.model_idx = 0
        self.calls_made = 0
        self._last_call = 0.0

    @property
    def model(self) -> str:
        return self.models[self.model_idx]

    def _job_block(self, idx: int, job: Job) -> str:
        desc = job.description[: int(self.settings["max_description_chars"])]
        return (f"### Job id: {idx}\nTitle: {job.title}\nCompany: {job.company}\n"
                f"Location: {job.location or 'not listed'}\n"
                f"Workplace type: {job.workplace or 'not listed'}\n"
                f"Description (truncated): {desc}\n")

    def score_batch(self, jobs: list[Job]) -> dict[str, dict]:
        """Returns {job.uid: {"score", "reason", "remote"}}. Raises QuotaExhausted."""
        prompt = "Score each of these jobs for the candidate.\n\n" + "\n".join(
            self._job_block(i + 1, j) for i, j in enumerate(jobs))
        text = self._call(prompt)
        results = self._parse(text)
        out = {}
        for i, job in enumerate(jobs):
            r = results.get(str(i + 1))
            if r is not None:
                out[job.uid] = r
        return out

    def _parse(self, text: str) -> dict[str, dict]:
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        data = json.loads(text)
        if isinstance(data, dict):
            data = data.get("jobs") or data.get("results") or [data]
        out = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                score = max(0, min(100, int(round(float(item.get("score", 0))))))
            except (TypeError, ValueError):
                continue
            out[str(item.get("id")).strip().lstrip("#")] = {
                "score": score,
                "reason": str(item.get("reason") or "").strip(),
                "remote": str(item.get("remote") or "Unclear").strip(),
            }
        return out

    def _call(self, prompt: str) -> str:
        wait = float(self.settings["seconds_between_ai_calls"]) - (time.time() - self._last_call)
        if wait > 0:
            time.sleep(wait)

        body = {
            "systemInstruction": {"parts": [{"text": self.system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"responseMimeType": "application/json", "temperature": 0.2},
        }
        attempts = 0
        while True:
            attempts += 1
            self._last_call = time.time()
            self.calls_made += 1
            try:
                resp = http_json(GEMINI_URL.format(model=self.model), method="POST", body=body,
                                 headers={"x-goog-api-key": self.api_key}, timeout=180)
            except urllib.error.HTTPError as e:
                detail = e.read().decode("utf-8", "replace")
                if e.code == 429:
                    if "PerDay" in detail or "per day" in detail.lower():
                        if self._next_model(f"daily free quota used up on {self.model}"):
                            continue
                        raise QuotaExhausted("Gemini daily free-tier quota is used up") from None
                    if attempts <= 4:
                        delay = _retry_delay(detail, default=30 * attempts)
                        log(f"    Gemini rate limit hit, waiting {delay:.0f}s...")
                        time.sleep(delay)
                        continue
                    raise QuotaExhausted("Gemini kept rate-limiting (429)") from None
                if e.code == 404 and self._next_model(f"model {self.model} not found"):
                    continue
                if e.code >= 500 and attempts <= 3:
                    time.sleep(10 * attempts)
                    continue
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


# --------------------------------------------------------------------------- #
# Seen-jobs memory
# --------------------------------------------------------------------------- #

def load_seen() -> dict:
    if not SEEN_FILE.exists():
        return {"last_run_date": None, "jobs": {}}
    try:
        data = json.loads(SEEN_FILE.read_text(encoding="utf-8") or "{}")
    except json.JSONDecodeError:
        log("  ! seen_jobs.json was unreadable; starting a fresh one")
        return {"last_run_date": None, "jobs": {}}
    if isinstance(data, list):  # tolerate a plain list of IDs
        data = {"jobs": {uid: None for uid in data}}
    data.setdefault("last_run_date", None)
    data.setdefault("jobs", {})
    return data


def save_seen(seen: dict, settings: dict) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=int(settings["forget_seen_jobs_after_days"]))).date().isoformat()
    seen["jobs"] = {k: v for k, v in sorted(seen["jobs"].items()) if not v or v >= cutoff}
    SEEN_FILE.write_text(json.dumps(seen, indent=1, sort_keys=True) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #

def score_color(score: int) -> str:
    return "#1a7f37" if score >= 85 else "#2f6fb0" if score >= 75 else "#8a6d00"


def build_email(matches: list[tuple[Job, dict]], notes: list[str], stats: dict, threshold: int) -> str:
    esc = html.escape
    rows = []
    for job, r in matches:
        rows.append(f"""
<tr><td style="padding:14px 0;border-bottom:1px solid #e5e5e5;">
  <div style="font-size:16px;font-weight:600;"><a href="{esc(job.url)}" style="color:#0b57d0;text-decoration:none;">{esc(job.title)}</a></div>
  <div style="color:#444;margin-top:2px;">{esc(job.company)} &middot; {esc(r['remote'])}{' &middot; ' + esc(job.location) if job.location else ''}</div>
  <div style="margin-top:6px;"><span style="display:inline-block;background:{score_color(r['score'])};color:#fff;border-radius:10px;padding:1px 8px;font-size:13px;font-weight:600;">{r['score']}</span>
  <span style="color:#222;">{esc(r['reason'])}</span></div>
  <div style="margin-top:6px;"><a href="{esc(job.url)}" style="color:#0b57d0;">Apply &rarr;</a></div>
</td></tr>""")
    notes_html = ""
    if notes:
        notes_html = ("<p style='margin-top:24px;color:#8a1c1c;font-size:13px;'><b>Problems this run</b></p>"
                      "<ul style='color:#8a1c1c;font-size:13px;'>"
                      + "".join(f"<li>{esc(n)}</li>" for n in notes) + "</ul>")
    return f"""<!doctype html><html><body style="margin:0;padding:0;background:#f6f6f6;">
<div style="max-width:640px;margin:0 auto;padding:24px 20px;background:#fff;font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;font-size:14px;line-height:1.45;color:#222;">
<h2 style="margin:0 0 4px;font-size:20px;">{len(matches)} new job match{'es' if len(matches) != 1 else ''}</h2>
<div style="color:#666;font-size:13px;">Scored {threshold}+ out of 100 &middot; {stats['scored']} new jobs scored today from {stats['companies_ok']} compan{'ies' if stats['companies_ok'] != 1 else 'y'}</div>
<table style="width:100%;border-collapse:collapse;margin-top:12px;">{''.join(rows)}</table>
{notes_html}
<p style="color:#999;font-size:12px;margin-top:24px;">Sent by your job-alerts GitHub Action.</p>
</div></body></html>"""


def send_email(subject: str, html_body: str) -> None:
    sender = os.environ["GMAIL_ADDRESS"].strip()
    password = os.environ["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
    recipients = [a.strip() for a in os.environ.get("TO_EMAIL", sender).split(",") if a.strip()]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = f"Job Alerts <{sender}>"
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText("Your email app doesn't show HTML. Open this message in Gmail to see your job matches.", "plain"))
    msg.attach(MIMEText(html_body, "html"))
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=60) as s:
        s.login(sender, password)
        s.sendmail(sender, recipients, msg.as_string())


# --------------------------------------------------------------------------- #
# Main flows
# --------------------------------------------------------------------------- #

SLUG_SUFFIXES = ("", "inc", "hq", "ai", "labs", "industries", "technologies", "tech", "careers", "jobs")


def check_boards(probe_names: list[str]) -> int:
    """Test every company in companies.yaml; for failures, look for the right slug."""
    companies = load_companies()
    settings = load_settings()
    failed = 0
    log(f"Checking {len(companies)} companies from companies.yaml\n")
    for c in companies:
        try:
            jobs = fetch_board(c)
            passing = [j for j in jobs if not prefilter(j, settings)]
            log(f"  OK    {c['name']:<28} {c['platform']:<10} {c['slug']:<24} {len(jobs)} open jobs, "
                f"{len(passing)} pass the keyword filter")
            for j in passing[:15]:
                log(f"          - {j.title} [{j.workplace or '?'}] {j.location[:60]}")
            if not jobs:
                log("        (board exists but has 0 jobs right now)")
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"  FAIL  {c['name']:<28} {c['platform']:<10} {c['slug']:<24} {e}")
            probe_names.append(c["name"])
    if probe_names:
        log("\nSearching for boards by name (this tries common slug spellings on all 3 platforms):")
        for name in dict.fromkeys(probe_names):
            probe(name)
    return 1 if failed else 0


def probe(name: str) -> None:
    base = re.sub(r"[^a-z0-9]", "", name.lower())
    hyph = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    slugs = list(dict.fromkeys([base, hyph] + [base + s for s in SLUG_SUFFIXES[1:]]))
    found = []
    for platform in BOARD_URLS:
        for slug in slugs:
            try:
                jobs = fetch_board({"name": name, "platform": platform, "slug": slug})
            except Exception:  # noqa: BLE001
                continue
            found.append((platform, slug, len(jobs)))
    if found:
        for platform, slug, n in found:
            log(f"  FOUND {name:<28} platform: {platform:<10} slug: {slug:<24} {n} open jobs")
    else:
        log(f"  NONE  {name:<28} not on Greenhouse, Lever or Ashby under any common slug")


def should_skip_scheduled(seen: dict) -> str | None:
    now = datetime.now(PACIFIC)
    if now.hour < SEND_HOUR_PACIFIC:
        return f"it is {now:%H:%M} Pacific, before {SEND_HOUR_PACIFIC}am"
    if seen.get("last_run_date") == now.date().isoformat():
        return "already ran today"
    return None


def run(dry_run: bool, scheduled: bool) -> int:
    settings = load_settings()
    seen = load_seen()
    if scheduled:
        skip = should_skip_scheduled(seen)
        if skip:
            log(f"Skipping this scheduled run: {skip}.")
            return 0

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    missing = [k for k in ("GEMINI_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD")
               if not os.environ.get(k, "").strip()]
    if dry_run:
        missing = [k for k in missing if k == "GEMINI_API_KEY"]
    if missing:
        log(f"ERROR: these GitHub secrets are missing or empty: {', '.join(missing)}. "
            "See the README, step 'Add your secrets'.")
        return 2

    profile = PROFILE_FILE.read_text(encoding="utf-8")
    threshold = int(settings["score_threshold"])
    notes: list[str] = []
    today = datetime.now(PACIFIC).date().isoformat()

    # 1. Fetch
    companies = load_companies()
    log(f"Fetching jobs from {len(companies)} companies...")
    all_jobs: list[Job] = []
    companies_ok = 0
    for c in companies:
        try:
            jobs = fetch_board(c)
            companies_ok += 1
            log(f"  {c['name']}: {len(jobs)} open jobs")
            all_jobs.extend(jobs)
        except Exception as e:  # noqa: BLE001
            log(f"  {c['name']}: FAILED - {e}")
            notes.append(f"Couldn't read {c['name']}'s job board ({c['platform']}/{c['slug']}): {e}")

    # 2. Dedupe + pre-filter
    unique = {}
    for j in all_jobs:
        unique.setdefault(j.uid, j)
    new_jobs = [j for j in unique.values() if j.uid not in seen["jobs"]]
    drop_counts: dict[str, int] = {}
    candidates = []
    for j in new_jobs:
        why = prefilter(j, settings)
        if why:
            drop_counts[why] = drop_counts.get(why, 0) + 1
        else:
            candidates.append(j)
    log(f"\n{len(unique)} open jobs, {len(new_jobs)} not seen before, "
        f"{len(candidates)} left after the keyword filter.")
    for why, n in sorted(drop_counts.items(), key=lambda x: -x[1]):
        log(f"  dropped {n:>4}: {why}")

    # 3. Score with Gemini, most promising titles first, within the daily budget
    candidates.sort(key=priority)
    batch_size = max(1, int(settings["jobs_per_ai_call"]))
    max_calls = max(1, int(settings["max_ai_calls_per_run"]))
    budget = batch_size * max_calls
    if len(candidates) > budget:
        notes.append(f"{len(candidates) - budget} jobs were left for tomorrow to stay inside "
                     f"the free AI limit ({max_calls} AI calls per day).")
    to_score = candidates[:budget]

    scorer = GeminiScorer(api_key, settings, profile)
    scored: dict[str, dict] = {}
    ai_errors = 0
    for start in range(0, len(to_score), batch_size):
        batch = to_score[start:start + batch_size]
        log(f"  Scoring jobs {start + 1}-{start + len(batch)} of {len(to_score)} with {scorer.model}...")
        try:
            got = scorer.score_batch(batch)
            scored.update(got)
            if len(got) < len(batch):
                log(f"    AI returned {len(got)} of {len(batch)} scores; the rest will retry tomorrow")
        except QuotaExhausted as e:
            left = len(to_score) - start
            log(f"    {e}. {left} jobs will be scored on the next run.")
            notes.append(f"{e}; {left} jobs will be scored on the next run.")
            break
        except Exception as e:  # noqa: BLE001
            ai_errors += 1
            log(f"    AI batch failed: {e}")
            if ai_errors >= 3:
                notes.append(f"The AI scoring kept failing ({e}); unscored jobs will retry tomorrow.")
                break
    else:
        if ai_errors:
            notes.append(f"{ai_errors} AI batch(es) failed; those jobs will retry tomorrow.")

    for uid in scored:
        seen["jobs"][uid] = today

    matches = sorted(
        ((unique[uid], r) for uid, r in scored.items() if r["score"] >= threshold),
        key=lambda x: (-x[1]["score"], x[0].company, x[0].title))
    log(f"\nScored {len(scored)} jobs; {len(matches)} scored {threshold}+.")
    for job, r in matches:
        log(f"  {r['score']:>3}  {job.company} - {job.title}  [{r['remote']}]")

    # 4. Email
    stats = {"scored": len(scored), "companies_ok": companies_ok}
    if matches:
        subject = f"{len(matches)} new job match{'es' if len(matches) != 1 else ''} (top: {matches[0][1]['score']}) - {today}"
        body = build_email(matches, notes, stats, threshold)
        if dry_run:
            out = HERE / "preview_email.html"
            out.write_text(body, encoding="utf-8")
            log(f"\nDry run: not sending. Email preview written to {out.name}")
        else:
            send_email(subject, body)
            log(f"\nEmail sent: {subject}")
    else:
        log("\nNo new matches today, so no email.")
    if notes:
        log("\nProblems this run:\n  - " + "\n  - ".join(notes))

    # 5. Remember
    if not dry_run:
        seen["last_run_date"] = today
        save_seen(seen, settings)

    # Fail loudly (GitHub emails you about a failed run) when nothing worked at all.
    if companies and companies_ok == 0:
        log("ERROR: every company board failed.")
        return 1
    if to_score and not scored:
        log("ERROR: no jobs could be scored by the AI. Check GEMINI_API_KEY.")
        return 1
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="only test the boards in companies.yaml")
    p.add_argument("--probe", nargs="*", default=[], metavar="NAME",
                   help="with --check: also search for these company names on all platforms")
    p.add_argument("--dry-run", action="store_true", help="don't send email or save seen jobs")
    p.add_argument("--scheduled", action="store_true", help="skip unless it's 7am+ Pacific and not yet run today")
    args = p.parse_args()
    if args.check:
        return check_boards(list(args.probe))
    return run(dry_run=args.dry_run, scheduled=args.scheduled)


if __name__ == "__main__":
    sys.exit(main())
