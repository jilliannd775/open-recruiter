import sys, time
sys.path.insert(0, "job-alerts")
from common import find_board, slug_candidates
tests = [("Hubble Network", "hubble.network"), ("SandboxAQ", ""), ("Anduril Industries", "anduril.com"),
         ("Mesa Quantum", ""), ("Palantir Technologies", "palantir.com"), ("Dextr AI", ""), ("Baselayer", ""),
         ("Planet Labs", "planet.com"), ("Commonwealth Fusion Systems", "cfs.energy"), ("Zzqx Nonexistent Co", "")]
for name, site in tests:
    t = time.time()
    r = find_board(name, site)
    print(f"{name:<30} {slug_candidates(name, site)}\n   -> {(r[0], r[1], len(r[2])) if r else None}  [{time.time()-t:.1f}s]", flush=True)
