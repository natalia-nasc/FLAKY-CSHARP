#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_study.py - Linux (Docker) version of run_study.ps1.

Implements the data-collection process of section 5 of REPLICACAO.md, reading
the same CSV:

  CSV validation -> repository preparation (clone at the pinned commit,
  submodules, setup/<repo>.ps1) -> build -> N runs, one TRX per run ->
  labels_csv.py -> summary.

There is a single round per suite (the "manual" round of the .ps1 was removed).
N is asked at startup (Enter accepts 100) unless it is given on the command line.

Accepts the same parameters as the .ps1 (PowerShell or GNU style):

  run_study.py                         # uses suites.csv and asks for N
  run_study.py -Csv suites2.csv
  run_study.py -Smoke                  # 1 run per suite (does not ask)
  run_study.py -Only cmg_              # only suites/repos whose name contains "cmg_"
  run_study.py -SkipBuild              # do not rebuild
  run_study.py -AutoRuns 50            # do not ask (required without a terminal); -Runs also works

Folders:
  input (CSV, setup/, labels_csv.py)  -> --input-dir or $STUDY_INPUT
  work  (repos/, results/, logs/)     -> --work-dir  or $STUDY_WORK
  If neither is given, both are this script's folder (like $PSScriptRoot in
  the .ps1).
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import os
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

RUNNERS = ("vstest", "mtp", "mtp-xunit", "xunit3")
DLL_RUNNERS = ("mtp", "mtp-xunit", "xunit3")
COLUMNS = ("repo", "url", "commit", "suite", "project", "runner",
           "framework", "config", "build_props", "env", "timeout_min")
REQUIRED = COLUMNS[:6]
# summary.csv: same columns, order and quoting as the summary written by
# run_study.ps1, so both can be read by the same analysis scripts.
# "rodada" holds the number of runs of the round (e.g. 100), as in the .ps1.
SUMMARY_COLUMNS = ("repo", "suite", "rodada", "status", "trx", "distintos",
                   "stable", "flaky", "broken", "skipped")
# Wait before retrying a failed repository preparation (section 5.5, step 2).
RETRY_WAIT_S = float(os.environ.get("STUDY_RETRY_WAIT_S", "30"))


# --------------------------------------------------------------------------
# Utilities
# --------------------------------------------------------------------------

class Interrupted(Exception):
    """SIGTERM (docker stop) or SIGINT (Ctrl+C)."""


def _on_signal(signum, _frame):
    raise Interrupted(signal.Signals(signum).name)


