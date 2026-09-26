# Daily AI Job Alerts

Every morning at about 7am Pacific, this collects new job postings from several
free sources. Google's Gemini AI scores each one against your profile, and the
good ones are emailed to you. Once a week it also reads startup-funding news
and adds promising newly-funded companies to your list for you.

Everything runs on GitHub's servers for free. You never install or run
anything on your computer.

**Your daily email** lists new jobs that scored **65 or higher**, best first.
Each one has the title, company, score, a one-line reason, the remote status
and location, an apply link, and which source it came from. If nothing new
matches, you get no email that day.

**Your Monday email** lists the companies it added to your list and why. It
also lists strong fits it couldn't find a job board for, with their website,
so you can check those yourself.

---

## Where the jobs come from

| Source | What it is | How often |
|---|---|---|
| **Startup board list** | Built for you automatically: the job boards of about 1,500 hiring US startups from the Y Combinator directory. See "The startup board list" below | Daily |
| **Your companies** | Every company in `companies.yaml`. Their own careers pages, read through the free Greenhouse, Lever, Ashby, Workable, SmartRecruiters, Gem and Workday feeds | Daily |
| **Hacker News "Who is hiring?"** | The monthly thread where companies post openings. The AI reads each new post and pulls out the roles | Daily (new posts only) |
| **Remotive** | Remote job board (remotive.com). Its free feed is small, about 20 jobs, shown 24 hours after posting | Daily |
| **Remote OK** | Remote job board (remoteok.com). The 100 newest jobs | Daily |
| **Himalayas** | Remote job board (himalayas.app). Searches for your target titles, US-eligible, newest first | Daily |
| **We Work Remotely** | One of the biggest remote job boards (weworkremotely.com). Its management & finance, product, and "all other" categories | Daily |

