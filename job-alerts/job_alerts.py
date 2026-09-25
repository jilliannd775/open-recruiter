"""Daily AI job alerts, built to run on GitHub Actions.

What one run does, in order:
  1. Collects open jobs from every source switched on in settings.yaml:
     your companies' Greenhouse / Lever / Ashby / Workable / SmartRecruiters
     boards (companies.yaml), Remotive, Remote OK, Himalayas, We Work
     Remotely, and the monthly Hacker News
     "Who is hiring?" thread (Gemini pulls the roles out of each post).
     A source that fails is skipped and noted at the bottom of the email.
  2. Drops jobs already seen (seen_jobs.json), duplicates across sources, and
     jobs a cheap keyword check can rule out: engineering titles, onsite,
     hybrid, non-US, and (for job-board sources) titles outside your targets.
  3. Sends what is left to Gemini in batches for a 0-100 score, a one-sentence
     reason and the remote status.
  4. Emails one digest of every job at or above the score threshold, each
     labelled with where it came from.
  5. Saves what it scored to seen_jobs.json (the workflow commits it back).

Usage:
  python job_alerts.py              # normal run (what the daily schedule does)
  python job_alerts.py --check      # only test companies.yaml and every source
  python job_alerts.py --dry-run    # everything except sending email / saving
  python job_alerts.py --scheduled  # like a normal run, but skips itself if it
                                    # is not yet 7am Pacific or already ran today
"""
from __future__ import annotations

import argparse
import html
import os
import sys
from datetime import datetime

import sources
from common import (HERE, PACIFIC, SEEN_FILE, Gemini, Job, QuotaExhausted, as_list, fetch_board,
                    fill_details, find_board, load_companies, load_json_state, load_profile, load_settings, log,
                    missing_secrets, prefilter, priority, prune_dated, save_json_state, send_email,
                    source_on, email_shell, today_pacific)

SEND_HOUR_PACIFIC = 7

SCORE_SYSTEM = """You are a careful recruiting assistant. You score job postings \
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

EMPTY_SEEN = {"last_run_date": None, "jobs": {}, "hn": {"thread": None, "done": {}, "pending": []}}


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def score_batch(gemini: Gemini, profile: str, jobs: list[Job], max_chars: int) -> dict[str, dict]:
    """Returns {job.uid: {"score", "reason", "remote"}} for one batch."""
    blocks = []
    for i, j in enumerate(jobs, 1):
        blocks.append(f"### Job id: {i}\nTitle: {j.title}\nCompany: {j.company}\n"
                      f"Location: {j.location or 'not listed'}\n"
                      f"Workplace type: {j.workplace or 'not listed'}\n"
                      f"Description (truncated): {j.description[:max_chars]}\n")
    data = gemini.ask_json(SCORE_SYSTEM + profile.strip(),
                           "Score each of these jobs for the candidate.\n\n" + "\n".join(blocks))
    out = {}
    for item in as_list(data, "jobs"):
        if not isinstance(item, dict):
            continue
        try:
            idx = int(str(item.get("id")).strip().lstrip("#"))
            score = max(0, min(100, int(round(float(item.get("score", 0))))))
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= len(jobs):
            out[jobs[idx - 1].uid] = {
                "score": score,
                "reason": str(item.get("reason") or "").strip(),
                "remote": str(item.get("remote") or "Unclear").strip(),
            }
    return out


# --------------------------------------------------------------------------- #
# Email
# --------------------------------------------------------------------------- #

def score_color(score: int) -> str:
    return "#1a7f37" if score >= 85 else "#2f6fb0" if score >= 75 else "#8a6d00"


def build_email(matches: list[tuple[Job, dict]], notes: list[str], stats: dict, threshold: int) -> str:
    esc = html.escape
    rows = []
    for job, r in matches:
        source = (f'<a href="{esc(job.source_url)}" style="color:#666;">{esc(job.source)}</a>'
                  if job.source_url else esc(job.source))
        rows.append(f"""
