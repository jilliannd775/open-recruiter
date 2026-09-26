import json, re, sys, time, urllib.request, urllib.error
sys.path.insert(0, "job-alerts")
from common import detect_ats, strip_html
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
def req(url, data=None, headers=None):
    h = {"User-Agent": UA, "Accept": "application/json"}; h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp: return resp.status, resp.read()
    except urllib.error.HTTPError as e: return e.code, e.read()[:300]
    except Exception as e: return None, str(e).encode()
# Hidden feeds of big companies
tests = [
 ("amazon", "https://www.amazon.jobs/en/search.json?base_query=program%20manager&loc_query=&result_limit=10&offset=0", None, None),
 ("apple", "https://jobs.apple.com/api/role/search", json.dumps({"query": "program manager", "filters": {"range": {"standardWeeklyHours": {"start": None, "end": None}}}, "page": 1, "locale": "en-us", "sort": ""}).encode(), {"Content-Type": "application/json"}),
 ("microsoft", "https://gcsservices.careers.microsoft.com/search/api/v1/search?q=program%20manager&l=en_us&pg=1&pgSz=10&o=Relevance&flt=true", None, None),
 ("microsoft2", "https://apply.careers.microsoft.com/api/pcsx/search?domain=microsoft.com&query=program%20manager&start=0&num=10", None, None),
 ("google", "https://careers.google.com/api/v3/search/?q=program%20manager&page_size=10", None, None),
 ("google2", "https://www.google.com/about/careers/applications/jobs/results?q=program%20manager", None, {"Accept": "text/html"}),
]
for name, u, body, h in tests:
    st, b = req(u, body, h)
    print(f"\nFEED {name} status={st} bytes={len(b)} {b[:500]!r}")
# Real browser
t = time.time()
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    try:
        browser = p.chromium.launch(channel="chrome", headless=True); print("launched system chrome", time.time()-t)
    except Exception as e:
        print("chrome channel failed:", e); browser = p.chromium.launch(headless=True)
    for url in ["https://www.spacex.com/careers/jobs", "https://rocketlabcorp.com/careers/", "https://www.relativityspace.com/careers", "https://www.planet.com/company/careers/", "https://www.amazon.jobs/en/search?base_query=program+manager"]:
        page = browser.new_page(user_agent=UA)
        reqs = []
        page.on("request", lambda r: reqs.append(r.url))
        t = time.time()
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception as e:
            print("  goto:", str(e)[:120])
        html = page.content()
        ats = detect_ats(html + " " + " ".join(reqs), page.url)
        anchors = page.eval_on_selector_all("a[href]", "els => els.map(e => [e.innerText.trim().slice(0,80), e.href])")
        jobish = [a for a in anchors if re.search(r"manager|analyst|engineer|operations|program|specialist|technician", a[0], re.I)]
        xhr = [r for r in reqs if re.search(r"api|json|greenhouse|lever|workday|ashby|graphql", r, re.I)][:8]
        print(f"\nBROWSER {url} -> {page.url} in {time.time()-t:.0f}s html={len(html)} ats={ats} anchors={len(anchors)} jobish={len(jobish)}")
        for a in jobish[:5]: print("   ", a)
        for r in xhr: print("   xhr:", r[:150])
        page.close()
    browser.close()
