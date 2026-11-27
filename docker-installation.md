# Running the data collection with Docker

This guide explains how to run the flaky-test data collection of this study inside a Docker container. The container gives every machine the same toolchain, so the collection does not depend on what is installed on the host.

The image contains:

| Component | Version |
|---|---|
| Base system | Ubuntu 24.04 (x64) |
| .NET SDK | 10.0.403 (includes the .NET and ASP.NET Core 10.0.14 runtimes) |
| .NET 8 runtimes | 8.0.33 (`Microsoft.NETCore.App` and `Microsoft.AspNetCore.App`) |
| Python | 3.14 (runs `labels_csv.py`) |
| Git | 2.43, with Git LFS |
| PowerShell | 7.6 (runs the per-repository `setup/*.ps1` scripts) |

Inside the container, `docker/run_study.py` does the whole collection for every suite listed in a CSV file:

1. clones the project at its pinned commit and applies the repository setup script, if there is one;
2. builds the test project;
3. runs the test suite **N times**, saving one TRX report per run (you choose N);
4. labels every test with `labels_csv.py`: `stable` (always passed), `flaky` (passed and failed), `broken` (failed, never passed) or `skipped` (never ran);
5. writes a summary table.

---

## 1. Requirements

- An x64 machine with a working internet connection (GitHub, NuGet and the Microsoft download servers are used).
- **Windows:** Windows 10/11 with WSL 2 and Docker Desktop. **Linux:** Docker Engine with the Compose plugin. macOS works with Docker Desktop, but on Apple Silicon the image runs under x64 emulation and is much slower.
- Plenty of free disk space. The clones, NuGet packages and build outputs of all suites can take tens of gigabytes.
- Time. A full collection runs every suite N times, one after another, and can take hours or days depending on N.

---

## 2. Install Docker

### Windows

1. Open PowerShell **as Administrator** and install WSL 2, then restart the computer:
   ```powershell
   wsl --install
   ```
2. Download and install **Docker Desktop** from <https://www.docker.com/products/docker-desktop/>. During installation, keep **"Use WSL 2 instead of Hyper-V"** selected.
3. Start Docker Desktop and wait until it shows **"Engine running"**. Docker Desktop must stay open while the collection runs.
4. Check the installation in a normal PowerShell window:
   ```powershell
   docker version
   docker compose version
   ```
5. *(Recommended)* Fix the CPUs and memory available to the container. Test parallelism depends on the number of cores, and that affects flakiness. Create or edit `%UserProfile%\.wslconfig`:
   ```ini
   [wsl2]
   processors=8
   memory=16GB
   ```
   Then run `wsl --shutdown` and restart Docker Desktop. Report these values together with your results.
6. Keep the computer from sleeping during the collection:
   ```powershell
   powercfg /change standby-timeout-ac 0
   ```

### Linux

1. Install Docker Engine and the Compose plugin following <https://docs.docker.com/engine/install/>.
2. Allow your user to run Docker without `sudo`, then log out and back in:
   ```bash
   sudo usermod -aG docker $USER
   ```
3. Check the installation:
   ```bash
   docker version
   docker compose version
   ```

---

## 3. Get the repository

```bash
git clone https://github.com/natalia-nasc/FLAKY-CSHARP.git
cd FLAKY-CSHARP
```

The files used by the Docker collection are:

| File | Purpose |
|---|---|
| `compose.yaml` | how the container is built and started (versions, folders, culture, time zone) |
| `docker/Dockerfile` | the image |
| `docker/run_study.py` | the collection script |
| `suites.csv`, `suites2.csv` | the suites of batches 2 and 3: repository, pinned commit, test project, runner |
| `setup/` | per-repository adjustments applied after cloning |
| `scripts/labels_csv.py` | the labeling script |

`run_study.ps1` is the original Windows script. Docker does not use it.

**Linux only:** create the output folders before the first run, so Docker does not create them as `root`. If your user ID is not 1000, also export it before building:

```bash
mkdir -p results-linux logs-linux
export STUDY_UID=$(id -u)
```

---

