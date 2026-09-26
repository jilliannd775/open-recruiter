import sys, time
from collections import Counter
sys.path.insert(0, "job-alerts")
from common import fetch_board, prefilter, load_settings, fill_page_details
s = load_settings()
for name, platform, slug in [("SpaceX", "page", "https://www.spacex.com/careers/jobs"), ("Planet", "page", "https://www.planet.com/company/careers/"),
                             ("Amazon", "amazon", "amazon"), ("Microsoft", "microsoft", "microsoft"), ("Anduril", "greenhouse", "andurilindustries")]:
    t = time.time()
    try:
        jobs = fetch_board({"name": name, "platform": platform, "slug": slug})
        fill_page_details(jobs, s)
        reasons = Counter(prefilter(j, s) or "KEEP" for j in jobs)
        keep = [j for j in jobs if not prefilter(j, s)]
        print(f"\n{name}: {len(jobs)} jobs in {time.time()-t:.0f}s via {jobs[0].source if jobs else ''}; {len(keep)} pass. {reasons.most_common(5)}")
        for j in keep[:8]: print("   ", j.title, "|", j.location[:50], "|", j.workplace)
    except Exception as e:
        print(f"\n{name} FAILED: {e}")
