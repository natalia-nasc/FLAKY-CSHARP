# Reproducing "The Vocabulary of Flaky Tests in C#"

This document explains how to reproduce every result in the paper from the replication package (`natalia-nasc/FLAKY-CSHARP` and its Zenodo record). It is written for a reader who has not seen the project before.

There are three levels of reproduction. Each one needs more time and more of your own hardware than the previous one.

| Level | What you do | What it reproduces | Time | Needs |
|---|---|---|---|---|
| **A. Models and analyses** | Run the modeling and analysis scripts on the shipped labels and Roslyn output | All tables and figures: cross-validation, LOPO, vocabulary, error analysis, sensitivity | About 1 minute for cross-validation; LOPO and error analysis take longer (see 6.3) | Python only |
| **B. Labels and features** | Rebuild the labels from the raw TRX reports and re-extract the token features from the sources | The dataset itself (12,797 units, 30 flaky) | Minutes to tens of minutes, plus cloning 16 repositories | Python, .NET SDK 10, `trx.zip` (about 650 MB), the 16 repositories |
| **C. New test runs** | Re-execute the test suites 100 times (and 20 times) | A new set of flaky tests. **This will not give the same 30 flaky tests**, because flakiness is non-deterministic | Days of machine time | Everything above, plus a Windows machine, Docker for some suites, and the correct SDKs |

Start with Level A. It is the only level that reproduces the numbers exactly.

---

## 1. Terminology

- **Test case**: one result row in a TRX report (a parameterized test produces one case per argument set). The suites contain 19,211 cases.
- **Unit (declaring method)**: the test method that declares one or more cases, as found in the source code. Cases are mapped to the method that declares them, and inherited tests are mapped to the base class that declares them. There are 12,797 units, of which 12,665 have a usable label. This is the unit of analysis in the paper.
- **Round**: one set of repeated executions. The *100-run round* is called `auto` in the package, and the *20-run round* (run under isolation) is called `manual`.
- **Labels**:
  - *flaky*: failed in at least one run and passed in at least one run.
  - *broken*: failed in every run in which it was executed.
  - *stable*: never failed.
  - *skipped*: never passed and never failed.
  - A unit with several cases gets *flaky* if any case is flaky, *stable* if all cases are stable, *broken* if all are broken, and *mixed* otherwise.
- **TRX**: the XML test report produced by `dotnet test --logger trx` (or by `--report-trx` on the Microsoft Testing Platform).
- **LOPO**: leave-one-project-out validation. In the package it is implemented per repository (`repo_dir`), so the two MassTransit suites are held out together.

---

## 2. What is in the package

```
FLAKY-CSHARP/
  manifest/    projects.csv, MANIFEST.csv
  labels/      labels_cases.csv, labels_methods.csv
  dataset/     dataset.csv, unmatched.csv, methods.jsonl.gz
  results/     out_auto/, out_manual/, out_auto_noattr/, out_auto_hop1/
  scripts/     *.py, *.ps1, RoslynExtract/
  requirements.txt, README.md, CITATION.cff, LICENSE
```

| File | Content |
|---|---|
| `manifest/MANIFEST.csv` | URL, commit hash, commit date and license file of each of the 16 repositories |
| `manifest/projects.csv` | Maps each of the 17 projects (MassTransit counts twice) to its repository folder and to the folders of TRX reports of the two rounds |
| `labels/labels_cases.csv` | One row per test case and round: passes, failures, skips and label |
| `labels/labels_methods.csv` | One row per declaring method and round, with its label |
| `dataset/methods.jsonl.gz` | Roslyn output: one JSON line per class and per test method (tokens, size, number of `await` and asserts, attributes) |
| `dataset/dataset.csv` | The final dataset, one row per unit (12,797 rows) |
| `dataset/unmatched.csv` | Cases that could not be mapped to a declaring method (765 methods; none of them flaky in the 100-run round) |
| `results/out_*` | The outputs of the modeling scripts for each label set and sensitivity analysis |
| Zenodo `trx.zip` | The raw TRX reports of both rounds. This is the only way to redo the labels (Level B) |

### Studied repositories

Check out each repository at the commit in `manifest/MANIFEST.csv`.

