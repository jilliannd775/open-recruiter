import sys, time
sys.path.insert(0, "job-alerts")
from common import fetch_board, prefilter, load_settings, fill_details, fill_page_details
s = load_settings()
def show(name, platform, slug):
    t = time.time()
    try:
        jobs = fetch_board({"name": name, "platform": platform, "slug": slug})
    except Exception as e:
        print(f"\n{name} ({platform}) FAILED: {e}"); return
    fill_page_details(jobs, s)
    keep = [j for j in jobs if not prefilter(j, s)]
    fill_details(keep[:3])
    print(f"\n{name} ({platform}): {len(jobs)} jobs in {time.time()-t:.0f}s, {len(keep)} pass filters; source={jobs[0].source if jobs else ''}")
    for j in keep[:6]: print("   KEEP", j.title, "|", j.location[:40], "|", j.workplace, "|", len(j.description), "chars")
show("Littlebird", "gem", "littlebird")
show("NVIDIA", "workday", "nvidia.wd5.myworkdayjobs.com/NVIDIAExternalCareerSite")
for name, url in [("Littlebird", "https://littlebird.ai/careers"), ("Anthropic", "https://www.anthropic.com/careers/jobs"),
                  ("Commonwealth Fusion", "https://cfs.energy/careers"), ("Relativity Space", "https://www.relativityspace.com/careers"),
                  ("Oklo", "https://oklo.com/careers"), ("SpaceX", "https://www.spacex.com/careers/jobs")]:
    show(name, "page", url)