All six are free and need no sign-up. Each one's terms ask that you credit it
and link back to its listing. The email does that for every job ("via
Remotive", and so on), and the jobs are only emailed to you. Nothing is
scraped from LinkedIn or Indeed.

The same job showing up in two places, such as a company's own board and
Himalayas, is only sent once.

---

## The files you might edit

All of these are in the `job-alerts` folder. You can edit them right on
github.com: open the file, click the **pencil icon** (top right of the file),
make your change, then click **Commit changes**.

| File | What it's for |
|---|---|
| `profile.md` | Your background and what you want. The AI reads this for every job and every company |
| `companies.yaml` | The companies to check. Weekly discovery adds to it automatically |
| `settings.yaml` | Score threshold, sources on/off, discovery settings, AI limits |
| `seen_jobs.json`, `discovery_state.json` | The system's memory. **Don't edit** |
| `*.py` | The programs themselves. You shouldn't need to touch them |

---

## One-time setup (about 10 minutes)

### Step 1: Get a free Gemini API key

1. Go to <https://aistudio.google.com/apikey> and sign in with a Google account.
2. Click **Create API key**. If it asks, pick or create a project; any name works.
3. Copy the key (a long string starting with `AIza...`). You'll paste it in Step 3.

The free tier doesn't need a credit card. If Google offers to "upgrade" or set
up billing, you can skip it.

### Step 2: Get a Gmail app password

Gmail won't let a program use your normal password, so you create a separate
app password for this.

1. 2-Step Verification must be turned on for your Google account. Check at
   <https://myaccount.google.com/signinoptions/twosv>.
2. Go to <https://myaccount.google.com/apppasswords>.
3. For the app name, type `Job alerts` and click **Create**.
4. Google shows a 16-letter password in four groups, like `abcd efgh ijkl mnop`.
   Copy it. You won't be able to see it again, but you can always make a new one.

### Step 3: Add your four secrets to GitHub

Secrets are stored encrypted. Nobody can read them back, including you, and
they never appear in the code or the logs.

1. Open this repository on github.com.
2. Click **Settings** in the top menu. On a phone, use "Desktop site" first.
3. In the left sidebar, click **Secrets and variables**, then **Actions**.
4. Click the green **New repository secret** button.
5. Add these four secrets one at a time. The **Name** must match exactly
   (capital letters, underscores). Click **Add secret** after each one.

   | Name | Secret (what to paste) |
   |---|---|
   | `GEMINI_API_KEY` | The key from Step 1 |
   | `GMAIL_ADDRESS` | The Gmail address that sends the email, e.g. `you@gmail.com` |
   | `GMAIL_APP_PASSWORD` | The 16-letter app password from Step 2. Spaces are fine |
   | `TO_EMAIL` | Where to send the emails. Can be the same Gmail address. Separate several addresses with commas |

When you're done you should see all four names listed under **Repository secrets**.

### Step 4: Make sure GitHub Actions is turned on

1. Click the **Actions** tab at the top of the repository.
2. If you see a button like **I understand my workflows, go ahead and enable
   them**, click it.
3. You should see four workflows in the left sidebar: **Daily job alerts**,
   **Build startup board list**, **Weekly company discovery** and **Check
   companies and sources**.

> Scheduled runs only happen from the repository's main (default) branch. If
> these files are on a different branch, merge them into main first.

---

## Running a test

### Test the daily job alert

1. Click the **Actions** tab.
2. In the left sidebar, click **Daily job alerts**.
3. On the right, click the **Run workflow** dropdown, leave the branch as is,
   and click the green **Run workflow** button.
4. Wait a few seconds and refresh. A new run appears with a yellow dot while it
   works. The first run takes about 5 to 10 minutes because every job is new.
5. When it finishes:
   - **Green check**: it worked. If anything matched, the email is in your
     inbox. Check spam the first time and mark it "Not spam".
   - **Red X**: click the run, then click **alerts**, then open the step with
     the red X to read what went wrong. The most common causes are a secret
     name with a typo, or a Gmail app password that was pasted wrong.

**To check only the email setup:** in the **Run workflow** dropdown, tick
**Only send a test email** before clicking the green button. It skips the job
search and just sends you a test message in under a minute.

**To see what it did**, click the run, then **alerts**, then the step **Find,
score and email new jobs**. The log shows:
- how many jobs each source had
- how many the keyword filter dropped, and why
- every score at or above your threshold, with where each job came from
- the 10 best jobs that scored below it, with the AI's reason

**About test runs:** a manual run always runs, even if the 7am run already
happened. Jobs it has already scored are never emailed again, so a second
test on the same day usually sends nothing. That's expected.

### Test the weekly company discovery

Same steps, but pick **Weekly company discovery** in the left sidebar. It
takes about 5 to 15 minutes, because it checks job boards for each company it
finds. You'll get the summary email whether or not it added anything. Any
companies it adds show up at the bottom of `companies.yaml`.

---

## The startup board list (no company list needed)

You don't need to know your target companies. A separate action, **Build
startup board list**, runs early every morning:

1. It takes every company in the Y Combinator directory that's hiring in the
   US and has at least 5 people.
2. It finds each one's job board on Greenhouse, Lever, Ashby, Workable or
   SmartRecruiters, and saves the list in `startup_boards.json`.

It looks up 400 companies a run, so the list fills in over the first few
days. To fill it faster, run **Build startup board list** by hand a few times
from the Actions tab. After that it mostly re-checks: found boards every 2
months, and companies with no board every 3 months.

The daily alert then reads every board on the list. Because there are
thousands of jobs, they go through the same strict filters as the big job
boards before any AI:
- your target titles or keywords
- not too senior
- remote, and open to the US

Big companies are still covered by Himalayas, We Work Remotely and the other
job boards, which search by title across all companies.

To turn it off, set `startup_boards: false` under `sources:` in
`settings.yaml`.

## Weekly company discovery

Every Monday morning, before the daily alert, it:

1. **Reads the past week's startup-funding news** from free news feeds:
   - TechCrunch (Venture, and Funding)
   - Crunchbase News
   - The Quantum Insider
   - Payload and SpaceNews (space)
   - CTVC (a climate-tech deals newsletter)
   - GeekWire

   SiliconANGLE is in the list but switched off, because it's mostly general
   tech news.
2. **Has the AI pick out funded companies** that fit the sectors in your
   `profile.md` and are big enough to hire program, operations or strategy
   people.

   It also looks through the **Y Combinator company directory**: YC companies
   that say they're hiring, are in the US, have at least 15 people, and
   mention one of your sectors (quantum, space, fusion, climate, defense, and
   so on). The AI scores those against your profile too. It looks at up to 40
   a week and doesn't look at the same one again for 6 months.
3. **Looks for each company's job board** on Greenhouse, Lever, Ashby,
   Workable, SmartRecruiters and Gem by trying likely names. It double-checks that the board really belongs to that
   company before using it.
4. **Adds the ones it finds** (with open jobs) to the bottom of
   `companies.yaml`, up to **25 a week**. Each one is marked like this:

   ```yaml
     - name: "Hubble Network"
       platform: greenhouse
       slug: "hubblenetwork"
       tag: discovered
       added: "2026-09-28"
       reason: "Satellite IoT network that just raised a Series C; likely hiring program and ops roles."
   ```
5. **Emails you a summary** of what it added and why. It also lists strong fits
   it couldn't find a board for, with their website.
6. **Helps you reach out before a job is posted.** For the best-fitting
   companies (up to 12), the email suggests who to contact (a person named in
   the news when there is one, otherwise the right role, like the founder or
   head of operations), a tip for finding them, and a short note from you that
   the AI drafts from your profile and resume. Edit it and send it yourself.
7. **Funding alerts.** If the week's news mentions a company you're watching,
   it's listed at the top of the email: new funding usually means hiring soon.
   You're watching every company in `companies.yaml` plus any names you add
   under `watch_for_funding:` in `settings.yaml`.

It never adds the same company twice. It also never re-adds a company you
deleted, because it remembers every company it has ever added. Companies with
no job board are tried again after 90 days, in case they've set one up.

**Changing how picky it is**, in `settings.yaml` under `discovery:`:
- `min_fit_score: 60`: raise it for fewer, better-fitting companies.
- `max_new_companies_per_week: 25`: the weekly cap.

**Turning off the outreach notes:** under `discovery:`, set
`outreach_notes: false`. Change `outreach_max` for more or fewer.

**Changing the YC sectors:** under `discovery:`, edit the `yc_sector_keywords`
list. Change `yc_min_team_size` to allow smaller or only bigger companies, or
set `yc_directory: false` to stop using YC.

**Adding a news feed:** under `feeds:` in `settings.yaml`, copy one of the
entries and change the `name` and `url`. Any free RSS feed works. After you
save, the **Check companies and sources** action tests it for you.

A few feeds were tried and left out because their sites block automated
readers: FinSMEs, Tech Funding News and Axios Pro. EU-Startups works, but it
covers European companies, so it isn't included.

---

## Turning things on and off

All of these are in `settings.yaml`. Change the word, then **Commit changes**.

| To turn off... | Change this |
|---|---|
| One job source (e.g. Remote OK) | Under `sources:`, set `remoteok: false`. The others are `company_boards`, `hacker_news`, `remotive`, `himalayas` and `weworkremotely` |
| The Y Combinator directory | Under `discovery:`, set `yc_directory: false` |
| One news feed | Under `discovery:` then `feeds:`, set that feed's `enabled: false` |
| Weekly discovery entirely | Under `discovery:`, set `enabled: false` |
| Everything | Actions tab, then click the workflow, then the **...** menu (top right), then **Disable workflow**. Do it for each workflow you want stopped. Turn it back on the same way |

**Job-board sources only score titles you're targeting.** Remotive, Remote OK,
Himalayas, We Work Remotely and Hacker News list thousands of jobs. So the AI budget isn't
wasted, a job from those sources is only scored if its title contains a word
from `job_board_title_keywords` in `settings.yaml`, such as program, project,
operations, strategy, analyst or chief of staff. Add words there if you see
good jobs being missed. Jobs from your own companies aren't limited this way.

To change what Himalayas searches for each day, edit the `himalayas_searches`
list. To read other We Work Remotely categories, add their RSS links to
`weworkremotely_feeds`.

---

## Adding a company yourself

1. Find the company's careers page and click through to any job posting.
   Look at the web address (URL):

   | If the address looks like... | platform | slug |
   |---|---|---|
   | `job-boards.greenhouse.io/`**`acme`**`/jobs/123` or `boards.greenhouse.io/`**`acme`** | `greenhouse` | `acme` |
   | `jobs.lever.co/`**`acme`**`/abc-123` | `lever` | `acme` |
   | `jobs.ashbyhq.com/`**`acme`**`/abc-123` | `ashby` | `acme` |
   | `apply.workable.com/`**`acme`**`/j/ABC123` | `workable` | `acme` |
   | `jobs.smartrecruiters.com/`**`Acme`**`/123-job-title` | `smartrecruiters` | `Acme` (capital letters matter) |
   | `jobs.gem.com/`**`acme`**`/...` | `gem` | `acme` |
   | `acme.wd5.myworkdayjobs.com/`**`AcmeCareers`**`/...` | `workday` | `acme.wd5.myworkdayjobs.com/AcmeCareers` (the whole address up to the site name) |

   Some companies wrap the board in their own site. If you can't see any of
   those addresses, try the **search** trick below.
2. Open `companies.yaml`, click the pencil, and add a block. Keep the same
   indentation as the others:

   ```yaml
     - name: Acme Space
       platform: greenhouse
       slug: acme
   ```
3. Click **Commit changes**.
4. The **Check companies and sources** action starts by itself. Open it from
   the **Actions** tab. Each company gets a line: **OK** with the number of open jobs, or
   **FAIL** followed by suggestions for the right platform and slug.

**Search trick:** Actions tab, then **Check companies and sources**, then
**Run workflow**. Type company names in the box, separated by commas (e.g.
`Planet, Rocket Lab`), and run it. The log lists any Greenhouse, Lever, Ashby,
Workable or SmartRecruiters boards it finds under common spellings.

**Companies with their own careers website** (no Greenhouse, Lever, etc. in
the address): add the careers page itself, and it's checked every day:

```yaml
  - name: Acme Space
    url: https://acmespace.com/careers
```

- If the page is really powered by one of the hiring systems above (very
  common, even when it doesn't look like it), the watcher notices and reads
  that system's full feed.
- Otherwise it picks the job links off the page, reads each relevant one,
  and runs them through the same filters and AI scoring.
- Some sites (SpaceX, for example) load their jobs with browser scripts, so
  there's nothing on the page to read. **Check companies and sources** will
  say so. For those, open a job and use the address its **Apply** button goes
  to instead; that's usually a Workday or Greenhouse link you can add.

BambooHR-hosted career pages can't be read (they have no public feed).

## Removing a company

Open `companies.yaml`, click the pencil, and do one of these:
- **Delete** the company's lines, from `- name:` down to the line before the
  next `- name:`.
- **Pause** it: add a line `    enabled: false` under it, lined up with
  `platform:`. Delete that line later to switch it back on.

Then **Commit changes**. This works the same for companies you added and ones
discovery added. A company discovery added and you deleted will not come back.

---

## Pay and experience

In `settings.yaml`:
- **`min_salary: 130000`**: a job is skipped only when its posted pay range
  tops out below this. Jobs that don't list pay are kept, since many don't.
- **`max_years_experience: 6`**: a job is skipped only when it clearly asks
  for more (e.g. "8+ years of experience"). Jobs that don't say are kept.

Your target (2-5 years, $130k+) is also in `profile.md`, so the AI scores
jobs that fit it higher. When a job lists pay, the email shows it.

## Choosing which job titles you see

Two lists in `settings.yaml` control this:

- **`my_target_titles`**: your specific titles, such as Technical Program
  Manager, Chief of Staff or Product Owner. A job whose title contains one of
  these is always considered, from any source.
- **`too_senior_title_words`**: director, VP, head of, principal, staff,
  chief, and so on. Any other job with one of these words in its title is
  skipped as too senior. Your own titles are exempt, so "Chief of Staff" is
  kept even though it contains "chief". "Principal Program Manager" is still
  skipped, because "principal" isn't part of your title.

Everything else that is mid-level still gets considered. To also skip
Senior-level roles, add `senior` and `sr` to `too_senior_title_words`. Your
target level is also written in `profile.md`, and the AI scores roles above it
lower.

## Changing the score threshold

1. Open `settings.yaml` and click the pencil.
2. Change the number in `score_threshold: 65`. Lower means more emails, higher
   means only the strongest matches.
3. Click **Commit changes**. The next run uses the new number.

A new threshold only applies to jobs that haven't been scored yet. Jobs that
were already scored are not re-scored.

## Giving the AI your resume (optional, recommended)

The AI scores jobs much better when it can see your actual experience. This
repository is **public**, so don't put your resume in a file here. Add it as a
secret instead; secrets are encrypted and never shown to anyone:

1. Open your resume, select all the text, and copy it. Plain text is fine;
   formatting doesn't matter.
2. Go to **Settings**, then **Secrets and variables**, then **Actions**, then
   **New repository secret**.
3. Name: `RESUME`. Secret: paste the text. Click **Add secret**.

From the next run on, the AI reads it along with `profile.md` when scoring
jobs and picking companies. To update it later, click the pencil next to
`RESUME` and paste the new version.

## Changing what the AI looks for

Edit `profile.md`. Write it the way you'd brief a recruiter. Adding "Score
anything at a fusion company 10 points higher" or "I don't want roles that
require travel over 25%" works. It's used for scoring jobs and for picking
companies in the weekly discovery. Changes apply from the next run.

---

## How it stays free

- **GitHub Actions** is free for this. It uses a few minutes a day.
- **Job sources and news feeds** are all free public feeds with no sign-up.
  It asks each one for data at most once a day, well inside their limits.
  Remotive, for example, asks for no more than 4 times a day.
- **Gemini** has a free daily allowance. Four things keep usage small:
  1. A free keyword filter runs first. It drops engineering, developer and
     scientist titles (unless the title also says "program" or "project").
     It also drops jobs listed as onsite, hybrid or outside the US, jobs that
     never mention remote, and job-board titles outside your target words.
  2. Jobs go to the AI **25 at a time** in one request, with at most **40
     requests a day** in total (up to 1,000 jobs). Reading Hacker News uses up
     to 3 of those. Anything left over waits until tomorrow; nothing is lost.
  3. Weekly discovery uses at most **5 requests**, on Mondays: 4 for the news
     and 1 for the Y Combinator directory.
  4. If the free daily limit on the main model runs out, it switches to
     Flash-Lite, which has a bigger free allowance.

  Google changes free-tier limits from time to time. Your current limits are
  shown at <https://aistudio.google.com/usage>. If an email says the quota was
  used up, lower `max_ai_calls_per_run` in `settings.yaml`.

## When something goes wrong

- **A company or source failed:** everything else still runs, and the problem
  is listed at the bottom of the email. Run **Check companies and sources** to
  see what's broken. A company usually fails because it moved to a different
  platform.
- **Every source failed, or the AI key doesn't work:** the run gets a red X,
  and GitHub emails the repository owner about the failed run.
- **No emails for days:** open **Actions**, then **Daily job alerts**, and look
  at the latest runs. A green run with "No new matches today" is normal.
- **GitHub turned off the schedule:** GitHub pauses scheduled workflows in
  repositories with no activity for 60 days, and emails you when it does. Go
  to **Actions**, click the workflow, and click **Enable workflow**.
- **Timing:** GitHub sometimes starts scheduled runs 5 to 30 minutes late
  when its servers are busy, so the email may arrive a little after 7am.