| Repository | URL | Commit | Commit date |
|---|---|---|---|
| akka.net | https://github.com/akkadotnet/akka.net | `8943f250305dcebfb437aae83fd666393a9632fe` | 2026-07-20 |
| ArchUnitNET | https://github.com/TNG/ArchUnitNET | `28b62ec0d98f9babb4ccdb6d8a1c3673a0497bcb` | 2026-08-28 |
| AsyncEx | https://github.com/StephenCleary/AsyncEx | `0361015459938f2eb8f3c1ad1021d19ee01c93a4` | 2021-09-25 |
| coravel | https://github.com/jamesmh/coravel | `4072e041820f2d14529276340abb7150a83945da` | 2025-07-19 |
| MassTransit | https://github.com/MassTransit/MassTransit | `62ab339afa3bac2e9b3fe1769d0d35d7e44778e9` | 2026-06-04 |
| Nerdbank.Streams | https://github.com/AArnott/Nerdbank.Streams | `9af91d10aeec990c4be376d511603ecab4e73145` | 2026-07-23 |
| netmq | https://github.com/zeromq/netmq | `17689605bc90234cd8789bdd33ddc9170612f678` | 2026-05-25 |
| Newtonsoft.Json | https://github.com/JamesNK/Newtonsoft.Json | `4f73e74372445108d2c1bda37b36e6f5e43402e0` | 2026-03-18 |
| NLog | https://github.com/NLog/NLog | `86e7d55db79269f311c4b1e6da7b478ce391b205` | 2026-07-11 |
| Polly | https://github.com/App-vNext/Polly | `8ba491d7da22a0364c9eb4bbef3a09d0c97c52a9` | 2026-07-10 |
| quartznet | https://github.com/quartznet/quartznet | `bd946b1bc39fb90cf1ffaaea2cfbb4c7c7b10316` | 2026-07-21 |
| rabbitmq-dotnet-client | https://github.com/rabbitmq/rabbitmq-dotnet-client | `c702061cf648f77851092d194bbd95fda17339a8` | 2026-07-08 |
| RestSharp | https://github.com/restsharp/RestSharp | `6a5082169257438cd085f822f050d93256a8e499` | 2026-06-02 |
| serilog | https://github.com/serilog/serilog | `07d39cfb2928076ecd902a61d295f90d74fe1fa5` | 2026-07-10 |
| testcontainers-dotnet | https://github.com/testcontainers/testcontainers-dotnet | `1717807affaae9b967035516ebedcd76dd7eaffb` | 2026-07-02 |
| vs-streamjsonrpc | https://github.com/microsoft/vs-streamjsonrpc | `d34c6fbc0e825169cdca97cde1e3e65cc059b682` | 2026-07-23 |

StackExchange.Redis and SSH.NET were evaluated and **excluded**, because environment interference made their runs unreliable. The folders `automapper_collection` and `respite` appear in the run folders but are not part of the study.

---

## 3. Requirements

| Component | Version used in the paper |
|---|---|
| Python | 3.14.5 (3.13 gave identical cross-validation results in our check) |
| Python packages | `numpy==2.5.3`, `pandas==3.0.6`, `scikit-learn==1.9.1`, `scipy==1.18.1` (`requirements.txt`) |
| .NET SDK for feature extraction | 10.0.401 |
| Roslyn | `Microsoft.CodeAnalysis.CSharp` 5.9.0 (pinned in `RoslynExtract.csproj`) |
| .NET SDKs for the test suites (Level C only) | The one that each repository's `global.json` resolves: 10.0.401, 10.0.303, 10.0.112 or 8.0.425 |
| Operating system for the test runs | Windows 11 Pro |
| Hardware for the test runs | Intel Core i7-1165G7 (4 cores, 8 threads), 16 GB RAM |
| PowerShell | Needed only for `scripts/run_repeated*.ps1` |
| Docker | Needed only to run the integration suites of Testcontainers and RabbitMQ |

Level A needs only Python and the four packages:

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## 4. Folder layout expected by the scripts

The scripts use relative paths and **must be run from one root folder**. They read and write a folder called `study/`. The package ships the same files in folders called `manifest/`, `labels/`, `dataset/` and `scripts/`, so you have to copy them into a `study/` folder first.

```
<root>/
  repos/                one folder per repository, at the commit from MANIFEST.csv   (Level B and C)
  results/
    automated-runs/     TRX folders of the 100-run round (from trx.zip)              (Level B)
    manual-runs/        TRX folders of the 20-run round (from trx.zip)               (Level B)
  study/                scripts and intermediate files, see below
```

Set up `study/` from a clone of the package. Run these commands in an empty root folder (Bash; on Windows use Git Bash or WSL):

