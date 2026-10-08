import csv, re, sys
from pathlib import Path

root = Path(r"<ROOT>\repos")
projs = list(csv.DictReader(open(r"<ROOT>\study\projects.csv", encoding="utf-8-sig")))
repo_dirs = sorted({p["repo_dir"] for p in projs})

FW = {
    "xUnit":  [r"\bxunit\b", r"xunit\.v3", r"xunit\.core"],
    "NUnit":  [r"\bnunit\b", r"nunit3testadapter"],
    "MSTest": [r"mstest\.testframework", r"mstest\.testadapter", r"microsoft\.visualstudio\.testplatform\.testframework", r"\bmstest\b"],
}
MOCK = {"Moq": r"\bmoq\b", "NSubstitute": r"nsubstitute", "FakeItEasy": r"fakeiteasy",
        "FluentAssertions": r"fluentassertions", "Shouldly": r"shouldly", "AutoFixture": r"autofixture"}

rows = []
for repo in repo_dirs:
    base = root / repo
    if not base.exists():
        continue
    tests_by_fw = {k: 0 for k in FW}
    mocks = set(); tfms = set(); testprojs = 0
    # arquivos centralizados que podem declarar pacotes
    central = ""
    for f in list(base.rglob("Directory.Packages.props")) + list(base.rglob("Directory.Build.props")):
        try: central += f.read_text(encoding="utf-8", errors="ignore").lower()
        except: pass
    for csproj in base.rglob("*.csproj"):
        if "test" not in csproj.name.lower() and "spec" not in csproj.name.lower():
            continue
        txt = csproj.read_text(encoding="utf-8", errors="ignore").lower()
        testprojs += 1
        for fw, pats in FW.items():
            if any(re.search(p, txt) for p in pats):
                tests_by_fw[fw] += 1
        for name, pat in MOCK.items():
            if re.search(pat, txt): mocks.add(name)
        for m in re.finditer(r"<targetframeworks?>(.*?)</targetframeworks?>", txt):
            tfms.update(x.strip() for x in m.group(1).split(";") if x.strip())
    # se o csproj nao declara (versao central), olha os props
    for fw, pats in FW.items():
        if tests_by_fw[fw] == 0 and any(re.search(p, central) for p in pats):
            tests_by_fw[fw] = -1   # -1 = so nos arquivos centrais
    rows.append((repo, testprojs, tests_by_fw, sorted(mocks), sorted(tfms)))

print(f"{'repo':28} {'proj':>4}  {'xUnit':>5} {'NUnit':>5} {'MSTest':>6}  mocks/assert | TFMs")
for repo, n, t, m, tf in rows:
    print(f"{repo:28} {n:>4}  {t['xUnit']:>5} {t['NUnit']:>5} {t['MSTest']:>6}  {','.join(m)} | {';'.join(tf)}")
print("\n(-1 = pacote so aparece em Directory.*.props; 0 = nao encontrado)")

with open(r"<ROOT>\study\frameworks.csv", "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f); w.writerow(["repo","test_projects","xunit","nunit","mstest","libs","tfms"])
    for repo, n, t, m, tf in rows:
        w.writerow([repo, n, t["xUnit"], t["NUnit"], t["MSTest"], ",".join(m), ";".join(tf)])
