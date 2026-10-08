import csv, json, re
from collections import defaultdict
def ncls(c): return re.sub(r"`\d+", "", c or "").replace("/", "+")
proj = {r["project"]: r["repo_dir"] for r in csv.DictReader(open("study/projects.csv", encoding="utf-8-sig"))}
meth, classes, simple, dup = {}, defaultdict(list), defaultdict(list), 0
for line in open("study/methods.jsonl", encoding="utf-8-sig"):
    r = json.loads(line)
    if r["kind"] == "class":
        k = (r["repo"], r["className"])
        if k not in classes: simple[(r["repo"], r["className"].split(".")[-1].split("+")[-1])].append(r["className"])
        classes[k].extend(r["bases"])
    else:
        k = (r["repo"], r["className"], r["method"])
        if k in meth: dup += 1
        else: meth[k] = r
print("metodos Roslyn:", len(meth), "duplicados ignorados:", dup)

def find_decl(repo, cls, names):
    seen, queue = set(), [cls]
    while queue:
        c = queue.pop(0)
        if c in seen: continue
        seen.add(c)
        for n in names:
            if (repo, c, n) in meth: return meth[(repo, c, n)], (c != cls)
        ns = c.rsplit(".", 1)[0] if "." in c else ""
        for b in classes.get((repo, c), []):
            cands = simple.get((repo, b), [])
            queue.extend([x for x in cands if x.startswith(ns + ".")] or cands)
    return None, False

def combine(labels):
    core = {l for l in labels if l != "skipped"}
    if not core: return "skipped"
    if "flaky" in core: return "flaky"
    if core == {"stable"}: return "stable"
    if core == {"broken"}: return "broken"
    return "mixed"

lab = defaultdict(dict)
for r in csv.DictReader(open("study/labels_methods.csv", encoding="utf-8-sig")):
    lab[(r["project"], ncls(r["className"]), r["method"], r["method_alt"])][r["campaign"]] = r["label"]
units = {}
miss, stat, inherited = [], defaultdict(lambda: [0, 0]), defaultdict(int)
for (p, cls, m, alt), d in lab.items():
    stat[p][1] += 1
    mm, inh = find_decl(proj[p], cls, [m, alt])
    if mm is None:
        miss.append([p, cls, m, alt, d.get("auto", ""), d.get("manual", "")]); continue
    stat[p][0] += 1
    if inh: inherited[p] += 1
    u = units.setdefault((p, mm["className"], mm["method"]), {"mm": mm, "auto": [], "manual": [], "n": 0})
    u["n"] += 1
    if "auto" in d: u["auto"].append(d["auto"])
    if "manual" in d: u["manual"].append(d["manual"])
for p, (a, b) in stat.items(): print(f"{p:20} casados {a}/{b} (herdados: {inherited[p]})")
rows = []
conf = 0
for (p, cls, m), u in units.items():
    mm = u["mm"]
    if len(set(u["auto"])) > 1 and "flaky" in u["auto"]: conf += 1
    rows.append([p, cls, m, combine(u["auto"]) if u["auto"] else "", combine(u["manual"]) if u["manual"] else "", u["n"],
                 mm["loc"], mm["awaits"], mm["asserts"], mm["isAsync"], "|".join(mm["attrs"]), mm["tokens"], mm.get("tokens_noattr", ""), mm.get("tokens_hop1", ""), mm.get("helpers_resolved", 0)])
with open("study/dataset.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["project","className","method","label_auto","label_manual","n_instances","loc","awaits","asserts","isAsync","attrs","tokens","tokens_noattr","tokens_hop1","helpers_resolved"]); w.writerows(rows)
with open("study/unmatched.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["project","className","method","method_alt","label_auto","label_manual"]); w.writerows(miss)
print("unidades (metodos declarados):", len(rows), "| flaky 100x:", sum(r[3] == "flaky" for r in rows),
      "| flaky manual:", sum(r[4] == "flaky" for r in rows), "| unidades flaky com instancias discordantes:", conf)
print("sem casamento:", len(miss), "| flaky 100x sem casamento:", sum(1 for r in miss if r[4] == "flaky"))