## 4. Configure (optional)

The defaults in `compose.yaml` reproduce the original environment. Change them only if you need to.

**Culture and time zone.** Some tests behave differently depending on the culture (number and date formats) and the time zone. The defaults are `pt_BR.UTF-8` and `America/Sao_Paulo`. To override them, set the variables before the commands below:

```powershell
# PowerShell
$env:STUDY_LANG = "en_US.UTF-8"
$env:STUDY_TZ   = "UTC"
```
```bash
# bash
export STUDY_LANG=en_US.UTF-8
export STUDY_TZ=UTC
```

**Versions.** The .NET SDK, .NET 8 runtime and Python versions are the `args` of the `build` section in `compose.yaml`. If you change one, rebuild the image (step 5).

---

## 5. Build the image

From the repository folder:

```bash
docker compose build
```

The first build downloads the SDK, the runtimes, Python and PowerShell, which takes a few minutes. Build again whenever `docker/Dockerfile` or `docker/run_study.py` changes: the script is copied into the image. Later builds are fast.

---

## 6. Run a smoke test

Run every suite **once**, to check that it builds and produces a TRX report:

```bash
docker compose run --rm study -Smoke -Csv suites2.csv
```

When it finishes, a summary table is printed and saved to `results-linux/summary_smoke.csv`. A suite with `ERROR` in the `status` column has a problem; see [Troubleshooting](#10-troubleshooting).

---

## 7. Run the full collection

### Interactive

```bash
docker compose run --rm study -Csv suites2.csv
```

The script asks how many times each suite should run:

```
How many runs per suite? [100]:
```

Type a number and press Enter, or just press Enter to use 100. The script then processes every active suite in the CSV, one after another.

### In the background (recommended for long collections)

In the background there is no terminal to answer the question, so pass the number of runs on the command line with `-Runs` (or `-AutoRuns`):

```bash
docker compose run -d --name collection study -Csv suites2.csv -Runs 100
docker logs -f collection
```

`docker logs -f` shows the progress. Press Ctrl+C to stop watching; the collection keeps running. The same output is also written to `logs-linux/run_study.log`.

### Both batches

`suites2.csv` (batch 3) and `suites.csv` (batch 2) are run separately. Each run of the script **overwrites** `results-linux/summary.csv`, so keep a copy before starting the next batch. The per-suite label files are not overwritten.

```powershell
# PowerShell
Copy-Item results-linux\summary.csv results-linux\summary_suites2.csv
docker rm collection
docker compose run -d --name collection study -Csv suites.csv -Runs 100
```
```bash
# bash
cp results-linux/summary.csv results-linux/summary_suites2.csv
docker rm collection
docker compose run -d --name collection study -Csv suites.csv -Runs 100
```

### Options

| Option | Default | Effect |
|---|---|---|
| `-Csv <file>` | `suites.csv` | CSV with the list of suites |
| `-Runs <N>` / `-AutoRuns <N>` | asked (suggested: 100) | number of runs per suite |
| `-Only <text>` | (all) | only suites or repositories whose name contains the text, e.g. `-Only cmg_` |
| `-Smoke` | off | 1 run per suite; labels go to `*_smoke_labels.csv` |
| `-SkipBuild` | off | do not rebuild; use the existing binaries |
| `--build-timeout-min <M>` | 0 (no limit) | time limit for each build |
| `--run-cwd dll\|repo` | `dll` | working directory of the `mtp`, `mtp-xunit` and `xunit3` runners |

Options are case-insensitive and can also be written GNU style (`--skip-build`, `--auto-runs 100`).

---

## 8. Stop and resume

- **Stop.** Use `docker stop collection` (background) or Ctrl+C (interactive). The run in progress is stopped together with its child processes, and its partial TRX report is deleted.
- **Resume.** Run the same command again, **with the same number of runs**. Runs that already have a `run_<i>.trx` are skipped, and complete suites only have their labels regenerated. The clones are kept in a Docker volume, so nothing is cloned again. In background mode, remove the stopped container first:
  ```bash
  docker rm collection
  docker compose run -d --name collection study -Csv suites2.csv -Runs 100
  ```
- **Change N later.** With a larger N (e.g. 150 after 100), only the missing runs (101–150) are executed. With a smaller N, nothing is deleted: the script prints a warning, and the labels still use every TRX in the folder.

If the computer restarts, start Docker Desktop and resume the same way.

---

## 9. Outputs

```
results-linux/
├── automated-runs/<suite>_runs/run_1.trx ... run_N.trx   one TRX report per run
├── <suite>_labels.csv                                    one line per test, with its label
├── summary.csv                                           one line per suite (summary_smoke.csv with -Smoke)
└── environment.txt                                       system, CPUs, memory, dotnet --info, LANG/TZ, N
logs-linux/
├── <suite>/build.log, last.out, last.err                 build output and output of the last run
├── _repos/<repo>.log                                     git and setup output for each repository
└── run_study.log                                         everything printed on the screen, with timestamps
```

`<suite>_labels.csv` has the columns `className,test,runs_presente,passed,failed,skipped,label`.

`summary.csv` has the same columns, column order and quoting as the summary written by the original Windows script (`run_study.ps1`), so both summaries can be read by the same analysis scripts:

| Column | Meaning |
|---|---|
| `repo` | repository, from the CSV |
| `suite` | suite name, from the CSV |
| `rodada` | number of runs of the round: N (1 with `-Smoke`) |
| `status` | `OK` or `ERROR: ...` (the Windows script writes `ERRO: ...`; a filter on `ERRO*` matches both) |
| `trx` | number of TRX reports |
| `distintos` | number of distinct tests |
| `stable`, `flaky`, `broken`, `skipped` | number of tests with each label (0 when the suite failed) |

The clones and the NuGet cache live in the Docker volumes `flaky-replication_repos` and `flaky-replication_nuget`, not in the repository folder.

---

## 10. Troubleshooting

| Symptom | What to do |
|---|---|
| `error during connect` / `Cannot connect to the Docker daemon` | start Docker Desktop (Windows/macOS) or the Docker service (Linux) |
| `there is no terminal to ask for the number of runs` | add `-Runs <N>` to the command (required with `-d`) |
| `The container name "/collection" is already in use` | remove the old container: `docker rm collection` |
| `permission denied` on `results-linux` (Linux) | create the folders before the first run and build with `STUDY_UID=$(id -u)` (step 3) |
| `ERROR: repo (...)` in the summary | see `logs-linux/_repos/<repo>.log` (clone, checkout or setup failed) |
| `ERROR: build` | see `logs-linux/<suite>/build.log`; the first error lines are also printed on the screen |
| `ERROR: run N produced no TRX` | see `logs-linux/<suite>/last.out` and `last.err` |
| `ERROR: labels` | `labels_csv.py` failed; the message is printed on the screen |
| the first build of each suite is slow | NuGet is downloading packages; they are cached in the `nuget` volume |

To open a shell inside the container and investigate a suite by hand:

```bash
docker compose run --rm --entrypoint bash study
```

---

## 11. Clean up

```bash
docker compose down -v                          # removes the clones and the NuGet cache (keeps results-linux/)
docker image rm flaky-replication:sdk-10.0.403  # removes the image
```

---

## 12. Differences from the original Windows collection

The original collection ran `run_study.ps1` on Windows 11 (see `REPLICACAO.md`). The Docker collection follows the same steps, with these differences:

- **Operating system.** Linux instead of Windows. Windows-only tests (registry, `\` paths, `net*-windows` targets, WinForms/WPF) do not build or end up `broken`. Linux is case-sensitive and uses LF line endings, which can change the outcome of some tests. Treat Docker results as a separate environment, not as a direct continuation of the Windows results.
- **A single round.** Each suite runs N times in one round. The second, independent 20-run round of the original process was removed.
- **Culture, time zone and resources** come from `compose.yaml` and the Docker/WSL settings, not from the host. They are recorded in `results-linux/environment.txt`.

More technical details, in Portuguese, are in [`docker/README.md`](docker/README.md).
