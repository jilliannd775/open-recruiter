# Daily AI Job Alerts

Every morning at about 7am Pacific, this checks your chosen companies' job
boards, has Google's Gemini AI score each new job against your profile, and
emails you the good ones. It runs entirely on GitHub's servers for free.
You never install or run anything on your computer.

**What you get:** one email a day listing new jobs that scored **65 or higher**,
best first. Each one has the title, company, score, a one-line reason, the
remote status and location, and an apply link. If nothing new matches, you get
no email that day.

---

## The files you might edit

All of these are in the `job-alerts` folder. You can edit them right on
github.com: open the file, click the **pencil icon** (top right of the file),
make your change, then click **Commit changes**.

| File | What it's for |
|---|---|
| `companies.yaml` | The companies to check |
| `profile.md` | Your background and what you want. The AI reads this for every job |
| `settings.yaml` | The score threshold and AI limits |
| `seen_jobs.json` | The system's memory of jobs it has already scored. **Don't edit** |
| `job_alerts.py` | The program itself. You shouldn't need to touch it |

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
   | `TO_EMAIL` | Where to send the digest. Can be the same Gmail address. Separate several addresses with commas |

When you're done you should see all four names listed under **Repository secrets**.

### Step 4: Make sure GitHub Actions is turned on

1. Click the **Actions** tab at the top of the repository.
2. If you see a button like **I understand my workflows, go ahead and enable
   them**, click it.
3. You should see **Daily job alerts** and **Check company boards** in the left sidebar.

> The daily schedule only runs from the repository's main (default) branch. If
> these files are on a different branch, merge them into main first.

---

## Running a test

1. Click the **Actions** tab.
2. In the left sidebar, click **Daily job alerts**.
3. On the right, click the **Run workflow** dropdown, leave the branch as is,
   and click the green **Run workflow** button.
4. Wait a few seconds and refresh. A new run appears with a yellow dot while it
   works. The first run can take 3 to 5 minutes because every job is new.
5. When it finishes:
   - **Green check**: it worked. If anything matched, the email is in your
     inbox. Check spam the first time and mark it "Not spam".
   - **Red X**: click the run, then click **alerts**, then open the step with
     the red X to read what went wrong. The most common causes are a secret
     name with a typo, or a Gmail app password that was pasted wrong.

**To see what it did**, click the run, then **alerts**, then the step **Find,
score and email new jobs**. The log shows how many jobs each company had, how
many the keyword filter dropped and why, and every score at or above your
threshold.

**About test runs:** a manual run always runs, even if the 7am run already
happened. Jobs it has already scored are never emailed again, so a second
test on the same day usually sends nothing. That's expected.

---

## Adding a company

1. Find the company's careers page and click through to any job posting.
   Look at the web address (URL):

   | If the address looks like... | platform | slug |
   |---|---|---|
   | `job-boards.greenhouse.io/`**`acme`**`/jobs/123` or `boards.greenhouse.io/`**`acme`** | `greenhouse` | `acme` |
   | `jobs.lever.co/`**`acme`**`/abc-123` | `lever` | `acme` |
   | `jobs.ashbyhq.com/`**`acme`**`/abc-123` | `ashby` | `acme` |

   Some companies wrap the board in their own site. If you can't see any of
   those addresses, try the **search** trick below.
2. Open `companies.yaml`, click the pencil, and add a block at the bottom.
   Keep the same indentation as the others:

   ```yaml
     - name: Acme Space
       platform: greenhouse
       slug: acme
   ```
3. Click **Commit changes**.
4. The **Check company boards** action starts by itself. Open it from the
   **Actions** tab. Each company gets a line: **OK** with the number of open jobs, or
   **FAIL** followed by suggestions for the right platform and slug.

**Search trick:** Actions tab, then **Check company boards**, then **Run
workflow**. Type company names in the box, separated by commas (e.g. `Planet,
Rocket Lab`), and run it. The log lists any Greenhouse/Lever/Ashby boards it
finds under common spellings.

Companies that run their own in-house careers site, such as Google, Apple,
Amazon and Microsoft, can't be added. They don't publish a free feed.

To **remove** a company, delete its three lines, or put `#` at the start of
each line to switch it off.

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
require travel over 25%" works. Changes apply to jobs scored after that.

---

## How it stays free

- **GitHub Actions** is free for this. It uses a couple of minutes a day.
- **Job boards**: Greenhouse, Lever and Ashby publish free public job feeds.
  Nothing is scraped from LinkedIn or Indeed.
- **Gemini** has a free daily allowance. Two things keep usage small:
  1. A free keyword filter runs first. It drops engineering, developer and
     scientist titles (unless the title also says "program" or "project").
     It also drops jobs listed as onsite, hybrid or outside the US, and jobs
     that never mention remote at all.
  2. The survivors go to the AI **20 at a time** in a single request, with at
     most **15 requests a day**. If there are more, the rest wait until
     tomorrow and nothing is lost. If the free daily limit on the main model
     runs out, it switches to Flash-Lite, which has a bigger free allowance.

  Google changes free-tier limits from time to time. Your current limits are
  shown at <https://aistudio.google.com/usage>. If the email says the quota was
  used up, lower `max_ai_calls_per_run` in `settings.yaml`.

## When something goes wrong

- **A company's board failed:** the other companies still run, and the problem
  is listed at the bottom of the email. Usually it means the company moved to
  a different platform. Run **Check company boards** to find the new slug.
- **Every board failed, or the AI key doesn't work:** the run gets a red X, and
  GitHub emails the repository owner about the failed run.
- **No emails for days:** open **Actions**, then **Daily job alerts**, and look
  at the latest runs. A green run with "No new matches today" is normal.
- **GitHub turned off the schedule:** GitHub pauses scheduled workflows in
  repositories with no activity for 60 days, and emails you when it does. Go
  to **Actions**, then **Daily job alerts**, and click **Enable workflow**.
- **Timing:** GitHub sometimes starts scheduled runs 5 to 30 minutes late
  when its servers are busy, so the email may arrive a little after 7am.