```bash
git clone https://github.com/natalia-nasc/FLAKY-CSHARP.git pkg
mkdir -p study
cp pkg/scripts/*.py                 study/
cp pkg/manifest/projects.csv        study/projects.csv
cp pkg/labels/labels_cases.csv      study/
cp pkg/labels/labels_methods.csv    study/
cp pkg/dataset/dataset.csv          study/
cp pkg/dataset/unmatched.csv        study/
gunzip -c pkg/dataset/methods.jsonl.gz > study/methods.jsonl
cp -r pkg/scripts/RoslynExtract     study/RoslynExtract
```

Only copy the files you need. Level A needs `projects.csv` and `dataset.csv`. Level B overwrites `labels_*.csv`, `methods.jsonl` and `dataset.csv`.

---

## 5. Level A: reproduce the models and analyses from the shipped data

Run all commands from `<root>` (the folder that contains `study/`), never from inside `study/`.

### 5.1 Check that the dataset is the one in the paper

```bash
python study/summarize.py
```

The last lines should show 12,797 units, 30 flaky units in the 100-run round and 19 in the 20-run round. `dataset.csv` has the columns `project, className, method, label_auto, label_manual, n_instances, loc, awaits, asserts, isAsync, attrs, tokens, tokens_noattr, tokens_hop1, helpers_resolved`.

### 5.2 Cross-validation and leave-one-project-out (RQ1.1, RQ2)

```bash
python study/model.py --label auto       # 100-run labels: main results
python study/model.py --label manual     # 20-run labels: robustness (RQ1.2)
```

Each call runs both cross-validation and LOPO and writes `study/out_<label>/`:

| Output | Content | Paper |
|---|---|---|
| `cv_folds.csv` | Metrics of every fold of every draw (50 estimates per model) | Table 3 |
| `cv_summary.csv` | Mean ± 95% interval per model | Table 3 |
| `lopo_groups.csv` | LOPO metrics per held-out repository | Table 5, Figure 3 |
| `lopo_summary.csv` | Macro and pooled AUC and AP | Table 4 |
| `predictions_cv.csv` | Per-unit prediction frequencies in the test folds | |

Options of `model.py`: `--draws` (default 10 undersampled draws), `--folds` (5), `--seed` (42), `--skip-lopo`, `--drop-noassert`, `--tokcol` (token column, default `tokens`), `--tag` (suffix of the output folder).

The cross-validation protocol is: keep all flaky units, draw an equal number of stable units at random (1:1), run a stratified 5-fold cross-validation on that balanced sample, and repeat for 10 independent draws (50 estimates). The TF-IDF vectorizer is fitted only on the training folds. LOPO trains on the other repositories (balanced 1:1) and tests on the held-out repository at its **natural** flaky rate, which is why precision is low there.

**Expected result with the 100-run labels** (we reproduced these numbers from the shipped data):

| Model | MCC | AUC |
|---|---|---|
| Extra Trees | 0.53 ± 0.05 | 0.86 ± 0.03 |
| Gradient Boosting | 0.51 ± 0.06 | 0.83 ± 0.03 |
| Random Forest | 0.51 ± 0.06 | 0.87 ± 0.03 |
| Decision Tree, Logistic Regression, SVM, Naive Bayes | 0.43 to 0.44 | 0.71 to 0.82 |
| Vocabulary threshold baseline | 0.40 | 0.77 |
| KNN | 0.38 | 0.74 |
| Structure-only baseline | 0.36 | 0.73 |
| Random / Majority | 0.02 / 0.00 | 0.53 / 0.50 |

**Expected LOPO result (100-run labels; flaky base rate 0.39%)**, reproduced from the shipped data:

| Model | Macro AUC | Pooled AUC | Pooled AP |
|---|---|---|---|
| Extra Trees | 0.757 | 0.775 | 0.015 |
| Random Forest | 0.754 | 0.753 | 0.023 |
| Vocabulary threshold baseline | 0.682 | 0.721 | 0.025 |
| Random baseline | 0.516 | 0.554 | 0.006 |

The unit counts printed at the start must be `unidades=12665 | flaky=30 | stable=12635`.

The 95% interval is the mean ± 1.96 standard errors over the 50 fold estimates. The folds share the same 30 positives and the draws share the same stable pool, so the estimates are not independent and the interval is optimistic. Treat it as a measure of variation, not as a formal confidence interval.

### 5.3 Sensitivity analyses (Table 11)

