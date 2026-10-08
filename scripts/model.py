import argparse, os, warnings
import numpy as np, pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer, CountVectorizer
from sklearn.feature_selection import mutual_info_classif
from sklearn.model_selection import StratifiedKFold
from sklearn.metrics import (precision_score, recall_score, f1_score, matthews_corrcoef,
                             roc_auc_score, average_precision_score)
from sklearn.ensemble import RandomForestClassifier, ExtraTreesClassifier, GradientBoostingClassifier
from sklearn.tree import DecisionTreeClassifier
from sklearn.naive_bayes import MultinomialNB
from sklearn.svm import LinearSVC
from sklearn.neighbors import KNeighborsClassifier
from sklearn.linear_model import LogisticRegression
warnings.filterwarnings("ignore")

STOP = set("public private protected internal static void var new if else for foreach while do switch case break continue "
           "return using class struct null this in out ref readonly override virtual abstract sealed partial get set namespace "
           "int string bool object true false".split())
def clean(s): return " ".join(t for t in s.split() if t.lower() not in STOP)
def make_vec(): return TfidfVectorizer(token_pattern=r"\S+", lowercase=True, ngram_range=(1, 2), min_df=2, max_df=0.9, sublinear_tf=True)

CLFS = {
    "RandomForest": lambda: RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=0),
    "DecisionTree": lambda: DecisionTreeClassifier(class_weight="balanced", random_state=0),
    "NaiveBayes": lambda: MultinomialNB(),
    "SVM": lambda: LinearSVC(class_weight="balanced"),
    "KNN": lambda: KNeighborsClassifier(n_neighbors=5, metric="cosine", algorithm="brute"),
    "LogReg": lambda: LogisticRegression(max_iter=1000, class_weight="balanced"),
    "ExtraTrees": lambda: ExtraTreesClassifier(n_estimators=200, class_weight="balanced", random_state=0),
    "GradBoost": lambda: GradientBoostingClassifier(random_state=0),
}
NAMES = list(CLFS) + ["Base:VocabThreshold", "Base:StructRF", "Base:Random", "Base:Majority"]

def fit_score(n, ttr, str_, ytr, tte, ste, rng):
    if n in CLFS:
        vec = make_vec(); Xtr = vec.fit_transform(ttr); Xte = vec.transform(tte)
        m = CLFS[n](); m.fit(Xtr, ytr)
        s = m.predict_proba(Xte)[:, 1] if hasattr(m, "predict_proba") else m.decision_function(Xte)
        return m.predict(Xte), s
    if n == "Base:VocabThreshold":
        cv = CountVectorizer(token_pattern=r"\S+", lowercase=True, binary=True, min_df=2)
        Xtr = cv.fit_transform(ttr); Xte = cv.transform(tte)
        mi = mutual_info_classif(Xtr, ytr, discrete_features=True, random_state=0)
        top = np.argsort(mi)[-10:]
        s = np.asarray(Xte[:, top].sum(axis=1)).ravel()
        return (s > 0).astype(int), s
    if n == "Base:StructRF":
        m = RandomForestClassifier(n_estimators=200, class_weight="balanced", random_state=0).fit(str_, ytr)
        s = m.predict_proba(ste)[:, 1]
        return m.predict(ste), s
    if n == "Base:Random":
        s = rng.random(len(tte)); return (s > 0.5).astype(int), s
    maj = int(ytr.mean() >= 0.5)
    return np.full(len(tte), maj), np.full(len(tte), 0.5)

def metrics(y, p, s):
    return dict(precision=precision_score(y, p, zero_division=0), recall=recall_score(y, p, zero_division=0),
                f1=f1_score(y, p, zero_division=0), mcc=matthews_corrcoef(y, p),
                auc=roc_auc_score(y, s) if len(set(y)) > 1 else np.nan)

ap = argparse.ArgumentParser()
ap.add_argument("--label", default="auto", choices=["auto", "manual"])
ap.add_argument("--draws", type=int, default=10)
ap.add_argument("--folds", type=int, default=5)
ap.add_argument("--seed", type=int, default=42)
ap.add_argument("--drop-noassert", action="store_true")
ap.add_argument("--skip-lopo", action="store_true")
ap.add_argument("--tokcol", default="tokens")
ap.add_argument("--tag", default="")
a = ap.parse_args()
rng = np.random.default_rng(a.seed)
out = f"study/out_{a.label}{a.tag}"; os.makedirs(out, exist_ok=True)

df = pd.read_csv("study/dataset.csv", keep_default_na=False)
df["isAsync"] = df["isAsync"].astype(str).str.lower().eq("true")
for c in ("loc", "awaits", "asserts"): df[c] = pd.to_numeric(df[c])
lab = df["label_" + a.label]
d = df[lab.isin(["flaky", "stable"])].copy()
d["y"] = (lab[d.index] == "flaky").astype(int)
if a.drop_noassert: d = d[(d.y == 1) | (d.asserts > 0)]
d = d.reset_index(drop=True)
grp = {r.project: r.repo_dir for r in pd.read_csv("study/projects.csv", encoding="utf-8-sig").itertuples()}
d["group"] = d.project.map(grp)
T = d[a.tokcol].apply(clean).values; S = d[["loc", "awaits", "asserts", "isAsync"]].astype(float).values; Y = d.y.values
G = d.group.values
pos, neg = np.where(Y == 1)[0], np.where(Y == 0)[0]
print(f"rotulo={a.label} | unidades={len(d)} | flaky={len(pos)} | stable={len(neg)} | sorteios={a.draws} x {a.folds}-fold")

