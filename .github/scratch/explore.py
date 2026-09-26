import json, re, urllib.request, urllib.error
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"
def get(u, accept="application/json"):
    try:
        with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA, "Accept": accept}), timeout=60) as r:
            return r.status, r.headers.get("content-type"), r.read(), r.geturl()
    except urllib.error.HTTPError as e: return e.code, e.headers.get("content-type"), e.read()[:200], u
    except Exception as e: return None, None, str(e).encode(), u
for slug in ["hostaway", "constructivedialogue", "zzqxnonexist"]:
    st, ct, b, f = get(f"https://{slug}.recruitee.com/api/offers/")
    print(f"\nRECRUITEE {slug} {st} {ct} final={f} bytes={len(b)}")
    try:
        d = json.loads(b); o = d.get("offers") or []; print(" count", len(o))
        if o: print(" keys", list(o[0])); print(" sample", {k: str(o[0].get(k))[:80] for k in ("id","title","location","city","country","country_code","remote","hybrid","on_site","careers_url","min_salary","max_salary","salary","employment_type_code","experience_code","status")})
    except Exception as e: print(" not json", b[:150])
for slug in ["tushy", "playtestcloud", "zzqxnonexist"]:
    st, ct, b, f = get(f"https://{slug}.breezy.hr/json?verbose=true")
    print(f"\nBREEZY {slug} {st} {ct} final={f} bytes={len(b)}")
    try:
        d = json.loads(b); print(" count", len(d))
        if d: print(" keys", list(d[0])); print(" sample", {k: str(d[0].get(k))[:120] for k in ("id","name","url","location","type","salary","department","published_date","description")})
    except Exception as e: print(" not json", b[:150])
for slug in ["cyclopsio", "firstadvantage", "zzqxnonexist"]:
    st, ct, b, f = get(f"https://app.jazz.co/feeds/export/jobs/{slug}", "application/xml")
    print(f"\nJAZZ XML {slug} {st} {ct} final={f} bytes={len(b)} {b[:300]!r}")
    st, ct, b, f = get(f"https://{slug}.applytojob.com/apply", "text/html")
    html = b.decode("utf-8", "replace")
    links = re.findall(r'href="(https?://[^"]*applytojob\.com/apply/[A-Za-z0-9]+/[^"]*)"[^>]*>(.*?)</a>', html, re.S)
    print(f"JAZZ HTML {slug} {st} final={f} bytes={len(b)} job links={len(links)}", [ (re.sub('<[^>]+>','',t).strip()[:50], h[:90]) for h,t in links[:3]])
