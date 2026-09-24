import json, urllib.request, urllib.error, xml.etree.ElementTree as ET, time
UA = {"User-Agent": "job-alerts/1.0 (personal job alert; github actions)"}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.headers.get("content-type"), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("content-type"), e.read()[:500]
    except Exception as e:
        return None, None, str(e).encode()
def show(url, n=1):
    st, ct, body = get(url)
    print(f"\n=== {url}\n status={st} type={ct} bytes={len(body)}")
    try:
        d = json.loads(body)
    except Exception:
        print(body[:600]); return None
    if isinstance(d, dict):
        print(" dict keys:", list(d)[:30])
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                print(f" {k}: list len {len(v)}; first item:"); print(json.dumps(v[0], default=str)[:1800]); break
            elif not isinstance(v, (list, dict)):
                print(f"  {k} = {str(v)[:150]}")
    elif isinstance(d, list):
        print(" list len", len(d))
        for item in d[:n+1]:
            print(json.dumps(item, default=str)[:1800])
    return d
# HN
d = show("https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=5")
for h in (d or {}).get("hits", []): print("  ", h.get("objectID"), h.get("title"), h.get("created_at"), h.get("num_comments"))
hid = next((h["objectID"] for h in (d or {}).get("hits", []) if "who is hiring" in h.get("title","").lower()), None)
if hid:
    st, ct, body = get(f"https://hn.algolia.com/api/v1/items/{hid}")
    it = json.loads(body); kids = it.get("children", [])
    print(" item keys", list(it), "top-level comments:", len(kids))
    print(json.dumps({k: v for k, v in kids[0].items() if k != "children"})[:1500])
    rem = [k for k in kids if k.get("text") and "remote" in k["text"].lower()]
    print(" with 'remote':", len(rem))
show("https://remotive.com/api/remote-jobs?limit=2")
st, ct, body = get("https://remotive.com/api/remote-jobs")
try:
    jobs = json.loads(body)["jobs"]; print("\nremotive full count", len(jobs), "bytes", len(body))
    from collections import Counter
    print(Counter(j["category"] for j in jobs).most_common(30))
    print(Counter(j["candidate_required_location"] for j in jobs).most_common(15))
except Exception as e: print("remotive full err", e, body[:300])
show("https://remoteok.com/api", n=1)
show("https://himalayas.app/jobs/api?limit=20&offset=0")
show("https://himalayas.app/jobs/api/search?q=program%20manager&country=US")
show("https://himalayas.app/jobs/api/search?q=program%20manager&worldwide=true")
for f in ["https://techcrunch.com/category/venture/feed/", "https://techcrunch.com/tag/fundraising/feed/",
          "https://techcrunch.com/tag/funding/feed/", "https://news.crunchbase.com/feed/",
          "https://www.finsmes.com/feed", "https://thequantuminsider.com/feed/", "https://spacenews.com/feed/",
          "https://payloadspace.com/feed/", "https://www.geekwire.com/feed/", "https://www.ctvc.co/rss/",
          "https://techfundingnews.com/feed/", "https://www.axios.com/pro/deals/feed", "https://siliconangle.com/feed/",
          "https://www.eu-startups.com/feed/", "https://www.canarymedia.com/rss.rss", "https://news.crunchbase.com/sections/venture/feed/"]:
    st, ct, body = get(f)
    try:
        root = ET.fromstring(body)
        items = root.findall(".//item") or root.findall(".//{http://www.w3.org/2005/Atom}entry")
        titles = [(i.findtext("title") or i.findtext("{http://www.w3.org/2005/Atom}title") or "")[:90] for i in items[:4]]
        dates = [i.findtext("pubDate") or i.findtext("{http://www.w3.org/2005/Atom}updated") for i in items[:1]]
        desc = (items[0].findtext("description") or "")[:200] if items else ""
        print(f"\nFEED {f} status={st} items={len(items)} first_date={dates}\n  titles={titles}\n  desc={desc!r}")
    except Exception as e:
        print(f"\nFEED {f} status={st} PARSE FAIL {e} {body[:200]!r}")
    time.sleep(1)
# ATS probes for discovery sanity
for u in ["https://boards-api.greenhouse.io/v1/boards/andurilindustries", "https://api.ashbyhq.com/posting-api/job-board/sandboxaq?includeCompensation=false"]:
    st, ct, body = get(u); print("\n", u, st, body[:400])
