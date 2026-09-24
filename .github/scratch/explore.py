import sys, time
sys.path.insert(0, "job-alerts")
from concurrent.futures import ThreadPoolExecutor
from common import find_board, fetch_board, fill_details, prefilter, load_settings
tests = [("Hugging Face", "huggingface.co"), ("ServiceNow", "servicenow.com"), ("Bosch Group", ""),
         ("Hubble Network", "hubble.network"), ("Planet Labs", "planet.com"), ("Google", "google.com"),
         ("Commonwealth Fusion Systems", "cfs.energy"), ("Zzqx Nonexistent Co", "")]
t0 = time.time()
with ThreadPoolExecutor(max_workers=6) as pool:
    res = list(pool.map(lambda t: (t, find_board(*t)), tests))
for (name, site), r in res:
    print(f"{name:<30} -> {(r[0], r[1], len(r[2])) if r else None}")
print(f"total {time.time()-t0:.1f}s for {len(tests)} companies in parallel")
jobs = fetch_board({"name": "ServiceNow", "platform": "smartrecruiters", "slug": "ServiceNow"})
s = load_settings(); keep = [j for j in jobs if not prefilter(j, s)]
print("ServiceNow SR:", len(jobs), "jobs,", len(keep), "pass filter")
fill_details(keep[:3]); 
for j in keep[:3]: print("  ", j.title, "|", j.location, "|", j.url, "| desc chars", len(j.description))
jobs = fetch_board({"name": "Hugging Face", "platform": "workable", "slug": "huggingface"})
print("HF workable:", len(jobs), [(j.title, j.workplace, j.location, j.extra.get("country")) for j in jobs[:3]])
