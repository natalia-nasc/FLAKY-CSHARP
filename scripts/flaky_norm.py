import sys, re, glob, os, statistics
import xml.etree.ElementTree as ET
from collections import defaultdict
ns = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
PATS = [
    (re.compile(r"\[\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2}(?:\.\d+)?Z?\]"), "[TS]"),
    (re.compile(r"\[Thread \d+\]"), "[Thread N]"),
    (re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"), "<GUID>"),
]
DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?")
def norm(s):
    for p, r in PATS: s = p.sub(r, s)
    return s

folder = sys.argv[1]
files = sorted(glob.glob(os.path.join(folder, "*.trx")))
N = len(files)
recs = []; per_run = []
for i, f in enumerate(files):
    root = ET.parse(f).getroot()
    cls = {u.get("id"): u.find("t:TestMethod", ns).get("className") for u in root.iterfind(".//t:UnitTest", ns)}
    n = 0
    for x in root.iterfind(".//t:UnitTestResult", ns):
        k = norm(f'{cls.get(x.get("testId"), "?")}::{x.get("testName")}'); n += 1
        o = x.get("outcome")
        recs.append((i, k, "Passed" if o == "Passed" else "Failed" if o in ("Failed", "Error", "Timeout", "Aborted") else "Skipped"))
    per_run.append(n)
presence = defaultdict(set)
for i, k, _ in recs: presence[k].add(i)
partial0 = {k for k, s in presence.items() if len(s) < N}
res = defaultdict(lambda: {"Passed": 0, "Failed": 0, "Skipped": 0, "runs": set()})
for i, k, o in recs:
    k2 = DATE.sub("<DATE>", k) if k in partial0 else k
    res[k2][o] += 1; res[k2]["runs"].add(i)
partial = [k for k, v in res.items() if len(v["runs"]) < N]
broken = [k for k, v in res.items() if v["Failed"] > 0 and v["Passed"] == 0]
flaky = [k for k, v in res.items() if v["Failed"] > 0 and v["Passed"] > 0]
skipped = [k for k, v in res.items() if v["Passed"] == 0 and v["Failed"] == 0]
print(f"Runs (.trx):                        {N}")
print(f"Resultados por run (min/mediana/max): {min(per_run)} / {int(statistics.median(per_run))} / {max(per_run)}")
print(f"Nomes distintos ANTES de normalizar: {len(presence)}")
print(f"Testes distintos DEPOIS:             {len(res)}")
print(f"Presentes em menos runs que o total: {len(partial)}")
print(f"Stable: {len(res)-len(broken)-len(flaky)-len(skipped)} | Broken: {len(broken)} | Flaky: {len(flaky)} | Skipped: {len(skipped)}")
print("\nFLAKY:");  [print("  ", k, (res[k]["Passed"], res[k]["Failed"])) for k in sorted(flaky)]
print("\nBROKEN:"); [print("  ", k) for k in sorted(broken)]
print("\nAINDA PARCIAIS:"); [print("  ", k) for k in sorted(partial)]