<tr><td style="padding:14px 0;border-bottom:1px solid #e5e5e5;">
  <div style="font-size:16px;font-weight:600;"><a href="{esc(job.url)}" style="color:#0b57d0;text-decoration:none;">{esc(job.title)}</a></div>
  <div style="color:#444;margin-top:2px;">{esc(job.company)} &middot; {esc(r['remote'])}{' &middot; ' + esc(job.location) if job.location else ''}</div>
  <div style="margin-top:6px;"><span style="display:inline-block;background:{score_color(r['score'])};color:#fff;border-radius:10px;padding:1px 8px;font-size:13px;font-weight:600;">{r['score']}</span>
  <span style="color:#222;">{esc(r['reason'])}</span></div>
  <div style="margin-top:6px;font-size:13px;"><a href="{esc(job.url)}" style="color:#0b57d0;">Apply &rarr;</a>
  <span style="color:#888;"> &nbsp;via {source}</span></div>
</td></tr>""")
    notes_html = ""
    if notes:
        notes_html = ("<p style='margin-top:24px;color:#8a1c1c;font-size:13px;'><b>Problems this run</b></p>"
                      "<ul style='color:#8a1c1c;font-size:13px;'>"
                      + "".join(f"<li>{esc(n)}</li>" for n in notes) + "</ul>")
    used = sorted({j.source for j, _ in matches if j.kind == "aggregator"})
    credits = ""
    if used:
        credits = "Listings from " + ", ".join(
            f'<a href="{esc(sources.SOURCE_HOMES.get(s.split(":")[0], ""))}" style="color:#999;">{esc(s)}</a>'
            for s in used) + ". "
    n = len(matches)
    return email_shell(
        f"{n} new job match{'es' if n != 1 else ''}",
        f"Scored {threshold}+ out of 100 &middot; {stats['scored']} new jobs scored today "
        f"from {stats['sources_ok']} source{'s' if stats['sources_ok'] != 1 else ''}",
        f'<table style="width:100%;border-collapse:collapse;margin-top:12px;">{"".join(rows)}</table>{notes_html}',
        credits + "Sent by your job-alerts GitHub Action.")


# --------------------------------------------------------------------------- #
# Collecting jobs
# --------------------------------------------------------------------------- #

def collect_fixed_sources(settings: dict, notes: list[str]) -> tuple[list[Job], int, int]:
    """Company boards + Remotive + Remote OK + Himalayas. Returns (jobs, sources worked, sources tried)."""
    jobs: list[Job] = []
    ok = tried = 0
    if source_on(settings, "company_boards"):
        companies = load_companies()
        log(f"Company boards ({len(companies)} companies):")
        for c in companies:
            tried += 1
            try:
                got = fetch_board(c)
                ok += 1
                log(f"  {c['name']}: {len(got)} open jobs")
                jobs.extend(got)
            except Exception as e:  # noqa: BLE001
                log(f"  {c['name']}: FAILED - {e}")
                notes.append(f"Couldn't read {c['name']}'s job board ({c['platform']}/{c['slug']}): {e}")
    aggregators = [
        ("remotive", "Remotive", sources.fetch_remotive),
        ("remoteok", "Remote OK", sources.fetch_remoteok),
        ("himalayas", "Himalayas", lambda: sources.fetch_himalayas(settings.get("himalayas_searches") or [])),
        ("weworkremotely", "We Work Remotely",
         lambda: sources.fetch_weworkremotely(settings.get("weworkremotely_feeds") or [])),
    ]
    for key, label, fetch in aggregators:
        if not source_on(settings, key):
            continue
        tried += 1
        try:
            got = fetch()
            ok += 1
            log(f"{label}: {len(got)} jobs")
            jobs.extend(got)
        except Exception as e:  # noqa: BLE001
            log(f"{label}: FAILED - {e}")
            notes.append(f"Couldn't read {label}: {e}")
    return jobs, ok, tried


def collect_hacker_news(settings: dict, seen: dict, gemini: Gemini, notes: list[str]) -> tuple[list[Job], bool]:
    """Roles from this month's HN thread that haven't been processed yet."""
    hn = seen["hn"]
    pending = [Job.from_dict(d) for d in hn.get("pending") or []]
    try:
        thread = sources.latest_hn_thread()
    except Exception as e:  # noqa: BLE001
        log(f"Hacker News: FAILED - {e}")
        notes.append(f"Couldn't read the Hacker News 'Who is hiring?' thread: {e}")
        return pending, False
    if hn.get("thread") != thread["id"]:
        hn["thread"] = thread["id"]
    done = hn.setdefault("done", {})
    today = today_pacific()
    todo = []
    for c in thread["comments"]:
        if c["id"] in done:
            continue
        if sources.hn_worth_extracting(c["text"]):
            todo.append(c)
        else:
            done[c["id"]] = today  # nothing remote + relevant in it; never look again
    log(f"Hacker News ({thread['title']}): {len(thread['comments'])} posts, "
        f"{len(todo)} new ones worth reading, {len(pending)} roles carried over")

    per_call = max(1, int(settings["hacker_news_posts_per_ai_call"]))
    calls = min(int(settings["hacker_news_max_ai_calls"]), gemini.calls_left)
    extracted: list[Job] = []
    for start in range(0, min(len(todo), per_call * calls), per_call):
        batch = todo[start:start + per_call]
        try:
            got = sources.hn_extract(gemini, batch, thread["id"])
        except QuotaExhausted as e:
            notes.append(f"Hacker News: {e}; the rest of the posts wait until tomorrow.")
            break
        except Exception as e:  # noqa: BLE001
            log(f"  HN extraction failed: {e}")
            notes.append(f"Hacker News: reading a batch of posts failed ({e}); it retries tomorrow.")
            continue
        for c in batch:
            done[c["id"]] = today
        extracted.extend(got)
        log(f"  read {len(batch)} posts -> {len(got)} roles")
    left = len(todo) - sum(1 for c in todo if c["id"] in done)
    if left:
        log(f"  {left} HN posts left for the next run (AI budget)")
    return pending + extracted, True


# --------------------------------------------------------------------------- #
# Main flows
# --------------------------------------------------------------------------- #

def should_skip_scheduled(seen: dict) -> str | None:
    now = datetime.now(PACIFIC)
    if now.hour < SEND_HOUR_PACIFIC:
        return f"it is {now:%H:%M} Pacific, before {SEND_HOUR_PACIFIC}am"
    if seen.get("last_run_date") == now.date().isoformat():
        return "already ran today"
    return None


def run(dry_run: bool, scheduled: bool) -> int:
    settings = load_settings()
    seen = load_json_state(SEEN_FILE, EMPTY_SEEN)
    if scheduled:
        skip = should_skip_scheduled(seen)
        if skip:
            log(f"Skipping this scheduled run: {skip}.")
            return 0

    missing = missing_secrets(("GEMINI_API_KEY",) if dry_run else
                              ("GEMINI_API_KEY", "GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"))
    if missing:
        log(f"ERROR: these GitHub secrets are missing or empty: {', '.join(missing)}. "
            "See the README, step 'Add your secrets'.")
        return 2

    profile = load_profile()
    threshold = int(settings["score_threshold"])
    notes: list[str] = []
    today = today_pacific()
    gemini = Gemini(os.environ["GEMINI_API_KEY"].strip(), settings)

    # 1. Collect
    all_jobs, sources_ok, sources_tried = collect_fixed_sources(settings, notes)
    hn_jobs: list[Job] = []
    if source_on(settings, "hacker_news"):
        sources_tried += 1
        hn_jobs, hn_ok = collect_hacker_news(settings, seen, gemini, notes)
        sources_ok += int(hn_ok)
        all_jobs.extend(hn_jobs)

    # 2. Dedupe (same job on two sources, or seen on an earlier day) + pre-filter
    unique: dict[str, Job] = {}
    keys_taken: set[str] = set()
    for j in all_jobs:
        key = j.dedupe_key()
        if j.uid in unique or key in keys_taken:
            continue
        unique[j.uid] = j
        keys_taken.add(key)
    new_jobs = [j for j in unique.values()
                if j.uid not in seen["jobs"] and j.dedupe_key() not in seen["jobs"]]
    drop_counts: dict[str, int] = {}
    dropped: set[str] = set()
    candidates = []
    for j in new_jobs:
        why = prefilter(j, settings)
        if why:
            drop_counts[why] = drop_counts.get(why, 0) + 1
            dropped.add(j.uid)
        else:
            candidates.append(j)
    log(f"\n{len(unique)} distinct open jobs, {len(new_jobs)} not seen before, "
        f"{len(candidates)} left after the keyword filter.")
    for why, n in sorted(drop_counts.items(), key=lambda x: -x[1]):
        log(f"  dropped {n:>4}: {why}")

    # 3. Score, most promising first, within the AI budget
    candidates.sort(key=priority)
    batch_size = max(1, int(settings["jobs_per_ai_call"]))
    budget = batch_size * gemini.calls_left
    if len(candidates) > budget:
        notes.append(f"{len(candidates) - budget} jobs were left for tomorrow to stay inside "
                     f"the free AI limit ({settings['max_ai_calls_per_run']} AI calls per day).")
    to_score = candidates[:budget]
    fill_details(to_score)  # SmartRecruiters lists titles only; fetch descriptions for these few
    scored: dict[str, dict] = {}
    ai_errors = 0
    for start in range(0, len(to_score), batch_size):
        batch = to_score[start:start + batch_size]
        log(f"  Scoring jobs {start + 1}-{start + len(batch)} of {len(to_score)} with {gemini.model}...")
        try:
            got = score_batch(gemini, profile, batch, int(settings["max_description_chars"]))
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
        seen["jobs"][unique[uid].dedupe_key()] = today
    # HN roles that were neither scored nor filtered out wait for the next run.
    seen["hn"]["pending"] = [j.to_dict() for j in hn_jobs
                             if j.uid in unique and j.uid not in scored and j.uid not in dropped
                             and j.uid not in seen["jobs"] and j.dedupe_key() not in seen["jobs"]]

    matches = sorted(
        ((unique[uid], r) for uid, r in scored.items() if r["score"] >= threshold),
        key=lambda x: (-x[1]["score"], x[0].company, x[0].title))
    log(f"\nScored {len(scored)} jobs with {gemini.calls_made} AI calls; {len(matches)} scored {threshold}+.")
    for job, r in matches:
        log(f"  {r['score']:>3}  {job.company} - {job.title}  [{r['remote']}]  via {job.source}")
    near = sorted(((unique[u], r) for u, r in scored.items() if r["score"] < threshold),
                  key=lambda x: -x[1]["score"])[:10]
    if near:
        log(f"Best of the rest (below {threshold}, not emailed):")
        for job, r in near:
            log(f"  {r['score']:>3}  {job.company} - {job.title}  [{r['remote']}]  {r['reason']}")

    # 4. Email
    stats = {"scored": len(scored), "sources_ok": sources_ok}
    if matches:
        n = len(matches)
        subject = f"{n} new job match{'es' if n != 1 else ''} (top: {matches[0][1]['score']}) - {today}"
        body = build_email(matches, notes, stats, threshold)
        if dry_run:
            (HERE / "preview_email.html").write_text(body, encoding="utf-8")
            log("\nDry run: not sending. Email preview written to preview_email.html")
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
        days = int(settings["forget_seen_jobs_after_days"])
        seen["jobs"] = prune_dated(seen["jobs"], days)
        seen["hn"]["done"] = prune_dated(seen["hn"]["done"], 120)
        save_json_state(SEEN_FILE, seen)

    # Fail loudly (GitHub emails you about a failed run) when nothing worked at all.
    if sources_tried and sources_ok == 0:
        log("ERROR: every job source failed.")
        return 1
    if to_score and not scored:
        log("ERROR: no jobs could be scored by the AI. Check GEMINI_API_KEY.")
        return 1
    return 0


def check_all(probe_names: list[str]) -> int:
    """Test every company board and every source; for failing companies, look for the right slug."""
    settings = load_settings()
    companies = load_companies()
    failed = 0
    log(f"Checking {len(companies)} companies from companies.yaml\n")
    for c in companies:
        try:
            jobs = fetch_board(c)
            passing = [j for j in jobs if not prefilter(j, settings)]
            log(f"  OK    {c['name']:<28} {c['platform']:<10} {c['slug']:<24} {len(jobs)} open jobs, "
                f"{len(passing)} pass the keyword filter")
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"  FAIL  {c['name']:<28} {c['platform']:<10} {c['slug']:<24} {e}")
            probe_names.append(c["name"])

    log("\nChecking the job-board sources (on/off is in settings.yaml -> sources)\n")
    checks = [
        ("remotive", "Remotive", sources.fetch_remotive),
        ("remoteok", "Remote OK", sources.fetch_remoteok),
        ("himalayas", "Himalayas", lambda: sources.fetch_himalayas((settings.get("himalayas_searches") or [])[:2])),
        ("weworkremotely", "We Work Remotely",
         lambda: sources.fetch_weworkremotely(settings.get("weworkremotely_feeds") or [])),
    ]
    for key, label, fetch in checks:
        state = "on " if source_on(settings, key) else "off"
        try:
            jobs = fetch()
            passing = [j for j in jobs if not prefilter(j, settings)]
            log(f"  OK    {label:<16} ({state}) {len(jobs)} jobs, {len(passing)} pass the keyword filter")
        except Exception as e:  # noqa: BLE001
            failed += 1
            log(f"  FAIL  {label:<16} ({state}) {e}")
    state = "on " if source_on(settings, "hacker_news") else "off"
    try:
        t = sources.latest_hn_thread()
        worth = sum(1 for c in t["comments"] if sources.hn_worth_extracting(c["text"]))
        log(f"  OK    {'Hacker News':<16} ({state}) {t['title']}: {len(t['comments'])} posts, "
            f"{worth} mention remote + a relevant role")
    except Exception as e:  # noqa: BLE001
        failed += 1
        log(f"  FAIL  {'Hacker News':<16} ({state}) {e}")

    try:
        import discover
        log("\nChecking the funding-news feeds used by weekly discovery\n")
        failed += discover.check_feeds(settings)
    except ImportError:
        pass

    if probe_names:
        log("\nSearching for boards by name (tries common slug spellings on every platform):")
        for name in dict.fromkeys(probe_names):
            found = find_board(name, verify=False, pause=0.1)
            if found:
                platform, slug, jobs = found
                log(f"  FOUND {name:<28} platform: {platform:<10} slug: {slug:<24} {len(jobs)} open jobs")
            else:
                log(f"  NONE  {name:<28} not on Greenhouse, Lever, Ashby, Workable or SmartRecruiters "
                    "under any common slug")
    return 1 if failed else 0


def test_email() -> int:
    missing = missing_secrets(("GMAIL_ADDRESS", "GMAIL_APP_PASSWORD"))
    if missing:
        log(f"ERROR: these GitHub secrets are missing or empty: {', '.join(missing)}.")
        return 2
    to = os.environ.get("TO_EMAIL") or os.environ["GMAIL_ADDRESS"]
    try:
        send_email("Job alerts: test email", email_shell(
            "Your job alerts can send email", "This is a test from your GitHub Action.",
            "<p>If you're reading this, the Gmail secrets are set up correctly. "
            "Real alerts arrive around 7am Pacific on days with new matches.</p>"))
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: sending failed: {e}")
        log("Check GMAIL_ADDRESS is the full Gmail address and GMAIL_APP_PASSWORD is the 16-letter "
            "app password (not your normal password).")
        return 1
    log(f"Test email sent to {to}. Check your inbox (and spam).")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check", action="store_true", help="only test companies.yaml and every source")
    p.add_argument("--probe", nargs="*", default=[], metavar="NAME",
                   help="with --check: also search for these company names on all platforms")
    p.add_argument("--dry-run", action="store_true", help="don't send email or save seen jobs")
    p.add_argument("--scheduled", action="store_true", help="skip unless it's 7am+ Pacific and not yet run today")
    p.add_argument("--test-email", action="store_true", help="only send a test email, to check the Gmail secrets")
    args = p.parse_args()
    if args.check:
        return check_all(list(args.probe))
    if args.test_email:
        return test_email()
    return run(dry_run=args.dry_run, scheduled=args.scheduled)


if __name__ == "__main__":
    sys.exit(main())
