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
| **Your companies** | Every company in `companies.yaml`. Their own careers pages, read through the free Greenhouse, Lever and Ashby feeds | Daily |
| **Hacker News "Who is hiring?"** | The monthly thread where companies post openings. The AI reads each new post and pulls out the roles | Daily (new posts only) |
| **Remotive** | Remote job board (remotive.com). Its free feed is small, about 20 jobs, shown 24 hours after posting | Daily |
| **Remote OK** | Remote job board (remoteok.com). The 100 newest jobs | Daily |
| **Himalayas** | Remote job board (himalayas.app). Searches for your target titles, US-eligible, newest first | Daily |

All five are free and need no sign-up. Each one's terms ask that you credit it
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
3. You should see three workflows in the left sidebar: **Daily job alerts**,
   **Weekly company discovery** and **Check companies and sources**.

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

**To see what it did**, click the run, then **alerts**, then the step **Find,
score and email new jobs**. The log shows:
- how many jobs each source had
- how many the keyword filter dropped, and why
- every score at or above your threshold, with where each job came from

**About test runs:** a manual run always runs, even if the 7am run already
happened. Jobs it has already scored are never emailed again, so a second
test on the same day usually sends nothing. That's expected.

### Test the weekly company discovery

Same steps, but pick **Weekly company discovery** in the left sidebar. It
takes about 5 to 15 minutes, because it checks job boards for each company it
finds. You'll get the summary email whether or not it added anything. Any
companies it adds show up at the bottom of `companies.yaml`.

---

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
3. **Looks for each company's job board** on Greenhouse, Lever and Ashby by
   trying likely names. It double-checks that the board really belongs to that
   company before using it.
4. **Adds the ones it finds** (with open jobs) to the bottom of
   `companies.yaml`, up to **25 a week**. Each one is marked like this:

   ```yaml
     - name: "Hubble Network"
       platform: ashby
       slug: "hubblenetwork"
       tag: discovered
       added: "2026-09-28"
       reason: "Satellite IoT network that just raised a Series C; likely hiring program and ops roles."
   ```
5. **Emails you a summary** of what it added and why. It also lists strong fits
   it couldn't find a board for, with their website.

It never adds the same company twice. It also never re-adds a company you
deleted, because it remembers every company it has ever added. Companies with
no job board are tried again after 90 days, in case they've set one up.

**Changing how picky it is**, in `settings.yaml` under `discovery:`:
- `min_fit_score: 60`: raise it for fewer, better-fitting companies.
- `max_new_companies_per_week: 25`: the weekly cap.

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
| One job source (e.g. Remote OK) | Under `sources:`, set `remoteok: false`. The others are `company_boards`, `hacker_news`, `remotive` and `himalayas` |
| One news feed | Under `discovery:` then `feeds:`, set that feed's `enabled: false` |
| Weekly discovery entirely | Under `discovery:`, set `enabled: false` |
| Everything | Actions tab, then click the workflow, then the **...** menu (top right), then **Disable workflow**. Do it for each workflow you want stopped. Turn it back on the same way |

**Job-board sources only score titles you're targeting.** Remotive, Remote OK,
Himalayas and Hacker News list thousands of jobs. So the AI budget isn't
wasted, a job from those sources is only scored if its title contains a word
from `job_board_title_keywords` in `settings.yaml`, such as program, project,
operations, strategy, analyst or chief of staff. Add words there if you see
good jobs being missed. Jobs from your own companies aren't limited this way.

To change what Himalayas searches for each day, edit the `himalayas_searches`
list.

---

## Adding a company yourself

1. Find the company's careers page and click through to any job posting.
   Look at the web address (URL):

   | If the address looks like... | platform | slug |
   |---|---|---|
   | `job-boards.greenhouse.io/`**`acme`**`/jobs/123` or `boards.greenhouse.io/`**`acme`** | `greenhouse` | `acme` |
   | `jobs.lever.co/`**`acme`**`/abc-123` | `lever` | `acme` |
   | `jobs.ashbyhq.com/`**`acme`**`/abc-123` | `ashby` | `acme` |

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
`Planet, Rocket Lab`), and run it. The log lists any Greenhouse/Lever/Ashby
boards it finds under common spellings.

Companies that run their own in-house careers site, such as Google, Apple,
Amazon and Microsoft, can't be added. They don't publish a free feed.

## Removing a company

Open `companies.yaml`, click the pencil, and do one of these:
- **Delete** the company's lines, from `- name:` down to the line before the
  next `- name:`.
- **Pause** it: add a line `    enabled: false` under it, lined up with
  `platform:`. Delete that line later to switch it back on.

Then **Commit changes**. This works the same for companies you added and ones
discovery added. A company discovery added and you deleted will not come back.

---

## Changing the score threshold

1. Open `settings.yaml` and click the pencil.
2. Change the number in `score_threshold: 65`. Lower means more emails, higher
   means only the strongest matches.
3. Click **Commit changes**. The next run uses the new number.

A new threshold only applies to jobs that haven't been scored yet. Jobs that
were already scored are not re-scored.

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
  2. Jobs go to the AI **20 at a time** in one request, with at most **15
     requests a day** in total. Reading Hacker News uses up to 3 of those.
     Anything left over waits until tomorrow; nothing is lost.
  3. Weekly discovery uses at most **4 requests**, on Mondays.
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
