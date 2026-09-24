import json, urllib.request, urllib.error, xml.etree.ElementTree as ET
UA = {"User-Agent": "job-alerts/1.0 (personal daily job alert; runs on GitHub Actions)"}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r: return r.status, r.read()
    except urllib.error.HTTPError as e: return e.code, e.read()[:300]
    except Exception as e: return None, str(e).encode()
def js(url, show=1):
    st, b = get(url); print(f"\n=== {url} status={st} bytes={len(b)}")
    try: d = json.loads(b)
    except Exception: print(b[:300]); return None
    if isinstance(d, dict):
        print(" keys:", list(d)[:20])
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                print(f" {k}: {len(v)} items; first:", json.dumps(v[0])[:1500]); break
            if not isinstance(v, (list, dict)): print(f"  {k}={str(v)[:120]}")
    elif isinstance(d, list): print(" list", len(d), json.dumps(d[0])[:1500] if d else "")
    return d
for slug in ["huggingface", "zzqxnonexist"]:
    js(f"https://apply.workable.com/api/v1/widget/accounts/{slug}?details=true")
js("https://apply.workable.com/api/v1/widget/accounts/huggingface")
for co in ["Visa", "ServiceNow", "BoschGroup", "zzqxnonexist"]:
    d = js(f"https://api.smartrecruiters.com/v1/companies/{co}/postings?limit=5")
    if d and d.get("content"):
        pid = d["content"][0]["id"]
        dd = js(f"https://api.smartrecruiters.com/v1/companies/{co}/postings/{pid}")
        if dd: print(" detail keys:", list(dd)); print(" urls:", dd.get("postingUrl"), dd.get("applyUrl")); print(" jobAd:", json.dumps(dd.get("jobAd"))[:400])
for f in ["https://weworkremotely.com/remote-jobs.rss", "https://weworkremotely.com/categories/remote-management-and-finance-jobs.rss",
          "https://weworkremotely.com/categories/remote-product-jobs.rss", "https://weworkremotely.com/categories/all-other-remote-jobs.rss",
          "https://weworkremotely.com/categories/remote-business-and-management-jobs.rss"]:
    st, b = get(f); print(f"\n=== {f} status={st} bytes={len(b)}")
    try:
        root = ET.fromstring(b); items = root.findall(".//item"); print(" items", len(items))
        if items:
            it = items[0]; print(" fields:", [(c.tag, (c.text or "")[:80]) for c in it])
    except Exception as e: print(" parse fail", e, b[:200])
st, b = get("https://weworkremotely.com/terms-of-service"); print("\nWWR terms status", st, len(b))
import re
if st == 200:
    t = re.sub(r"<[^>]+>", " ", b.decode("utf-8", "replace")); 
    for m in re.finditer(r"[^.]{0,300}(RSS|scrap|automated|API)[^.]{0,300}\.", t): print(" TERMS:", " ".join(m.group(0).split())[:600])
for u in ["https://yc-oss.github.io/api/meta.json", "https://yc-oss.github.io/api/companies/hiring.json"]:
    d = js(u)
    if isinstance(d, list):
        from collections import Counter
        print(" regions:", Counter(r for c in d for r in c.get("regions", [])).most_common(8))
        print(" stages:", Counter(c.get("stage") for c in d).most_common(5))
        print(" batches:", Counter(c.get("batch") for c in d).most_common(8))
        print(" industries:", Counter(c.get("industry") for c in d).most_common(12))