```bash
python study/model.py --label auto --tokcol tokens_noattr --tag _noattr     # without attributes ([Fact], [Theory], ...)
python study/model.py --label auto --tokcol tokens_hop1   --tag _hop1       # plus tokens of helper methods (one hop)
```

Expected: without attributes, Extra Trees and Random Forest reach MCC 0.46; with one-hop helpers they reach 0.56 and 0.53. Gradient Boosting and Decision Tree get worse with helpers (0.43 and 0.39).

### 5.4 Vocabulary (RQ3)

```bash
python study/vocab.py                    # writes study/out_auto/vocabulary.csv; runs in seconds
```

It computes the information gain of each unigram and bigram, averaged over 30 balanced draws, and prints three rankings: the top 25 by gain, the top 25 among tokens that appear in flaky tests of at least 3 repositories, and the top 15 flakiness markers among those. Columns: `IG`, `pctF` and `pctS` (percentage of flaky and stable units that contain the token), `nF`, `repos_F` (number of repositories in which it appears in a flaky unit), `top_repo` and `top_share` (the repository that contributes most flaky occurrences, and its share).

Expected top of the ranking: `task` (80% of flaky units against 31% of stable ones), then `async` and `await` (67% against about 30%). The `top_share` column shows how much of each token's signal comes from a single repository, most visibly `vs-streamjsonrpc`.

### 5.5 Error analysis (RQ4)

```bash
python study/rq4.py                      # writes study/out_auto/rq4_units.csv
```

It runs LOPO with the mean score of Random Forest and Extra Trees (10 draws), converts the score into a percentile within each unit's repository, and lists:

- the percentile of each flaky unit (median about 0.80; 23 of 30 units in the top quartile of their repository; 9 at or above 0.90; 6 below 0.50),
- the false negatives (flaky units with the lowest percentile) with their source file,
- the units that were flaky only in the 20-run round,
- the 20 stable units with the highest scores (false positives).

`rq4.py` needs `study/out_auto/` to exist. Running `model.py --label auto` first creates it.

### 5.6 Runtime

Cross-validation of all 12 models takes about 1 minute on a laptop. LOPO (9 repositories x 10 draws x 12 models) and `rq4.py` (9 repositories x 10 draws x 2 models) train many more models and take much longer: plan for tens of minutes on a laptop, and run them in the background.

---

## 6. Level B: rebuild labels and features from raw data

### 6.1 Get the raw TRX reports

Download `trx.zip` from the Zenodo record (about 650 MB) and extract it into `<root>/results/`, so that you get `results/automated-runs/<folder>/run_1.trx ... run_100.trx` and `results/manual-runs/<folder>/run_1.trx ... run_20.trx`. The folder names must match `auto_folder` and `manual_folder` in `study/projects.csv`. The TRX files were sanitized: the author's user name and machine name were replaced by `user` and `HOST`.

### 6.2 Rebuild the labels

```bash
python study/export_labels.py results study/projects.csv
```

For each row of `projects.csv` and each round, the script reads all `*.trx` files in the folder and normalizes the volatile parts of test names: bracketed timestamps become `[TS]`, `[Thread n]` becomes `[Thread N]`, GUIDs become `<GUID>`, and, for test names that do not appear in every run, ISO dates become `<DATE>`. It then counts passes, failures and skips per test case, assigns the case label, and combines the cases of each method. It writes `study/labels_cases.csv` and `study/labels_methods.csv` and prints, per project and round, the number of runs and the label counts. A project whose folder has fewer runs than expected (100 or 20) is the first thing to check if numbers differ.

To inspect one folder by hand:

```bash
python study/flaky_norm.py results/automated-runs/netmq_runs       # counts and lists stable/broken/flaky/skipped
python study/fails_in_runs.py results/automated-runs/netmq_runs <name-fragment>   # which runs a test failed in
python study/diff_trx.py results/automated-runs/x/run_1.trx results/manual-runs/y/run_1.trx   # tests missing in one round
```

### 6.3 Re-extract tokens and structure with Roslyn

Check out the 16 repositories into `<root>/repos/`, **one folder per repository, with the folder name equal to `repo_dir` in `projects.csv`** (for example `repos/akka.net`, `repos/vs-streamjsonrpc`). Use the commits in section 2. You do not need to build them; the extractor only parses the source files.

```bash
cd study/RoslynExtract && dotnet restore && cd ../..
dotnet run -c Release --project study/RoslynExtract -- repos study/methods.jsonl
```

