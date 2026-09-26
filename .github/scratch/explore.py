import json, re, urllib.request, urllib.error
UA = {"User-Agent": "job-alerts/1.0 (personal daily job alert; runs on GitHub Actions)"}
def req(url, data=None, headers=None):
    h = dict(UA); h.update(headers or {})
    r = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(r, timeout=60) as resp: return resp.status, resp.headers.get("content-type"), resp.read()
    except urllib.error.HTTPError as e: return e.code, e.headers.get("content-type"), e.read()[:400]
    except Exception as e: return None, None, str(e).encode()
for u in ["https://api.gem.com/job_board/v0/littlebird/job_posts/", "https://api.gem.com/job_board/v0/littlebird/job_posts",
          "https://api.gem.com/job_board/v0/littlebird/job_posts/?include_content=true"]:
    st, ct, b = req(u); print(f"\n=== GET {u}\n status={st} type={ct} bytes={len(b)}\n {b[:1500]!r}")
st, ct, b = req("https://jobs.gem.com/littlebird")
print(f"\n=== GET board page status={st} type={ct} bytes={len(b)}")
html = b.decode("utf-8", "replace")
for pat in [r'__NEXT_DATA__[^>]*>(.{0,1500})', r'(graphql[^"\']{0,200})', r'(JobBoardList[^"\']{0,300})', r'"(extId|boardId)"\s*:\s*"[^"]+"']:
    for m in list(re.finditer(pat, html))[:3]: print(" match:", pat[:20], "->", m.group(0)[:600])
for body in [
    [{"operationName": "JobBoardList", "variables": {"boardId": "littlebird"}, "query": "query JobBoardList($boardId: String!) { oatsExternalJobPostings(boardId: $boardId) { jobPostings { id extId title locations { name } } } }"}],
]:
    st, ct, b = req("https://jobs.gem.com/api/public/graphql/batch", json.dumps(body).encode(), {"Content-Type": "application/json"})
    print(f"\n=== POST graphql status={st} type={ct}\n {b[:2000]!r}")
