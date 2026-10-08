import argparse, os, warnings
import numpy as np, pandas as pd
from sklearn.feature_extraction.text import CountVectorizer
warnings.filterwarnings("ignore")
STOP = set("public private protected internal static void var new if else for foreach while do switch case break continue "
           "return using class struct null this in out ref readonly override virtual abstract sealed partial get set namespace "
           "int string bool object true false".split())
def clean(s): return " ".join(t for t in s.split() if t.lower() not in STOP)

def mi_binary(X, y):
    n = X.shape[0]; n1 = float(y.sum()); n0 = n - n1
    a = np.asarray(X[y == 1].sum(0)).ravel(); b = np.asarray(X[y == 0].sum(0)).ravel()
    c, d = n1 - a, n0 - b
    mi = np.zeros(X.shape[1])
    for cnt, nx, ny in ((a, a + b, n1), (b, a + b, n0), (c, c + d, n1), (d, c + d, n0)):
        with np.errstate(divide="ignore", invalid="ignore"):
            t = np.where(cnt > 0, (cnt / n) * np.log(cnt * n / (nx * ny)), 0.0)
        mi += t
    return mi

ap = argparse.ArgumentParser()
ap.add_argument("--label", default="auto", choices=["auto", "manual"])
ap.add_argument("--draws", type=int, default=30)
ap.add_argument("--seed", type=int, default=42)
a = ap.parse_args()
rng = np.random.default_rng(a.seed)
out = f"study/out_{a.label}"; os.makedirs(out, exist_ok=True)
df = pd.read_csv("study/dataset.csv", keep_default_na=False)
lab = df["label_" + a.label]
d = df[lab.isin(["flaky", "stable"])].copy(); d["y"] = (lab[d.index] == "flaky").astype(int); d = d.reset_index(drop=True)
grp = {r.project: r.repo_dir for r in pd.read_csv("study/projects.csv", encoding="utf-8-sig").itertuples()}
G = d.project.map(grp).values; Y = d.y.values
T = d.tokens.apply(clean).values
pos, neg = np.where(Y == 1)[0], np.where(Y == 0)[0]
cv = CountVectorizer(token_pattern=r"\S+", lowercase=True, ngram_range=(1, 2), binary=True, min_df=2)
X = cv.fit_transform(T).tocsr(); V = np.array(cv.get_feature_names_out())
print(f"unidades={len(d)} flaky={len(pos)} stable={len(neg)} vocabulario={len(V)} sorteios={a.draws}")
ig = np.zeros(X.shape[1])
for _ in range(a.draws):
    rows = np.concatenate([pos, rng.choice(neg, size=len(pos), replace=False)])
    ig += mi_binary(X[rows], Y[rows])
ig /= a.draws
nF = np.asarray(X[pos].sum(0)).ravel(); nS = np.asarray(X[neg].sum(0)).ravel()
groups = sorted(set(G[pos]))
M = np.vstack([np.asarray(X[pos[G[pos] == g]].sum(0)).ravel() for g in groups])
res = pd.DataFrame({"token": V, "IG": ig, "pctF": 100 * nF / len(pos), "pctS": 100 * nS / len(neg), "nF": nF.astype(int),
                    "repos_F": (M > 0).sum(0), "top_repo": np.array(groups)[M.argmax(0)], "top_share": M.max(0) / np.maximum(nF, 1)})
res["tipo"] = np.where(res.pctS > res.pctF, "estabilidade", "flakiness")
res = res[(res.nF >= 2) | (res.pctS >= 5)].sort_values("IG", ascending=False)
res.to_csv(f"{out}/vocabulary.csv", index=False)
fmt = {"IG": "{:.3f}".format, "pctF": "{:.0f}".format, "pctS": "{:.0f}".format, "top_share": "{:.2f}".format}
print("\n=== Top-25 por information gain ===")
print(res.head(25).to_string(index=False, formatters=fmt))
rob = res[(res.repos_F >= 3) & (res.nF >= 3)]
print("\n=== Top-25 tokens presentes em flaky de >=3 repositorios ===")
print(rob.head(25).to_string(index=False, formatters=fmt))
print("\n=== Top-15 marcadores de flakiness (pctF > pctS) em >=3 repositorios ===")
print(rob[rob.tipo == "flakiness"].head(15).to_string(index=False, formatters=fmt))
