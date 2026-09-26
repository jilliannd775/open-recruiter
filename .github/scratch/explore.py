import sys; sys.path.insert(0, "job-alerts")
import common as c
for plat, slug, name in [("recruitee","hostaway","Hostaway"),("breezy","tushy","Tushy"),("jazzhr","cyclopsio","Cyclops"),
                         ("jazzhr","firstadvantage","First Advantage"),("recruitee","zzqxnonexist","X"),("breezy","zzqxnonexist","X"),("jazzhr","zzqxnonexist","X")]:
    try:
        jobs = c.fetch_board({"platform": plat, "slug": slug, "name": name})
        print(plat, slug, len(jobs))
        for j in jobs[:3]:
            print("   ", j.title, "|", j.location, "|", j.workplace, "|", j.url, "|", j.extra, "|", len(j.description), c.format_salary(c.parse_salary(j)))
    except Exception as e:
        print(plat, slug, "ERROR", type(e).__name__, str(e)[:150])
import xml.etree.ElementTree as ET
t = c.http_text("https://app.jazz.co/feeds/export/jobs/cyclopsio")
print("JAZZ TAGS", [ch.tag for ch in ET.fromstring(t.strip().encode()).find("job")])
print("GUESS", c.find_board("Hostaway", "hostaway.com", quick=True)[:2] if c.find_board("Hostaway", "hostaway.com", quick=True) else None)