The program walks every `*.cs` file of every repository (skipping `obj/` and `bin/`) and writes one JSON line per type declaration (with its base types, used to resolve inherited tests) and one per test method. A method is a test method if it has one of the attributes `Fact`, `Theory`, `Test`, `TestCase`, `TestCaseSource`, `TestMethod`, `DataTestMethod`, or a name ending in `Fact` or `Theory`. For each test method it records:

- `tokens`: all identifier and keyword tokens of the method, **including attribute tokens**; literals and comments are not tokens, so they are excluded,
- `tokens_noattr`: the same tokens without those inside attribute lists (sensitivity analysis),
- `tokens_hop1`: `tokens` plus the tokens of helper methods that the test calls (non-test methods in test paths, at most 5 helpers per test, only when a name has at most 3 candidate definitions),
- `loc` (non-blank lines), `awaits`, `asserts` (calls to `Assert`, `Should` or `Verify`), `isAsync`, `attrs`, `file`.

It prints `<n> test methods; <m> com ao menos um auxiliar resolvido` ("with at least one helper resolved").

### 6.4 Join labels and features into the dataset

```bash
python study/build_dataset.py
```

This maps each labeled case to its declaring method, following base classes for inherited tests, and combines the labels of all cases of the same declaring method. It writes `study/dataset.csv` and `study/unmatched.csv`. **Expected output** (reproduced from the shipped files):

```
metodos Roslyn: 26437 duplicados ignorados: 41
...
unidades (metodos declarados): 12797 | flaky 100x: 30 | flaky manual: 19 | unidades flaky com instancias discordantes: 8
sem casamento: 765 | flaky 100x sem casamento: 0
```

`dataset.csv` produced this way holds the same values as the shipped file (a byte comparison can differ only because of the byte-order mark and line endings; a `pandas` comparison is equal).

Then run Section 5 again on the regenerated files.

---

## 7. Level C: run the test suites again

This level produces **new data**. Do not expect the same flaky tests.

### 7.1 Scripts

| Script | When to use it |
|---|---|
| `scripts/run_repeated.ps1 -CsprojPath <csproj> -OutDir <dir> [-Framework <tfm>] [-Runs 100]` | Default. Builds once in Release, then runs `dotnet test --no-build --logger trx` N times, with `--blame-hang-timeout 5m` |
| `scripts/run_repeated_v2.ps1 -CsprojPath <csproj> -OutDir <dir> -Framework <tfm> [-Runs 100] [-StartAt 1] [-ResetDir <dir>] [-ResetWaitSeconds 15]` | Same, with the option to resume (`-StartAt`) and to restart a `docker compose` stack between runs (`-ResetDir`) |
| `scripts/run_repeated_mtp.ps1 -TestDllPath <dll> -OutDir <dir> [-Runs 100]` | For test projects that run on the Microsoft Testing Platform (for example xUnit v3), which are executed directly as a program with `--report-trx` |

Example (100-run round):

```powershell
.\study\run_repeated.ps1 -CsprojPath repos\serilog\test\Serilog.Tests\Serilog.Tests.csproj `
                         -OutDir results\automated-runs\serilog_runs -Runs 100
```

Example (20-run round; the exact command used originally is not recorded, so this is an equivalent):

```powershell
.\study\run_repeated.ps1 -CsprojPath repos\serilog\test\Serilog.Tests\Serilog.Tests.csproj `
                         -OutDir results\automated-runs\serilog_manual_runs -Runs 20
```

Use the folder names listed in `study/projects.csv` for `-OutDir`, or edit that file.

### 7.2 Conditions of the original runs

- 100-run round: executed in July 2026 (ArchUnitNET in September), with an earlier SDK whose version was not recorded.
- 20-run round: executed between 27 September and 2 October 2026, under isolation. The package does not contain the script or procedure used for this round (see section 10); the example above is the closest equivalent.
- Each repository ran with the SDK that its `global.json` resolves (10.0.401, 10.0.303, 10.0.112 or 8.0.425).
- Nerdbank.Streams in the 20-run round was run on `net472` (folder `nerdbank_streams_manual_runs_net472`).
- Several suites contain integration tests that need Docker (Testcontainers, RabbitMQ). Any other process using the same ports or containers on the machine can create spurious failures. This is the reason StackExchange.Redis and SSH.NET were excluded.
- Because of the non-determinism, a new round will produce a different flaky set. In our own comparison of the 100-run and the 20-run rounds, only 13 of 36 flaky units appeared in both (Jaccard index 0.36). Expect a similar spread across repeated rounds, and compare your conclusions (ranking of models, direction of the signal) rather than exact counts.