# ---------- CV (RQ1.1 / RQ2) ----------
rows, psum, pcnt = [], {n: np.zeros(len(d)) for n in NAMES}, np.zeros(len(d))
for draw in range(a.draws):
    sel = np.concatenate([pos, rng.choice(neg, size=len(pos), replace=False)])
    skf = StratifiedKFold(a.folds, shuffle=True, random_state=int(rng.integers(1_000_000_000)))
    for tr, te in skf.split(sel, Y[sel]):
        itr, ite = sel[tr], sel[te]; pcnt[ite] += 1
        for n in NAMES:
            p, s = fit_score(n, T[itr], S[itr], Y[itr], T[ite], S[ite], rng)
            psum[n][ite] += p
            rows.append(dict(model=n, draw=draw, **metrics(Y[ite], p, s)))
cv = pd.DataFrame(rows); cv.to_csv(f"{out}/cv_folds.csv", index=False)
def ci(x): x = x.dropna(); return 1.96 * x.std(ddof=1) / np.sqrt(len(x)) if len(x) > 1 else np.nan
summ = []
for n in NAMES:
    r = {"model": n}
    for m in ("precision", "recall", "f1", "mcc", "auc"):
        r[m] = f"{cv[cv.model == n][m].mean():.2f}+-{ci(cv[cv.model == n][m]):.2f}"
    r["_mcc"] = cv[cv.model == n].mcc.mean(); summ.append(r)
summ = pd.DataFrame(summ).sort_values("_mcc", ascending=False).drop(columns="_mcc")
print("\n=== CV (media +- IC95%, teste balanceado 1:1) ===")
print(summ.to_string(index=False))
summ.to_csv(f"{out}/cv_summary.csv", index=False)
pr = d[["project", "className", "method", "label_auto", "label_manual"]].copy(); pr["n_test_folds"] = pcnt
for n in list(CLFS) + ["Base:StructRF"]: pr["flag_" + n] = np.where(pcnt > 0, psum[n] / np.maximum(pcnt, 1), np.nan)
pr[pcnt > 0].to_csv(f"{out}/predictions_cv.csv", index=False)

# ---------- LOPO por repositorio ----------
if not a.skip_lopo:
    groups = [g for g in pd.unique(G) if ((Y == 1) & (G == g)).any()]
    lrows, pooled = [], {n: ([], []) for n in NAMES}
    for g in groups:
        te = np.where(G == g)[0]
        trp, trn = np.where((Y == 1) & (G != g))[0], np.where((Y == 0) & (G != g))[0]
        acc, sc = {n: [] for n in NAMES}, {n: np.zeros(len(te)) for n in NAMES}
        for r in range(a.draws):
            itr = np.concatenate([trp, rng.choice(trn, size=len(trp), replace=False)])
            for n in NAMES:
                p, s = fit_score(n, T[itr], S[itr], Y[itr], T[te], S[te], rng)
                m = metrics(Y[te], p, s); m["ap"] = average_precision_score(Y[te], s)
                acc[n].append(m); sc[n] += s / a.draws
        for n in NAMES:
            lrows.append(dict(model=n, group=g, n_pos=int(Y[te].sum()), n_units=len(te), **pd.DataFrame(acc[n]).mean().to_dict()))
            pooled[n][0].append(Y[te]); pooled[n][1].append(sc[n])
        print("LOPO concluido:", g, flush=True)
    L = pd.DataFrame(lrows); L.to_csv(f"{out}/lopo_groups.csv", index=False)
    srows = []
    for n in NAMES:
        y_all, s_all = np.concatenate(pooled[n][0]), np.concatenate(pooled[n][1]); q = L[L.model == n]
        srows.append(dict(model=n, macro_auc=q.auc.mean(), macro_ap=q.ap.mean(), macro_recall=q.recall.mean(),
                          macro_prec_natural=q.precision.mean(), pooled_auc=roc_auc_score(y_all, s_all),
                          pooled_ap=average_precision_score(y_all, s_all)))
    base = y_all.mean()
    LS = pd.DataFrame(srows).sort_values("pooled_ap", ascending=False)
    print(f"\n=== LOPO (teste na distribuicao natural dos repos deixados de fora; taxa-base de flaky = {base:.4f}) ===")
    print(LS.round(3).to_string(index=False)); LS.to_csv(f"{out}/lopo_summary.csv", index=False)
    best = LS.iloc[0].model
    print(f"\n--- por repositorio: {best} ---")
    print(L[L.model == best][["group", "n_pos", "n_units", "auc", "ap", "recall", "precision"]].round(3).to_string(index=False))
