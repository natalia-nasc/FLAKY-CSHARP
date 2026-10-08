import json, warnings
import numpy as np, pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier
warnings.filterwarnings("ignore")
STOP = set("public private protected internal static void var new if else for foreach while do switch case break continue "
           "return using class struct null this in out ref readonly override virtual abstract sealed partial get set namespace "
           "int string bool object true false".split())
def clean(s): return " ".join(t for t in s.split() if t.lower() not in STOP)
def make_vec(): return TfidfVectorizer(token_pattern=r"\S+", lowercase=True, ngram_range=(1, 2), min_df=2, max_df=0.9, sublinear_tf=True)
DRAWS = 10
rng = np.random.default_rng(42)
df = pd.read_csv("study/dataset.csv", keep_default_na=False)
d = df[df.label_auto.isin(["flaky", "stable"])].copy(); d["y"] = (d.label_auto == "flaky").astype(int); d = d.reset_index(drop=True)
grp = {r.project: r.repo_dir for r in pd.read_csv("study/projects.csv", encoding="utf-8-sig").itertuples()}
d["repo"] = d.project.map(grp)
T = d.tokens.apply(clean).values; Y = d.y.values; G = d.repo.values
score = np.full(len(d), np.nan)
for g in [g for g in pd.unique(G) if ((Y == 1) & (G == g)).any()]:
    te = np.where(G == g)[0]
    trp, trn = np.where((Y == 1) & (G != g))[0], np.where((Y == 0) & (G != g))[0]
    s = np.zeros(len(te))
    for _ in range(DRAWS):
        itr = np.concatenate([trp, rng.choice(trn, size=len(trp), replace=False)])
        vec = make_vec(); Xtr = vec.fit_transform(T[itr]); Xte = vec.transform(T[te])
        for M in (RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=0),
                  ExtraTreesClassifier(n_estimators=200, class_weight="balanced", random_state=0)):
            s += M.fit(Xtr, Y[itr]).predict_proba(Xte)[:, 1] / (2 * DRAWS)
    score[te] = s
    print("LOPO concluido:", g, flush=True)
d["score"] = score
files = {}
for line in open("study/methods.jsonl", encoding="utf-8-sig"):
    r = json.loads(line)
    if r["kind"] == "method": files[(r["repo"], r["className"], r["method"])] = r["file"]
d["file"] = [files.get((a, b, c), "") for a, b, c in zip(d.repo, d.className, d.method)]
dd = d[d.score.notna()].copy()
dd["pct"] = dd.groupby("repo").score.rank(pct=True)
dd["unit"] = dd.className.str.split(".").str[-1] + "." + dd.method
dd.drop(columns=["tokens"]).to_csv("study/out_auto/rq4_units.csv", index=False)
fl = dd[dd.y == 1].sort_values("pct")
print(f"\nflaky avaliados: {len(fl)} | percentil medio {fl.pct.mean():.2f} | mediana {fl.pct.median():.2f}")
for q in (0.9, 0.75, 0.5): print(f"  no top {int((1-q)*100)}% do ranking do repo: {(fl.pct >= q).sum()} de {len(fl)}")
cols = ["repo", "unit", "pct", "score", "loc", "awaits", "asserts", "label_manual"]
print("\n=== Falsos negativos: 15 flaky com menor percentil ===")
print(fl[cols].head(15).round(2).to_string(index=False))
print("\narquivos:"); [print("  ", f) for f in fl.file.head(15)]
mo = dd[(dd.label_auto == "stable") & (dd.label_manual == "flaky")].sort_values("pct", ascending=False)
print("\n=== Flaky so no manual (rotulados stable no 100x): percentil no ranking ===")
print(mo[cols].round(2).to_string(index=False))
fp = dd[(dd.y == 0) & (dd.label_manual != "flaky")].sort_values("score", ascending=False).head(20)
print("\n=== Falsos positivos: 20 stable com maior pontuacao ===")
print(fp[["repo", "unit", "score", "pct", "loc", "awaits", "asserts"]].round(2).to_string(index=False))
print("\narquivos:"); [print("  ", f) for f in fp.file.head(20)]
