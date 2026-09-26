import sys, time
sys.path.insert(0, "job-alerts")
import startups, common
t = time.time(); startups.build(80); print(f"build of 80 took {time.time()-t:.0f}s")
t = time.time(); jobs, n, failed = startups.sweep(); print(f"sweep of {n} boards took {time.time()-t:.0f}s, {failed} failed, {len(jobs)} jobs")
s = common.load_settings(); keep = [j for j in jobs if not common.prefilter(j, s)]
from collections import Counter
print(Counter(common.prefilter(j, s) or "KEEP" for j in jobs).most_common())
for j in keep[:25]: print("  ", j.company, "|", j.title, "|", j.location[:40])
