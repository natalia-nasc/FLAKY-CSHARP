import csv
from collections import defaultdict
rows = list(csv.DictReader(open("study/dataset.csv", encoding="utf-8")))
st = defaultdict(lambda: defaultdict(int))
for r in rows:
    p = r["project"]; st[p]["unidades"] += 1
    st[p]["auto_" + (r["label_auto"] or "-")] += 1
    st[p]["manual_" + (r["label_manual"] or "-")] += 1
print(f'{"projeto":26}{"unid":>6}{"flaky100x":>11}{"broken":>8}{"mixed":>7}{"flakyManual":>13}')
for p, d in sorted(st.items()):
    print(f'{p:26}{d["unidades"]:>6}{d["auto_flaky"]:>11}{d["auto_broken"]:>8}{d["auto_mixed"]:>7}{d["manual_flaky"]:>13}')
fl = [r for r in rows if r["label_auto"] == "flaky"]
print("\nFLAKY (100x):", len(fl), "| sem asserts:", sum(r["asserts"] == "0" for r in fl))
for r in sorted(fl, key=lambda r: (r["project"], r["className"])):
    print(f'  {r["project"]:18} n={r["n_instances"]:>3} manual={r["label_manual"] or "-":8} {r["className"].split(".")[-1]}.{r["method"]}')
stb = [r for r in rows if r["label_auto"] == "stable"]
print("\nSTABLE (100x):", len(stb), "| sem asserts:", sum(r["asserts"] == "0" for r in stb))
