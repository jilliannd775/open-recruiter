import sys; sys.path.insert(0, "job-alerts")
import sources, common
s = common.load_settings()
for name, f in [("Jobicy", sources.fetch_jobicy), ("Working Nomads", sources.fetch_workingnomads)]:
    try:
        jobs = f()
        keep = [j for j in jobs if not common.prefilter(j, s)]
        print(name, len(jobs), "jobs,", len(keep), "pass filter")
        for j in keep[:8]:
            print("   ", j.title, "|", j.company, "|", j.location, "|", j.url, "|", j.extra, "|", len(j.description))
        from collections import Counter
        print("   drop reasons:", Counter(common.prefilter(j, s) for j in jobs).most_common(6))
    except Exception as e:
        print(name, "ERROR", e)