class Log:
    """Writes to the terminal and to logs/run_study.log."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = open(path, "a", encoding="utf-8")

    def __call__(self, msg: str = "") -> None:
        print(msg, flush=True)
        self._f.write(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S}  {msg}\n")
        self._f.flush()


def _children_map() -> dict[int, list[int]]:
    tree: dict[int, list[int]] = {}
    proc = Path("/proc")
    if not proc.is_dir():
        return tree
    for p in proc.iterdir():
        if not p.name.isdigit():
            continue
        try:
            stat = (p / "stat").read_text()
            ppid = int(stat.rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            continue
        tree.setdefault(ppid, []).append(int(p.name))
    return tree


def kill_tree(proc: subprocess.Popen) -> None:
    """Kills the process and all its descendants (like taskkill /T /F)."""
    tree = _children_map()
    pids, stack = [], [proc.pid]
    while stack:
        for child in tree.get(stack.pop(), []):
            pids.append(child)
            stack.append(child)
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    for pid in pids:  # descendants that left the process group (setsid)
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    try:
        proc.wait(timeout=30)
    except subprocess.TimeoutExpired:
        pass


def run_logged(cmd, cwd, env, out_path: Path, err_path: Path | None = None,
               timeout_s: float | None = None) -> tuple[int | None, bool]:
    """Runs cmd with its output written to file(s). Returns (exit_code, timed_out)."""
    out = open(out_path, "wb")
    err = open(err_path, "wb") if err_path else subprocess.STDOUT
    try:
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, start_new_session=True)
        except OSError as e:
            out.write(f"could not run {cmd[0]}: {e}\n".encode())
            return 127, False
        try:
            return proc.wait(timeout=timeout_s), False
        except subprocess.TimeoutExpired:
            kill_tree(proc)
            return None, True
        except BaseException:
            kill_tree(proc)
            raise
    finally:
        out.close()
        if err_path:
            err.close()


def run_capture(cmd, cwd=None, env=None, timeout_s=None) -> tuple[int | None, str, str]:
    try:
        p = subprocess.run(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                           capture_output=True, text=True, errors="replace",
                           timeout=timeout_s)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode(errors="replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        return None, out, "timed out"
    except OSError as e:
        return 127, "", str(e)


def resolve_ci(base: Path, rel: str) -> Path | None:
    """Resolves a CSV path (with Windows \\ separators), ignoring letter case."""
    rel = rel.replace("\\", "/").strip().strip("/")
    direct = base / rel
    if direct.exists():
        return direct
    cur = base
    for part in rel.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            cur = cur.parent
            continue
        nxt = cur / part
        if not nxt.exists():
            try:
                nxt = next((c for c in cur.iterdir() if c.name.lower() == part.lower()), None)
            except OSError:
                nxt = None
            if nxt is None:
                return None
        cur = nxt
    return cur


def find_ci(folder: Path, name: str) -> Path | None:
    if not folder.is_dir():
        return None
    exact = folder / name
    if exact.is_file():
        return exact
    return next((c for c in folder.iterdir()
                 if c.is_file() and c.name.lower() == name.lower()), None)


def count_trx(folder: Path) -> int:
    return len(list(folder.glob("*.trx"))) if folder.is_dir() else 0


def read_text_any(path: Path) -> str:
    data = path.read_bytes()
    for enc in ("utf-8-sig", "cp1252"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1")


# --------------------------------------------------------------------------
# CSV (section 5.3)
# --------------------------------------------------------------------------

@dataclass
class Suite:
    line: int
    repo: str
    url: str
    commit: str
    suite: str
    project: str
    runner: str
    framework: str = ""
    config: str = "Release"
    build_props: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    timeout_min: float = 60.0


def load_csv(path: Path) -> tuple[list[Suite], list[str]]:
    reader = csv.reader(io.StringIO(read_text_any(path), newline=""))
    header: list[str] | None = None
    suites: list[Suite] = []
    errors: list[str] = []
    for rec in reader:
        line = reader.line_num
        cells = [c.strip() for c in rec]
        if not cells or not any(cells):
            continue
        if cells[0].startswith("#"):          # disabled row / comment
            continue
        if header is None:
            if cells[0].lower() == "repo":
                header = [c.lower() for c in cells]
                continue
            header = list(COLUMNS)            # no header: column order of section 5.3
        d = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}
        for c in COLUMNS:
            d.setdefault(c, "")

        missing = [c for c in REQUIRED if not d[c]]
        if missing:
            errors.append(f"line {line}: empty required column(s): {', '.join(missing)}")
            continue
        if d["runner"] not in RUNNERS:
            errors.append(f"line {line}: unknown runner '{d['runner']}' "
                          f"(valid: {', '.join(RUNNERS)})")
            continue

        env: dict[str, str] = {}
        bad_env = False
        for item in d["env"].split(";"):
            item = item.strip()
            if not item:
                continue
            name, sep, value = item.partition("=")
            if not sep or not name.strip():
                errors.append(f"line {line}: invalid env '{item}' (use NAME=value;OTHER=value)")
                bad_env = True
                continue
            env[name.strip()] = value
        if bad_env:
            continue

        timeout = 60.0
        if d["timeout_min"]:
            try:
                timeout = float(d["timeout_min"].replace(",", "."))
                if timeout <= 0:
                    raise ValueError
            except ValueError:
                errors.append(f"line {line}: invalid timeout_min '{d['timeout_min']}'")
                continue

        suites.append(Suite(
            line=line, repo=d["repo"], url=d["url"], commit=d["commit"],
            suite=d["suite"], project=d["project"], runner=d["runner"],
            framework=d["framework"], config=d["config"] or "Release",
            build_props=d["build_props"].split(), env=env, timeout_min=timeout))

    seen: dict[str, int] = {}
    commits: dict[str, tuple[str, int]] = {}
    for s in suites:
        if s.suite in seen:
            errors.append(f"line {s.line}: duplicate suite '{s.suite}' (already on line {seen[s.suite]})")
        else:
            seen[s.suite] = s.line
        if s.repo in commits and commits[s.repo][0] != s.commit:
            errors.append(f"line {s.line}: repo '{s.repo}' uses commit {s.commit}, "
                          f"but line {commits[s.repo][1]} uses {commits[s.repo][0]}")
        commits.setdefault(s.repo, (s.commit, s.line))
    return suites, errors


# --------------------------------------------------------------------------
# Study
# --------------------------------------------------------------------------

class Study:
    def __init__(self, args, log: Log):
        self.a = args
        self.log = log
        self.input_dir: Path = args.input_dir
        self.work: Path = args.work_dir
        self.repos = self.work / "repos"
        self.results = self.work / "results"
        self.logs = self.work / "logs"
        self.setup_dir = self.input_dir / "setup"
        self.labels_script: Path = args.labels_script
        self.repo_state: dict[str, tuple[bool, str]] = {}
        self.summary: list[dict] = []
        self.summary_path = self.results / ("summary_smoke.csv" if args.smoke else "summary.csv")

    # ---------------- environment ----------------

    def base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("CI", None)
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    def write_environment(self) -> None:
        """Records the collection environment (like the table in section 4)."""
        def cmd(*c):
            rc, out, err = run_capture(list(c), timeout_s=120)
            return (out or err).strip()

        mem = ""
        try:
            for line in Path("/proc/meminfo").read_text().splitlines():
                if line.startswith("MemTotal"):
                    mem = line.split(":", 1)[1].strip()
        except OSError:
            pass
        cg = ""
        for f in ("/sys/fs/cgroup/memory.max", "/sys/fs/cgroup/cpu.max"):
            try:
                cg += f"{f}: {Path(f).read_text().strip()}\n"
            except OSError:
                pass
        try:
            ncpu = len(os.sched_getaffinity(0))
        except AttributeError:
            ncpu = os.cpu_count()
        os_name = ""
        try:
            os_name = next((l.split("=", 1)[1].strip('"') for l in
                            Path("/etc/os-release").read_text().splitlines()
                            if l.startswith("PRETTY_NAME=")), "")
        except OSError:
            pass
        text = "\n".join(l for l in [
            f"date: {dt.datetime.now().isoformat(timespec='seconds')}",
            f"system: {os_name} | {platform.platform()} | {platform.machine()}",
            f"cpus: {ncpu}",
            f"memory: {mem}",
            cg.rstrip() or None,
            f"python: {sys.version.split()[0]}",
            f"git: {cmd('git', '--version')} | {cmd('git', 'lfs', 'version')}",
            f"pwsh: {cmd('pwsh', '-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()')}",
            f"LANG={os.environ.get('LANG', '')} LC_ALL={os.environ.get('LC_ALL', '')} "
            f"TZ={os.environ.get('TZ', '')}",
            f"csv: {self.a.csv}",
            ("runs: smoke (1)" if self.a.smoke else f"runs per suite: {self.a.auto_runs}"),
            "",
            "--- dotnet --info ---",
            cmd("dotnet", "--info"),
            "",
        ] if l is not None)
        (self.results / "environment.txt").write_text(text, encoding="utf-8")

    # ---------------- repository (section 5.5, step 2) ----------------

    def ensure_repo(self, s: Suite) -> tuple[bool, str]:
        if s.repo not in self.repo_state:
            self.repo_state[s.repo] = self.prepare_repo(s)
        return self.repo_state[s.repo]

    def prepare_repo(self, s: Suite) -> tuple[bool, str]:
        repo_dir = self.repos / s.repo
        logp = self.logs / "_repos" / f"{s.repo}.log"
        logp.parent.mkdir(parents=True, exist_ok=True)
        msg = ""
        for attempt in (1, 2):
            with open(logp, "a", encoding="utf-8") as lf:
                lf.write(f"\n===== {dt.datetime.now():%Y-%m-%d %H:%M:%S} attempt {attempt} =====\n")
                ok, msg, clone_failed = self._prepare_once(s, repo_dir, lf)
            if ok:
                return True, ""
            self.log(f"  repo {s.repo}: {msg} (attempt {attempt}; details in {logp})")
            if attempt == 1:
                if clone_failed and repo_dir.exists():
                    shutil.rmtree(repo_dir, ignore_errors=True)
                time.sleep(RETRY_WAIT_S)
        return False, msg

    def _git(self, args, cwd, lf) -> tuple[int | None, str]:
        rc, out, err = run_capture(["git", *args], cwd=cwd, env=self.base_env())
        lf.write(f"$ git {' '.join(args)}\n{out}{err}[rc={rc}]\n")
        return rc, out.strip()

    def _prepare_once(self, s: Suite, repo_dir: Path, lf) -> tuple[bool, str, bool]:
        if not (repo_dir / ".git").exists():
            if repo_dir.exists():
                shutil.rmtree(repo_dir, ignore_errors=True)
            self.log(f"  git clone {s.url}")
            rc, _ = self._git(["clone", s.url, str(repo_dir)], self.repos, lf)
            if rc != 0:
                return False, "clone failed", True

        rc, head = self._git(["rev-parse", "HEAD"], repo_dir, lf)
        rc, target = self._git(["rev-parse", "--verify", "--quiet", f"{s.commit}^{{commit}}"], repo_dir, lf)
        if rc != 0:
            self._git(["fetch", "origin", s.commit], repo_dir, lf)
            rc, target = self._git(["rev-parse", "--verify", "--quiet", f"{s.commit}^{{commit}}"], repo_dir, lf)
            if rc != 0:
                self._git(["fetch", "--tags", "origin"], repo_dir, lf)
                rc, target = self._git(["rev-parse", "--verify", "--quiet", f"{s.commit}^{{commit}}"], repo_dir, lf)
                if rc != 0:
                    return False, f"commit {s.commit} not found", False

        if head != target:
            rc, dirty = self._git(["status", "--porcelain", "--untracked-files=no"], repo_dir, lf)
            if dirty:
                return False, ("local changes to tracked files and HEAD at another commit; "
                               "checkout skipped"), False
            self.log(f"  git checkout {s.commit}")
            rc, _ = self._git(["-c", "advice.detachedHead=false", "checkout", target], repo_dir, lf)
            if rc != 0:
                return False, "checkout failed", False

        if (repo_dir / ".gitmodules").exists():
            rc, _ = self._git(["submodule", "update", "--init", "--recursive"], repo_dir, lf)
            if rc != 0:
                return False, "submodule update failed", False

        ok, msg = self.run_setup(s.repo, repo_dir, lf)
        return ok, msg, False

    def run_setup(self, repo: str, repo_dir: Path, lf) -> tuple[bool, str]:
        """Runs setup/<repo>.sh (bash) if present; otherwise setup/<repo>.ps1 (pwsh). In the repo folder.

        The .sh is optional: it replaces, on Linux only, a .ps1 that depends on Windows.
        """
        env = self.base_env()
        sh = find_ci(self.setup_dir, f"{repo}.sh")
        ps1 = None if sh else find_ci(self.setup_dir, f"{repo}.ps1")
        if ps1:
            self.log(f"  setup {ps1.name} (pwsh)")
            rc, out, err = run_capture(["pwsh", "-NoProfile", "-NonInteractive",
                                        "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                                       cwd=repo_dir, env=env)
            lf.write(f"$ pwsh -File {ps1}\n{out}{err}[rc={rc}]\n")
            if rc != 0:
                return False, f"setup {ps1.name} failed (rc={rc})"
        if sh:
            self.log(f"  setup {sh.name} (bash; replaces the .ps1)")
            # strip CRLF, in case the file was edited on Windows
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as t:
                t.write(read_text_any(sh).replace("\r\n", "\n"))
            try:
                rc, out, err = run_capture(["bash", t.name], cwd=repo_dir, env=env)
            finally:
                os.unlink(t.name)
            lf.write(f"$ bash {sh}\n{out}{err}[rc={rc}]\n")
            if rc != 0:
                return False, f"setup {sh.name} failed (rc={rc})"
        return True, ""

    # ---------------- suite (section 5.5, step 3) ----------------

    def suite_env(self, s: Suite) -> dict[str, str]:
        env = self.base_env()
        env.update(s.env)
        return env

    def build(self, s: Suite, proj: Path, repo_dir: Path, env, log_dir: Path) -> bool:
        cmd = ["dotnet", "build", str(proj), "-c", s.config]
        if s.framework:
            cmd += ["-f", s.framework]
        cmd += ["-p:NuGetAudit=false", "-p:TreatWarningsAsErrors=false", *s.build_props]
        blog = log_dir / "build.log"
        timeout = self.a.build_timeout_min * 60 if self.a.build_timeout_min > 0 else None
        for attempt in (1, 2):
            self.log(f"  build ({s.config}{', ' + s.framework if s.framework else ''})"
                     f"{' - retrying' if attempt == 2 else ''}")
            rc, timed_out = run_logged(cmd, repo_dir, env, blog, None, timeout)
            if rc == 0:
                return True
            if attempt == 1:
                run_capture(["dotnet", "build-server", "shutdown"], cwd=repo_dir, env=env, timeout_s=300)
        lines, seen = [], set()
        for line in blog.read_text(encoding="utf-8", errors="replace").splitlines():
            if re.search(r"\berror\b", line, re.I) and line.strip() not in seen:
                seen.add(line.strip())
                lines.append(line.strip())
        for line in lines[:10]:
            self.log(f"    {line[:300]}")
        return False

    def target_path(self, s: Suite, proj: Path, repo_dir: Path, env) -> tuple[Path | None, str]:
        cmd = ["dotnet", "msbuild", str(proj), "-getProperty:TargetPath", f"-p:Configuration={s.config}"]
        if s.framework:
            cmd.append(f"-p:TargetFramework={s.framework}")
        cmd += s.build_props
        rc, out, err = run_capture(cmd, cwd=repo_dir, env=env, timeout_s=900)
        lines = [l.strip() for l in out.splitlines() if l.strip()]
        if rc != 0 or not lines:
            return None, (err or out).strip()[-300:]
        return Path(lines[-1]), ""

    def run_command(self, s: Suite, proj: Path, dll: Path | None, rdir: Path, i: int) -> list[str]:
        name = f"run_{i}.trx"
        if s.runner == "vstest":
            cmd = ["dotnet", "test", str(proj), "-c", s.config]
            if s.framework:
                cmd += ["-f", s.framework]
            return cmd + ["--no-build", "--logger", f"trx;LogFileName={name}",
                          "--results-directory", str(rdir), *s.build_props]
        if s.runner == "mtp":
            return ["dotnet", str(dll), "--report-trx", "--report-trx-filename", name,
                    "--results-directory", str(rdir)]
        if s.runner == "mtp-xunit":
            return ["dotnet", str(dll), "--report-xunit-trx", "--report-xunit-trx-filename", name,
                    "--results-directory", str(rdir)]
        return ["dotnet", str(dll), "-result-trx", str(rdir / name)]  # xunit3

    def run_round(self, s: Suite, kind: str, rdir: Path, n: int, proj: Path,
                  dll: Path | None, cwd: Path, env, log_dir: Path) -> str:
        rdir.mkdir(parents=True, exist_ok=True)
        timeout_s = s.timeout_min * 60
        for i in range(1, n + 1):
            trx = rdir / f"run_{i}.trx"
            if trx.exists():
                continue
            for attempt in (1, 2):
                t0 = time.monotonic()
                try:
                    rc, timed_out = run_logged(self.run_command(s, proj, dll, rdir, i), cwd, env,
                                               log_dir / "last.out", log_dir / "last.err", timeout_s)
                except BaseException:
                    trx.unlink(missing_ok=True)       # possibly partial TRX
                    raise
                secs = time.monotonic() - t0
                if timed_out:
                    trx.unlink(missing_ok=True)
                if trx.exists():
                    self.log(f"  {kind} {i}/{n}  rc={rc}  {secs:.0f}s")
                    break
                why = (f"timed out ({s.timeout_min:g} min)" if timed_out
                       else f"no TRX (rc={rc})")
                if attempt == 1:
                    self.log(f"  {kind} {i}/{n}  {why}; retrying run {i}")
                else:
                    self.log(f"  {kind} {i}/{n}  {why}; stopping this suite (see {log_dir}/last.*)")
                    return f"ERROR: run {i} produced no TRX"
        return "OK"

    def labels(self, s: Suite, kind: str, n: int, rdir: Path, out_csv: Path) -> dict:
        rc, out, err = run_capture([sys.executable, str(self.labels_script), str(rdir), str(out_csv)],
                                   cwd=self.input_dir, timeout_s=3600)
        stats: dict = {}
        # labels_csv.py prints its summary in Portuguese (see section 2.3)
        for line in out.splitlines():
            m = re.match(r"\s*([^:]+?)\s*:\s*(\d+)\s*$", line)
            if not m:
                continue
            key, val = m.group(1).lower(), int(m.group(2))
            if key.startswith(("execucoes", "execuções")):
                stats["trx"] = val
            elif key.startswith("testes distintos"):
                stats["distintos"] = val
            elif key in ("stable", "flaky", "broken", "skipped"):
                stats[key] = val
        if rc != 0:
            self.log(f"  labels ({kind}) failed (rc={rc}): {(err or out).strip()[-300:]}")
            return self.row(s, n, "ERROR: labels", rdir)
        self.log(f"  labels ({kind}) -> {out_csv.name}: "
                 f"trx={stats.get('trx', '?')}  distinct={stats.get('distintos', '?')}  " +
                 "  ".join(f"{k}={stats.get(k, '?')}" for k in ("stable", "flaky", "broken", "skipped")))
        return self.row(s, n, "OK", rdir, stats)

    @staticmethod
    def row(s: Suite, n: int, status: str, rdir: Path, stats: dict | None = None) -> dict:
        stats = stats or {}
        r = {"repo": s.repo, "suite": s.suite, "rodada": str(n), "status": status,
             "trx": stats.get("trx", count_trx(rdir))}
        for k in SUMMARY_COLUMNS[5:]:
            r[k] = stats.get(k, 0)          # 0 when there is nothing to count, as in the .ps1
        return r

    def process(self, s: Suite) -> None:
        a = self.a
        log_dir = self.logs / s.suite
        log_dir.mkdir(parents=True, exist_ok=True)
        auto_dir = self.results / "automated-runs" / f"{s.suite}_runs"
        if a.smoke:
            rounds = [("smoke", auto_dir, 1, self.results / f"{s.suite}_smoke_labels.csv")]
        else:
            rounds = [("auto", auto_dir, a.auto_runs, self.results / f"{s.suite}_labels.csv")]

        self.log("")
        self.log(f"=== {s.suite}  [{s.repo} | {s.runner}{' | ' + s.framework if s.framework else ''}] ===")

        def fail_all(status: str) -> None:
            self.log(f"  {status}")
            for _, rdir, n, _ in rounds:
                self.summary.append(self.row(s, n, status, rdir))

        for kind, rdir, n, _ in rounds:
            if count_trx(rdir) > n:
                self.log(f"  warning: {rdir.name} already has {count_trx(rdir)} TRX files, more than the "
                         f"{n} requested; the labels ({kind}) use every TRX in the folder")

        # 1. suite already complete: only regenerate the labels
        if all(count_trx(rdir) >= n for _, rdir, n, _ in rounds):
            self.log("  suite complete; only regenerating the labels")
            for kind, rdir, n, out_csv in rounds:
                self.summary.append(self.labels(s, kind, n, rdir, out_csv))
            return

        ok, msg = self.ensure_repo(s)
        if not ok:
            return fail_all(f"ERROR: repo ({msg})")
        repo_dir = self.repos / s.repo
        proj = resolve_ci(repo_dir, s.project)
        if proj is None:
            return fail_all(f"ERROR: project not found ({s.project})")

        # 2. suite environment variables (only for this suite's processes)
        env = self.suite_env(s)

        # 3. build
        if not a.skip_build and not self.build(s, proj, repo_dir, env, log_dir):
            return fail_all("ERROR: build")

        # 4. DLL
        dll = None
        if s.runner in DLL_RUNNERS:
            dll, why = self.target_path(s, proj, repo_dir, env)
            if dll is None or not dll.is_file():
                return fail_all(f"ERROR: DLL not found ({dll or why})")
        cwd = dll.parent if (dll is not None and a.run_cwd == "dll") else repo_dir

        # 5-6. runs and labels
        for idx, (kind, rdir, n, out_csv) in enumerate(rounds):
            status = self.run_round(s, kind, rdir, n, proj, dll, cwd, env, log_dir)
            if status != "OK":
                self.summary.append(self.row(s, n, status, rdir))
                for _, rdir2, n2, _ in rounds[idx + 1:]:
                    self.summary.append(self.row(s, n2, "not run", rdir2))
                return
            self.summary.append(self.labels(s, kind, n, rdir, out_csv))

    def write_summary(self) -> None:
        self.results.mkdir(parents=True, exist_ok=True)
        with open(self.summary_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS, quoting=csv.QUOTE_ALL)
            w.writeheader()
            w.writerows(self.summary)

    def print_summary(self) -> None:
        if not self.summary:
            return
        rows = [SUMMARY_COLUMNS] + [tuple(str(r[c]) for c in SUMMARY_COLUMNS) for r in self.summary]
        widths = [max(len(r[i]) for r in rows) for i in range(len(SUMMARY_COLUMNS))]
        self.log("")
        self.log("SUMMARY")
        for r in rows:
            self.log("  ".join(v.ljust(widths[i]) for i, v in enumerate(r)).rstrip())
        self.log(f"(saved to {self.summary_path})")


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------

_OPTIONS = {
    "csv": "--csv", "only": "--only", "smoke": "--smoke", "skipbuild": "--skip-build",
    "autoruns": "--auto-runs", "runs": "--auto-runs",
    "inputdir": "--input-dir", "workdir": "--work-dir", "labelsscript": "--labels-script",
    "buildtimeoutmin": "--build-timeout-min", "runcwd": "--run-cwd",
    "help": "--help", "h": "--help", "?": "--help",
}


def normalize_argv(argv: list[str]) -> list[str]:
    """Accepts -Csv, -SkipBuild etc. (PowerShell style, case-insensitive)."""
    out = []
    for arg in argv:
        if arg.startswith("-") and len(arg) > 1:
            name, sep, value = arg.lstrip("-").partition("=")
            key = name.replace("-", "").replace("_", "").lower()
            if key in _OPTIONS:
                out.append(_OPTIONS[key])
                if sep:
                    out.append(value)
                continue
        out.append(arg)
    return out


def parse_args(argv: list[str]):
    here = Path(__file__).resolve().parent
    p = argparse.ArgumentParser(
        prog="run_study.py",
        description="Flaky-test data collection (Linux version of run_study.ps1).")
    p.add_argument("--csv", default="suites.csv", help="file with the list of suites (default: suites.csv)")
    p.add_argument("--only", default="", help="only rows whose suite or repo contains this text")
    p.add_argument("--smoke", action="store_true", help="1 run per suite (kept as run_1)")
    p.add_argument("--skip-build", action="store_true", help="do not build; use the existing binaries")
    p.add_argument("--auto-runs", type=int, default=None,
                   help="runs per suite (also -Runs); if omitted, the script asks (suggested: 100)")
    p.add_argument("--input-dir", type=Path, default=Path(os.environ.get("STUDY_INPUT", here)),
                   help="folder with the CSV, setup/ and labels_csv.py")
    p.add_argument("--work-dir", type=Path, default=None,
                   help="folder for repos/, results/ and logs/")
    p.add_argument("--labels-script", type=Path, default=None,
                   help="path to labels_csv.py (default: <input>/labels_csv.py or <input>/scripts/labels_csv.py)")
    p.add_argument("--build-timeout-min", type=float, default=0,
                   help="build time limit in minutes (default 0 = no limit, as in the .ps1)")
    p.add_argument("--run-cwd", choices=("dll", "repo"), default="dll",
                   help="working directory of the mtp/mtp-xunit/xunit3 runners (default: the DLL folder)")
    a = p.parse_args(normalize_argv(argv))
    a.input_dir = a.input_dir.resolve()
    if a.work_dir is None:
        a.work_dir = Path(os.environ.get("STUDY_WORK", a.input_dir))
    a.work_dir = a.work_dir.resolve()
    csv_path = Path(a.csv)
    a.csv = csv_path if csv_path.is_absolute() else (a.input_dir / csv_path)
    if a.labels_script is None:
        a.labels_script = next((c for c in (a.input_dir / "labels_csv.py",
                                            a.input_dir / "scripts" / "labels_csv.py") if c.is_file()),
                               a.input_dir / "labels_csv.py")
    return a


def ask_runs(question: str, suggestion: int, minimum: int) -> int:
    """Asks for a number of runs in the terminal; Enter accepts the suggestion."""
    while True:
        try:
            answer = input(f"{question} [{suggestion}]: ").strip()
        except EOFError:
            raise SystemExit("\nNo answer; nothing was run.")
        if not answer:
            return suggestion
        if answer.isdigit() and int(answer) >= minimum:
            return int(answer)
        print(f"  Please enter a whole number greater than or equal to {minimum}.")


def resolve_runs(a, log: Log) -> str | None:
    """Sets a.auto_runs, from the command line or by asking.

    Returns an error message, or None if everything is fine.
    """
    if a.smoke:
        return None
    if a.auto_runs is not None:
        return None if a.auto_runs >= 1 else "-AutoRuns must be 1 or more"
    if not sys.stdin.isatty():
        return ("there is no terminal to ask for the number of runs; "
                "pass -AutoRuns (or -Runs) on the command line")
    print()
    a.auto_runs = ask_runs("How many runs per suite?", 100, 1)
    log(f"runs per suite chosen: {a.auto_runs}")
    return None


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    a = parse_args(argv)

    for d in ("repos", "results", "logs"):
        (a.work_dir / d).mkdir(parents=True, exist_ok=True)
    log = Log(a.work_dir / "logs" / "run_study.log")
    log("")
    log(f"run_study.py  {' '.join(argv)}")

    # Validation (section 5.5, step 1): nothing runs if something is wrong.
    problems = []
    if not a.csv.is_file():
        problems.append(f"CSV not found: {a.csv}")
    if not a.labels_script.is_file():
        problems.append(f"labels_csv.py not found in {a.input_dir} or {a.input_dir / 'scripts'}")
    for tool in ("dotnet", "git"):
        if shutil.which(tool) is None:
            problems.append(f"'{tool}' is not on the PATH")
    suites: list[Suite] = []
    if a.csv.is_file():
        suites, errors = load_csv(a.csv)
        problems += errors
    if problems:
        for msg in problems:
            log(f"ERROR: {msg}")
        log("Nothing was run.")
        return 2

    if a.only:
        suites = [s for s in suites if a.only.lower() in s.suite.lower() or a.only.lower() in s.repo.lower()]
    if not suites:
        log("No suite selected.")
        return 0

    try:
        problem = resolve_runs(a, log)
    except Interrupted:
        log("\nCancelled; nothing was run.")
        return 130
    if problem:
        log(f"ERROR: {problem}")
        log("Nothing was run.")
        return 2

    if "CI" in os.environ:
        log("CI variable removed from the environment")
        os.environ.pop("CI", None)

    study = Study(a, log)
    study.write_environment()
    mode = "smoke (1 run)" if a.smoke else f"{a.auto_runs} runs per suite"
    log(f"{len(suites)} suite(s) from {a.csv.name}; {mode}; results in {study.results}")

    try:
        for s in suites:
            study.process(s)
            study.write_summary()
    except Interrupted as e:
        log("")
        log(f"Interrupted ({e}). Run the same command again to resume from the next missing run.")
        study.write_summary()
        study.print_summary()
        return 130
    study.write_summary()
    study.print_summary()
    return 1 if any(r["status"].startswith("ERROR") for r in study.summary) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
