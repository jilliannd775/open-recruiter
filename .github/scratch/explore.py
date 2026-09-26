import json, sys, time, urllib.request
sys.path.insert(0, "job-alerts")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept": "application/json"}), timeout=60) as r: return json.loads(r.read())
d = get("https://www.amazon.jobs/en/search.json?base_query=program%20manager&result_limit=3&offset=0&normalized_country_code%5B%5D=USA")
print("AMAZON hits", d.get("hits"), "keys", list(d["jobs"][0]))
j = d["jobs"][0]; print({k: (str(v)[:120]) for k, v in j.items() if k not in ("description",)})
d = get("https://www.amazon.jobs/en/search.json?base_query=program%20manager%20virtual&result_limit=3&offset=0&normalized_country_code%5B%5D=USA")
print("AMAZON virtual:", [(x["title"], x.get("location"), x.get("city")) for x in d["jobs"]])
d = get("https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query=program%20manager&location=United%20States&start=0&num=3")
pos = d["data"]["positions"]; print("MSFT count", d["data"].get("count"), "keys", list(pos[0])); print({k: str(v)[:150] for k, v in pos[0].items()})
print("MSFT data keys", list(d["data"]))
from common import fetch_board, prefilter, load_settings, fill_page_details
s = load_settings()
for name, url in [("SpaceX", "https://www.spacex.com/careers/jobs"), ("Planet", "https://www.planet.com/company/careers/")]:
    t = time.time()
    try:
        jobs = fetch_board({"name": name, "platform": "page", "slug": url})
        keep = [j for j in jobs if not prefilter(j, s)]
        print(f"\nPAGE {name}: {len(jobs)} jobs in {time.time()-t:.0f}s via {jobs[0].source if jobs else ''}; {len(keep)} pass")
        for j in keep[:5]: print("   ", j.title, "|", j.location)
    except Exception as e: print(f"\nPAGE {name} FAILED {e}")
