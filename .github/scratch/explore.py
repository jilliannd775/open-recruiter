import json, re, sys, urllib.request, urllib.error
sys.path.insert(0, "job-alerts")
UA = {"User-Agent": "Mozilla/5.0 (compatible; job-alerts/1.0; personal daily job alert)"}
def req(url, data=None, headers=None):
    h = dict(UA); h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp: return resp.status, resp.headers.get("content-type"), resp.read(), resp.geturl()
    except urllib.error.HTTPError as e: return e.code, e.headers.get("content-type"), e.read()[:300], url
    except Exception as e: return None, None, str(e).encode(), url
# Gem via our parser
from common import fetch_board, prefilter, load_settings
jobs = fetch_board({"name": "Littlebird", "platform": "gem", "slug": "littlebird"})
s = load_settings()
for j in jobs: print("GEM", j.title, "|", j.location, "|", j.workplace, "|", prefilter(j, s) or "KEEP")
st, ct, b, _ = req("https://api.gem.com/job_board/v0/littlebird/job_posts/"); print("GEM keys:", list(json.loads(b)[0].keys()))
st, ct, b, _ = req("https://api.gem.com/job_board/v0/zzqxnonexist/job_posts/"); print("GEM missing:", st, b[:100])
# Workday
for host, tenant, site in [("nvidia.wd5.myworkdayjobs.com", "nvidia", "NVIDIAExternalCareerSite"), ("salesforce.wd12.myworkdayjobs.com", "salesforce", "External_Career_Site")]:
    body = json.dumps({"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": "program manager"}).encode()
    st, ct, b, _ = req(f"https://{host}/wday/cxs/{tenant}/{site}/jobs", body, {"Content-Type": "application/json", "Accept": "application/json"})
    print(f"\nWORKDAY {host} status={st} type={ct}")
    try:
        d = json.loads(b); print(" total", d.get("total"), "keys", list(d)); p = d["jobPostings"][0]; print(" first:", json.dumps(p)[:500])
        st2, ct2, b2, _ = req(f"https://{host}/wday/cxs/{tenant}/{site}{p['externalPath']}", headers={"Accept": "application/json"})
        d2 = json.loads(b2); info = d2.get("jobPostingInfo", {}); print(" detail status", st2, "info keys", list(info)); print(" remoteType:", info.get("remoteType"), "| location:", info.get("location"), "| url:", info.get("externalUrl"))
    except Exception as e: print(" parse fail", e, b[:300])
# BambooHR
for co in ["stickermule", "bamboohr", "tenstorrent", "zzqxnonexist"]:
    st, ct, b, final = req(f"https://{co}.bamboohr.com/careers/list", headers={"Accept": "application/json"})
    print(f"\nBAMBOO {co} status={st} type={ct} final={final} bytes={len(b)} {b[:400]!r}")
    try:
        d = json.loads(b); r = d.get("result") or []
        if r:
            jid = r[0]["id"]; st2, ct2, b2, _ = req(f"https://{co}.bamboohr.com/careers/{jid}/detail", headers={"Accept": "application/json"})
            print(" detail", st2, b2[:600])
    except Exception as e: print(" parse fail", e)
# Careers pages
for u in ["https://littlebird.ai/careers", "https://www.anthropic.com/careers/jobs", "https://www.spacex.com/careers/jobs", "https://www.rocketlabcorp.com/careers/", "https://www.planet.com/company/careers/"]:
    st, ct, b, final = req(u, headers={"Accept": "text/html"})
    html = b.decode("utf-8", "replace")
    ats = sorted(set(re.findall(r"(boards\.greenhouse\.io/[\w-]+|job-boards\.greenhouse\.io/[\w-]+|greenhouse\.io/embed/job_board\?for=[\w-]+|jobs\.lever\.co/[\w-]+|jobs\.ashbyhq\.com/[\w.-]+|apply\.workable\.com/[\w-]+|jobs\.gem\.com/[\w-]+|[\w-]+\.wd\d+\.myworkdayjobs\.com/[\w-]+|[\w-]+\.bamboohr\.com|jobs\.smartrecruiters\.com/[\w-]+)", html)))
    anchors = re.findall(r"<a[^>]+href=\"([^\"]+)\"[^>]*>(.*?)</a>", html, re.S)
    jobish = [(re.sub(r"<[^>]+>", " ", t).strip()[:60], h[:80]) for h, t in anchors if re.search(r"manager|analyst|engineer|operations|program|lead|specialist", t, re.I)]
    print(f"\nPAGE {u} status={st} final={final} bytes={len(b)} ats={ats[:5]} anchors={len(anchors)} jobish={len(jobish)}")
    for x in jobish[:6]: print("   ", x)