After the runs finish, continue at section 6.2.

---

## 8. Mapping from the paper to the scripts

Table numbers below follow the current draft and may change in the submitted version.

| Paper element | Command | Output file |
|---|---|---|
| Table 2 (projects, flaky counts, unit counts) | `summarize.py` | console |
| Table 3 (cross-validation) | `model.py --label auto` | `out_auto/cv_summary.csv` |
| Table 4 (LOPO) | `model.py --label auto` | `out_auto/lopo_summary.csv` |
| Table 5 and Figure 3 (per repository) | `model.py --label auto` | `out_auto/lopo_groups.csv` |
| Tables 6 and 7 (100-run against 20-run labels) | `model.py --label manual` | `out_manual/*` |
| Tables 8 and 9 (tokens, rare markers) | `vocab.py` | `out_auto/vocabulary.csv` |
| Table 10 (position of flaky tests in the ranking) | `rq4.py` | `out_auto/rq4_units.csv` |
| Table 11 (sensitivity) | `model.py ... --tag _noattr` and `--tag _hop1` | `out_auto_noattr/*`, `out_auto_hop1/*` |

The shipped `results/` folder holds the outputs we obtained, so you can compare your own files against them directly.

Fixed settings, all in the scripts: random seed 42; Random Forest and Extra Trees with 200 trees and `class_weight="balanced"`; TF-IDF with unigrams and bigrams, `min_df=2`, `max_df=0.9`, sublinear term frequency; a short list of C# keywords and modifiers removed before vectorization (`STOP` in `model.py`); KNN with k=5 and cosine distance; LinearSVC for the SVM; the vocabulary-threshold baseline flags a unit that contains any of the 10 tokens with the highest mutual information on the training fold.

---

## 9. Troubleshooting

| Symptom | Likely cause |
|---|---|
| `FileNotFoundError: study/projects.csv` or `study/dataset.csv` | The command was run from the wrong folder, or the files were not copied into `study/` (section 4) |
| `unidades` is not 12665 / flaky is not 30 | `dataset.csv` or `projects.csv` is not the one from the package, or `--label` is wrong |
| `FileNotFoundError` in `rq4.py` when saving `rq4_units.csv` | `study/out_auto/` does not exist yet. Run `model.py --label auto` first, or create the folder |
| Numbers differ in the second decimal | Different `scikit-learn`, `numpy` or `pandas` versions. Install the pinned versions in `requirements.txt` |
| `export_labels.py` prints fewer runs than expected for a project | The TRX folder name does not match `projects.csv`, or `trx.zip` was extracted one level too deep |
| `export_labels.py` counts a different number of methods | Test names containing local paths were sanitized in the shared TRX files (a few parameterized NLog tests). Use the shipped TRX, not your own, if you want to match the shipped labels |
| `build_dataset.py` reports many more unmatched methods | `repos/` folders are not at the manifest commits, or a folder name differs from `repo_dir` |
| `dotnet run` fails for `RoslynExtract` | SDK 10 is not installed (`dotnet --list-sdks`) |
| A suite does not build when you re-run it (Level C) | The SDK resolved by the repository's `global.json` is missing, or a package audit warning is treated as an error. We built with `-p:NuGetAudit=false` in `run_repeated_v2.ps1` |
| A suite finishes with zero TRX files | The project uses the Microsoft Testing Platform. Use `run_repeated_mtp.ps1` |

---

## 10. Known limits of the package

State these when you cite the package, so that nobody expects more reproducibility than it offers.

- Level C cannot recreate the exact flaky set (non-determinism).
- The SDK of the 100-run round was not recorded.
- The package does not store which test project and target framework were run for each TRX folder, nor the commands used for the 20-run (isolated) round. The folder names in `projects.csv` and the three run scripts are the only record.
- The sources of the studied projects are not redistributed; use the manifest.
- The labeled data has only 30 positive units, 20 of them in three repositories (StreamJsonRpc 8, MassTransit 6, Nerdbank.Streams 6), so results at the repository level rest on very few positives.

---

## 11. Licenses and citation

Code: MIT. Data: CC BY 4.0. Cite the package through `CITATION.cff` (the author and DOI fields still hold placeholders; see below).
