# Replication package: The Vocabulary of Flaky Tests in C#

Replication package for "<TITLE>" (<AUTOR>). The study asks whether the vocabulary of C# test code predicts flaky tests. It uses 16 open-source .NET repositories, re-executed 100 times (automated campaign) and 20 times (manual campaign), 12,797 declaring test methods and 30 flaky ones (100-run labels).

## Contents
- `manifest/`: `projects.csv` (project to repository and run folders) and `MANIFEST.csv` (URL, commit, date and license of each repository).
- `labels/`: flaky/broken/stable labels per test case and per declaring method.
- `dataset/`: unified dataset (labels, structural features, tokens with and without attributes, tokens with one-hop helpers), unmatched cases, and `methods.jsonl.gz` (Roslyn output, gzipped).
- `results/`: cross-validation, leave-one-repository-out (LOPO), vocabulary and error-analysis outputs. `out_auto` and `out_manual` use the 100-run and the 20-run labels; `out_auto_noattr` and `out_auto_hop1` are the sensitivity analyses.
- `scripts/`: re-execution, labeling, Roslyn extraction (`RoslynExtract`), modeling and analysis.
- Raw TRX reports of both campaigns are only in the Zenodo record (`trx.zip`, about 650 MB).

## Environment
Windows 11 Pro, Intel Core i7-1165G7 (4 cores, 8 threads), 16 GB RAM, Python 3.14.5 (pandas, scikit-learn, numpy, scipy; see `requirements.txt`), .NET SDK 10.0.401 for feature extraction. Each repository was run with the SDK that its `global.json` resolves (10.0.401, 10.0.303, 10.0.112 or 8.0.425). The 100-run campaign was executed in July 2026 (ArchUnitNET in September) with an earlier SDK that was not recorded; the 20-run campaign ran between 27 September and 2 October 2026.

## Layout expected by the scripts
The scripts use relative paths and must be run from a root folder with this layout:

    <root>/
      repos/      one folder per repository, checked out at the commit in manifest/MANIFEST.csv
      results/    automated-runs/ and manual-runs/ (from trx.zip)
      study/      scripts/*, manifest/projects.csv and the Roslyn project (study/RoslynExtract)

## Reproduction
1. Clone each repository at its commit (`manifest/MANIFEST.csv`) into `repos/`.
2. Either extract `trx.zip` into `results/` (to reuse our runs) or re-run the suites (`scripts/run_repeated*.ps1`). Flaky outcomes are non-deterministic, so a new campaign may find a different set of flaky tests.
3. Labels: `python study/export_labels.py results study/projects.csv`
4. Features: `dotnet run -c Release --project study/RoslynExtract -- repos study/methods.jsonl`
5. Dataset: `python study/build_dataset.py` (gunzip `methods.jsonl.gz` first if you skip step 4)
6. Models: `python study/model.py --label auto` and `--label manual`
7. Sensitivity analyses: `python study/model.py --label auto --tokcol tokens_noattr --tag _noattr` and `--tokcol tokens_hop1 --tag _hop1`
8. Vocabulary and error analysis: `python study/vocab.py` and `python study/rq4.py`

## Sanity checks
With the 100-run labels: 12,665 units (30 flaky, 12,635 stable); cross-validation MCC about 0.53 (Extra Trees) and 0.51 (Random Forest); without attributes 0.46 and 0.46; with helpers 0.56 and 0.53.

## Notes
- The TRX reports were sanitized: the author's user name and machine name were replaced by `user` and `HOST`. Test names that contained local paths (a few parameterized NLog tests) changed accordingly, and the label files use the same names.
- StackExchange.Redis and SSH.NET were excluded because environment interference made the runs unreliable. `automapper_collection` and `respite` were run but are not part of the study.
- The sources of the studied projects are not redistributed; see their own licenses.

## Licenses
Code: MIT. Data: CC BY 4.0.

## Citation
See `CITATION.cff`.
