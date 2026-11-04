import sys, re, glob, os, csv
import xml.etree.ElementTree as ET
from collections import defaultdict

NS = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
PATS = [
    (re.compile(r"\[\d{1,2}/\d{1,2}/\d{4} \d{1,2}:\d{2}:\d{2}(?:\.\d+)?Z?\]"), "[TS]"),
    (re.compile(r"\[Thread \d+\]"), "[Thread N]"),
    (re.compile(r"[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}"), "<GUID>"),
]
DATE = re.compile(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)?")
def norm(s):
    for p, r in PATS: s = p.sub(r, s)
    return s

pasta, saida = sys.argv[1], sys.argv[2]
arquivos = sorted(glob.glob(os.path.join(pasta, "*.trx")))
N = len(arquivos)
recs = []
for i, f in enumerate(arquivos):
    root = ET.parse(f).getroot()
    cls = {u.get("id"): u.find("t:TestMethod", NS).get("className") for u in root.iterfind(".//t:UnitTest", NS)}
    for x in root.iterfind(".//t:UnitTestResult", NS):
        o = x.get("outcome")
        oc = "P" if o == "Passed" else "F" if o in ("Failed", "Error", "Timeout", "Aborted") else "S"
        recs.append((i, cls.get(x.get("testId"), "?"), norm(x.get("testName") or ""), oc))
pres = defaultdict(set)
for i, c, d, _ in recs: pres[(c, d)].add(i)
parcial = {k for k, s in pres.items() if len(s) < N}
agg = {}
for i, c, d, o in recs:
    k = (c, DATE.sub("<DATE>", d) if (c, d) in parcial else d)
    a = agg.setdefault(k, {"P": 0, "F": 0, "S": 0, "runs": set()})
    a[o] += 1; a["runs"].add(i)

cont = defaultdict(int)
with open(saida, "w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["className", "test", "runs_presente", "passed", "failed", "skipped", "label"])
    for (c, d), a in sorted(agg.items()):
        lab = "flaky" if a["F"] and a["P"] else "broken" if a["F"] else "skipped" if not a["P"] else "stable"
        cont[lab] += 1
        w.writerow([c, d, len(a["runs"]), a["P"], a["F"], a["S"], lab])
print(f"execucoes (.trx): {N}")
print(f"testes distintos: {len(agg)}")
print(f"em menos execucoes que o total: {sum(1 for a in agg.values() if len(a['runs']) < N)}")
for l in ("stable", "flaky", "broken", "skipped"): print(f"{l}: {cont[l]}")
print("CSV salvo em", saida)
