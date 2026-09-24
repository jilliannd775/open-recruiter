import json, urllib.request, urllib.error
UA = {"User-Agent": "job-alerts/1.0 (personal job alert; github actions)"}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e: return e.code, e.read()[:300]
st, d = get("https://remotive.com/api/remote-jobs?limit=1")
print("REMOTIVE LEGAL:", d.get("0-legal-notice")); print("WARN:", d.get("00-warning"))
for q in ["search?q=program%20manager&country=US", "search?q=program%20manager&country=US&sort=recent",
          "search?q=program%20manager&country=US&page=2", "search?q=chief%20of%20staff&country=US&sort=recent"]:
    st, d = get("https://himalayas.app/jobs/api/" + q)
    print("\nHIMALAYAS", q, st, "total", d.get("totalCount") if isinstance(d, dict) else d)
    if isinstance(d, dict):
        print(" comments:", d.get("comments"))
        for j in d["jobs"][:6]:
            print("  ", j.get("pubDate"), "|", j.get("title"), "|", j.get("companyName"), "|", j.get("locationRestrictions"))
        j = d["jobs"][0]; print(" keys:", list(j)); print(" link fields:", {k: j.get(k) for k in ("applicationLink", "guid", "pubDate", "expiryDate")})
