import sys, csv, re, glob, os
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

def read_runs(folder):
    files = sorted(glob.glob(os.path.join(folder, "*.trx")))
    recs = []
    for i, f in enumerate(files):
        root = ET.parse(f).getroot()
        info = {}
        for u in root.iterfind(".//t:UnitTest", ns):
            tm = u.find("t:TestMethod", ns)
            info[u.get("id")] = (tm.get("className"), tm.get("name"))
        for x in root.iterfind(".//t:UnitTestResult", ns):
            cls, mname = info.get(x.get("testId"), ("?", x.get("testName")))
            o = x.get("outcome")
            oc = "P" if o == "Passed" else "F" if o in ("Failed", "Error", "Timeout", "Aborted") else "S"
            disp = norm(x.get("testName") or "")
            recs.append((i, cls, (mname or "").split("(")[0].strip(), disp, oc))
    return len(files), recs

def label_cases(N, recs):
    pres = defaultdict(set)
    for i, cls, m, d, o in recs: pres[(cls, d)].add(i)
    partial = {k for k, s in pres.items() if len(s) < N}
    agg = {}
    for i, cls, m, d, o in recs:
        k = (cls, DATE.sub("<DATE>", d) if (cls, d) in partial else d)
        a = agg.setdefault(k, {"P": 0, "F": 0, "S": 0, "method": m, "alt": d.split("(")[0].rsplit(".", 1)[-1].strip()})
        a[o] += 1
    for a in agg.values():
        a["label"] = ("flaky" if a["F"] and a["P"] else "broken" if a["F"] else
                      "skipped" if not a["P"] else "stable")
    return agg

def method_label(labels):
    core = {l for l in labels if l != "skipped"}
    if not core: return "skipped"
    if "flaky" in core: return "flaky"
    if core == {"stable"}: return "stable"
    if core == {"broken"}: return "broken"
    return "mixed"

results_root, projects = sys.argv[1], sys.argv[2]
cases, methods = [], []
for row in csv.DictReader(open(projects, encoding="utf-8-sig")):
    for camp, sub, col in (("auto", "automated-runs", "auto_folder"), ("manual", "manual-runs", "manual_folder")):
        folder = os.path.join(results_root, sub, row[col])
        N, recs = read_runs(folder)
        agg = label_cases(N, recs)
        by_m = defaultdict(list)
        for (cls, d), a in agg.items():
            cases.append([row["project"], camp, cls, a["method"], d, a["P"], a["F"], a["S"], a["label"]])
            by_m[(cls, a["method"], a["alt"])].append(a["label"])
        for (cls, m, alt), labs in by_m.items():
            methods.append([row["project"], camp, cls, m, alt, method_label(labs)])
        cnt = defaultdict(int)
        for r in methods:
            if r[0] == row["project"] and r[1] == camp: cnt[r[5]] += 1
        print(f'{row["project"]:20} {camp:7} runs={N:3} metodos={dict(cnt)}')
with open("study/labels_cases.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["project","campaign","className","method","display","passed","failed","skipped","label"]); w.writerows(cases)
with open("study/labels_methods.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["project","campaign","className","method","method_alt","label"]); w.writerows(methods)

