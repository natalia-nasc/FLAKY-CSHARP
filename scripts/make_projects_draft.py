import os, re
from difflib import SequenceMatcher
n = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
lcs = lambda a, b: SequenceMatcher(None, a, b).find_longest_match(0, len(a), 0, len(b)).size
A, M = "results/automated-runs", "results/manual-runs"
isd = lambda base, d: os.path.isdir(os.path.join(base, d))
auto = [d for d in sorted(os.listdir(A)) if isd(A, d) and d.endswith("_runs") and not d.startswith("debug")]
manual = [d for d in sorted(os.listdir(M)) if isd(M, d)]
repos = [d for d in sorted(os.listdir("repos")) if isd("repos", d)]
INC = re.compile(r"^(serilog|testcontainers|polly|newtonsoft|nlog|masstransit|restsharp|asyncex|akka|rabbitmq_unit|coravel|quartz|nerdbank_streams|streamjsonrpc|netmq|archunitnet)")
mkey = lambda m: n(re.sub(r"_manual.*$", "", m))
rows, fora = ["project,repo_dir,auto_folder,manual_folder"], []
for a in auto:
    if "_manual_" in a or not INC.match(a): fora.append(a); continue
    k = re.sub(r"(_tests)?_runs$", "", a)
    g = re.match(r"(asyncex|restsharp)", k); proj = g.group(1) if g else k
    cands = sorted(manual, key=lambda m: (mkey(m) != n(k), -lcs(mkey(m), n(k)), len(mkey(m)), not m.endswith("net472")))
    m = cands[0] if cands and lcs(mkey(cands[0]), n(k)) >= 4 else "???"
    r = max(repos, key=lambda d: (lcs(n(d), n(k)), -(len(n(d)) - lcs(n(d), n(k)))))
    r = r if lcs(n(r), n(k)) >= 4 else "???"
    flag = "" if (m != "???" and mkey(m) == n(k) and r != "???") else "   <-- VERIFICAR"
    rows.append(f"{proj},{r},{a},{m}")
    print(f"{proj},{r},{a},{m}{flag}")
open("study/projects_draft.csv", "w", encoding="utf-8").write("\n".join(rows))
print("\nPastas de automated-runs FORA do rascunho:", ", ".join(fora))
print("\nPastas de manual-runs:", ", ".join(manual))
