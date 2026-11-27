#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_study.py - versao Linux (Docker) do run_study.ps1.

Implementa o processo da secao 5 do REPLICACAO.md, lendo o mesmo CSV:

  validacao do CSV -> preparacao de cada repositorio (clone no commit fixo,
  submodulos, setup/<repo>.ps1) -> build -> 100 execucoes automaticas e 20
  "manuais" com um TRX por execucao -> labels_csv.py -> resumo.

Aceita os mesmos parametros do .ps1 (no estilo PowerShell ou GNU):

  run_study.py                         # usa suites.csv
  run_study.py -Csv suites2.csv
  run_study.py -Smoke                  # 1 execucao por suite
  run_study.py -Only cmg_              # so suites/repos com "cmg_" no nome
  run_study.py -SkipBuild              # nao recompila
  run_study.py -AutoRuns 100 -ManualRuns 20

Pastas:
  entrada  (CSV, setup/, labels_csv.py)  -> --input-dir ou $STUDY_INPUT
  trabalho (repos/, results/, logs/)     -> --work-dir  ou $STUDY_WORK
  Sem nenhum dos dois, as duas sao a pasta deste script (como o $PSScriptRoot
  do .ps1).
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
SUMMARY_COLUMNS = ("suite", "rodada", "status", "trx", "distintos",
                   "stable", "flaky", "broken", "skipped")
# Espera antes da nova tentativa de preparar um repositorio (secao 5.5, passo 2).
RETRY_WAIT_S = float(os.environ.get("STUDY_RETRY_WAIT_S", "30"))


# --------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------

class Interrupted(Exception):
    """SIGTERM (docker stop) ou SIGINT (Ctrl+C)."""


def _on_signal(signum, _frame):
    raise Interrupted(signal.Signals(signum).name)


class Log:
    """Escreve no terminal e em logs/run_study.log."""

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
    """Encerra o processo e todos os descendentes (equivalente a taskkill /T /F)."""
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
    for pid in pids:  # descendentes que tenham saido do grupo (setsid)
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
    """Executa cmd gravando a saida em arquivo. Retorna (codigo, estourou_tempo)."""
    out = open(out_path, "wb")
    err = open(err_path, "wb") if err_path else subprocess.STDOUT
    try:
        try:
            proc = subprocess.Popen(cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                    stdout=out, stderr=err, start_new_session=True)
        except OSError as e:
            out.write(f"nao foi possivel executar {cmd[0]}: {e}\n".encode())
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
        return None, out, "tempo esgotado"
    except OSError as e:
        return 127, "", str(e)


def resolve_ci(base: Path, rel: str) -> Path | None:
    """Resolve um caminho do CSV (com \\ do Windows) ignorando maiusculas/minusculas."""
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
# CSV (secao 5.3)
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
        if cells[0].startswith("#"):          # linha desativada / comentario
            continue
        if header is None:
            if cells[0].lower() == "repo":
                header = [c.lower() for c in cells]
                continue
            header = list(COLUMNS)            # sem cabecalho: ordem da secao 5.3
        d = {h: (cells[i] if i < len(cells) else "") for i, h in enumerate(header)}
        for c in COLUMNS:
            d.setdefault(c, "")

        missing = [c for c in REQUIRED if not d[c]]
        if missing:
            errors.append(f"linha {line}: coluna(s) obrigatoria(s) vazia(s): {', '.join(missing)}")
            continue
        if d["runner"] not in RUNNERS:
            errors.append(f"linha {line}: runner desconhecido '{d['runner']}' "
                          f"(validos: {', '.join(RUNNERS)})")
            continue

        env: dict[str, str] = {}
        bad_env = False
        for item in d["env"].split(";"):
            item = item.strip()
            if not item:
                continue
            name, sep, value = item.partition("=")
            if not sep or not name.strip():
                errors.append(f"linha {line}: env invalido '{item}' (use NOME=valor;OUTRO=valor)")
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
                errors.append(f"linha {line}: timeout_min invalido '{d['timeout_min']}'")
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
            errors.append(f"linha {s.line}: suite '{s.suite}' repetida (ja aparece na linha {seen[s.suite]})")
        else:
            seen[s.suite] = s.line
        if s.repo in commits and commits[s.repo][0] != s.commit:
            errors.append(f"linha {s.line}: repo '{s.repo}' com commit {s.commit}, "
                          f"mas a linha {commits[s.repo][1]} usa {commits[s.repo][0]}")
        commits.setdefault(s.repo, (s.commit, s.line))
    return suites, errors


# --------------------------------------------------------------------------
# Estudo
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

    # ---------------- ambiente ----------------

    def base_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env.pop("CI", None)
        env["GIT_TERMINAL_PROMPT"] = "0"
        return env

    def write_environment(self) -> None:
        """Registra o ambiente da coleta (equivalente a tabela da secao 4)."""
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
            f"data: {dt.datetime.now().isoformat(timespec='seconds')}",
            f"sistema: {os_name} | {platform.platform()} | {platform.machine()}",
            f"cpus: {ncpu}",
            f"memoria: {mem}",
            cg.rstrip() or None,
            f"python: {sys.version.split()[0]}",
            f"git: {cmd('git', '--version')} | {cmd('git', 'lfs', 'version')}",
            f"pwsh: {cmd('pwsh', '-NoProfile', '-Command', '$PSVersionTable.PSVersion.ToString()')}",
            f"LANG={os.environ.get('LANG', '')} LC_ALL={os.environ.get('LC_ALL', '')} "
            f"TZ={os.environ.get('TZ', '')}",
            f"csv: {self.a.csv}",
            "",
            "--- dotnet --info ---",
            cmd("dotnet", "--info"),
            "",
        ] if l is not None)
        (self.results / "ambiente.txt").write_text(text, encoding="utf-8")

    # ---------------- repositorio (secao 5.5, passo 2) ----------------

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
                lf.write(f"\n===== {dt.datetime.now():%Y-%m-%d %H:%M:%S} tentativa {attempt} =====\n")
                ok, msg, clone_failed = self._prepare_once(s, repo_dir, lf)
            if ok:
                return True, ""
            self.log(f"  repo {s.repo}: {msg} (tentativa {attempt}; detalhes em {logp})")
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
                return False, "clone falhou", True

        rc, head = self._git(["rev-parse", "HEAD"], repo_dir, lf)
        rc, target = self._git(["rev-parse", "--verify", "--quiet", f"{s.commit}^{{commit}}"], repo_dir, lf)
        if rc != 0:
            self._git(["fetch", "origin", s.commit], repo_dir, lf)
            rc, target = self._git(["rev-parse", "--verify", "--quiet", f"{s.commit}^{{commit}}"], repo_dir, lf)
            if rc != 0:
                self._git(["fetch", "--tags", "origin"], repo_dir, lf)
                rc, target = self._git(["rev-parse", "--verify", "--quiet", f"{s.commit}^{{commit}}"], repo_dir, lf)
                if rc != 0:
                    return False, f"commit {s.commit} nao encontrado", False

        if head != target:
            rc, dirty = self._git(["status", "--porcelain", "--untracked-files=no"], repo_dir, lf)
            if dirty:
                return False, ("alteracoes locais em arquivos versionados e HEAD em outro commit; "
                               "checkout nao feito"), False
            self.log(f"  git checkout {s.commit}")
            rc, _ = self._git(["-c", "advice.detachedHead=false", "checkout", target], repo_dir, lf)
            if rc != 0:
                return False, "checkout falhou", False

        if (repo_dir / ".gitmodules").exists():
            rc, _ = self._git(["submodule", "update", "--init", "--recursive"], repo_dir, lf)
            if rc != 0:
                return False, "submodule update falhou", False

        ok, msg = self.run_setup(s.repo, repo_dir, lf)
        return ok, msg, False

    def run_setup(self, repo: str, repo_dir: Path, lf) -> tuple[bool, str]:
        """Roda setup/<repo>.sh (bash) se existir; senao setup/<repo>.ps1 (pwsh). Na pasta do repo.

        O .sh e opcional e serve para substituir, so no Linux, um .ps1 que dependa do Windows.
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
                return False, f"setup {ps1.name} falhou (rc={rc})"
        if sh:
            self.log(f"  setup {sh.name} (bash; substitui o .ps1)")
            # remove CRLF, caso o arquivo tenha sido editado no Windows
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False, encoding="utf-8") as t:
                t.write(read_text_any(sh).replace("\r\n", "\n"))
            try:
                rc, out, err = run_capture(["bash", t.name], cwd=repo_dir, env=env)
            finally:
                os.unlink(t.name)
            lf.write(f"$ bash {sh}\n{out}{err}[rc={rc}]\n")
            if rc != 0:
                return False, f"setup {sh.name} falhou (rc={rc})"
        return True, ""

    # ---------------- suite (secao 5.5, passo 3) ----------------

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
                     f"{' - nova tentativa' if attempt == 2 else ''}")
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
                    trx.unlink(missing_ok=True)       # TRX possivelmente parcial
                    raise
                secs = time.monotonic() - t0
                if timed_out:
                    trx.unlink(missing_ok=True)
                if trx.exists():
                    self.log(f"  {kind} {i}/{n}  rc={rc}  {secs:.0f}s")
                    break
                why = (f"tempo esgotado ({s.timeout_min:g} min)" if timed_out
                       else f"sem TRX (rc={rc})")
                if attempt == 1:
                    self.log(f"  {kind} {i}/{n}  {why}; repetindo a execucao {i}")
                else:
                    self.log(f"  {kind} {i}/{n}  {why}; rodada interrompida (veja {log_dir}/last.*)")
                    return f"ERRO: execucao {i} sem TRX"
        return "OK"

    def labels(self, s: Suite, kind: str, rdir: Path, out_csv: Path) -> dict:
        rc, out, err = run_capture([sys.executable, str(self.labels_script), str(rdir), str(out_csv)],
                                   cwd=self.input_dir, timeout_s=3600)
        stats: dict = {}
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
            self.log(f"  labels ({kind}) falhou (rc={rc}): {(err or out).strip()[-300:]}")
            return self.row(s, kind, "ERRO: labels", rdir)
        self.log(f"  labels ({kind}) -> {out_csv.name}: " +
                 "  ".join(f"{k}={stats.get(k, '?')}" for k in SUMMARY_COLUMNS[3:]))
        return self.row(s, kind, "OK", rdir, stats)

    @staticmethod
    def row(s: Suite, kind: str, status: str, rdir: Path, stats: dict | None = None) -> dict:
        stats = stats or {}
        r = {"suite": s.suite, "rodada": kind, "status": status,
             "trx": stats.get("trx", count_trx(rdir))}
        for k in SUMMARY_COLUMNS[4:]:
            r[k] = stats.get(k, "")
        return r

    def process(self, s: Suite) -> None:
        a = self.a
        log_dir = self.logs / s.suite
        log_dir.mkdir(parents=True, exist_ok=True)
        auto_dir = self.results / "automated-runs" / f"{s.suite}_runs"
        manual_dir = self.results / "manual-runs" / f"{s.suite}_manual_runs"
        if a.smoke:
            rounds = [("smoke", auto_dir, 1, self.results / f"{s.suite}_smoke_labels.csv")]
        else:
            rounds = [("auto", auto_dir, a.auto_runs, self.results / f"{s.suite}_labels.csv"),
                      ("manual", manual_dir, a.manual_runs, self.results / f"{s.suite}_manual_labels.csv")]

        self.log("")
        self.log(f"=== {s.suite}  [{s.repo} | {s.runner}{' | ' + s.framework if s.framework else ''}] ===")

        def fail_all(status: str) -> None:
            self.log(f"  {status}")
            for kind, rdir, _, _ in rounds:
                self.summary.append(self.row(s, kind, status, rdir))

        # 1. suite completa: so gera os labels de novo
        if all(count_trx(rdir) >= n for _, rdir, n, _ in rounds):
            self.log("  suite completa; so os labels sao gerados de novo")
            for kind, rdir, _, out_csv in rounds:
                self.summary.append(self.labels(s, kind, rdir, out_csv))
            return

        ok, msg = self.ensure_repo(s)
        if not ok:
            return fail_all(f"ERRO: repo ({msg})")
        repo_dir = self.repos / s.repo
        proj = resolve_ci(repo_dir, s.project)
        if proj is None:
            return fail_all(f"ERRO: projeto nao encontrado ({s.project})")

        # 2. variaveis de ambiente da suite (so nos processos desta suite)
        env = self.suite_env(s)

        # 3. build
        if not a.skip_build and not self.build(s, proj, repo_dir, env, log_dir):
            return fail_all("ERRO: build")

        # 4. DLL
        dll = None
        if s.runner in DLL_RUNNERS:
            dll, why = self.target_path(s, proj, repo_dir, env)
            if dll is None or not dll.is_file():
                return fail_all(f"ERRO: DLL nao encontrada ({dll or why})")
        cwd = dll.parent if (dll is not None and a.run_cwd == "dll") else repo_dir

        # 5-6. rodadas e labels
        for idx, (kind, rdir, n, out_csv) in enumerate(rounds):
            status = self.run_round(s, kind, rdir, n, proj, dll, cwd, env, log_dir)
            if status != "OK":
                self.summary.append(self.row(s, kind, status, rdir))
                for kind2, rdir2, _, _ in rounds[idx + 1:]:
                    self.summary.append(self.row(s, kind2, "nao executada", rdir2))
                return
            self.summary.append(self.labels(s, kind, rdir, out_csv))

    def write_summary(self) -> None:
        self.results.mkdir(parents=True, exist_ok=True)
        with open(self.summary_path, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=SUMMARY_COLUMNS)
            w.writeheader()
            w.writerows(self.summary)

    def print_summary(self) -> None:
        if not self.summary:
            return
        rows = [SUMMARY_COLUMNS] + [tuple(str(r[c]) for c in SUMMARY_COLUMNS) for r in self.summary]
        widths = [max(len(r[i]) for r in rows) for i in range(len(SUMMARY_COLUMNS))]
        self.log("")
        self.log("RESUMO")
        for r in rows:
            self.log("  ".join(v.ljust(widths[i]) for i, v in enumerate(r)).rstrip())
        self.log(f"(gravado em {self.summary_path})")


# --------------------------------------------------------------------------
# Linha de comando
# --------------------------------------------------------------------------

_OPTIONS = {
    "csv": "--csv", "only": "--only", "smoke": "--smoke", "skipbuild": "--skip-build",
    "autoruns": "--auto-runs", "manualruns": "--manual-runs",
    "inputdir": "--input-dir", "workdir": "--work-dir", "labelsscript": "--labels-script",
    "buildtimeoutmin": "--build-timeout-min", "runcwd": "--run-cwd",
    "help": "--help", "h": "--help", "?": "--help",
}


def normalize_argv(argv: list[str]) -> list[str]:
    """Aceita -Csv, -SkipBuild etc. (estilo PowerShell, sem diferenciar maiusculas)."""
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
        description="Coleta de testes flaky (versao Linux do run_study.ps1).")
    p.add_argument("--csv", default="suites.csv", help="arquivo com a lista de suites (padrao: suites.csv)")
    p.add_argument("--only", default="", help="so as linhas cujo suite ou repo contem o texto")
    p.add_argument("--smoke", action="store_true", help="1 execucao por suite (vale como run_1 da rodada automatica)")
    p.add_argument("--skip-build", action="store_true", help="nao compila; usa os binarios existentes")
    p.add_argument("--auto-runs", type=int, default=100, help="execucoes da rodada automatica (padrao 100)")
    p.add_argument("--manual-runs", type=int, default=20, help="execucoes da rodada 'manual' (padrao 20)")
    p.add_argument("--input-dir", type=Path, default=Path(os.environ.get("STUDY_INPUT", here)),
                   help="pasta com o CSV, setup/ e labels_csv.py")
    p.add_argument("--work-dir", type=Path, default=None,
                   help="pasta onde ficam repos/, results/ e logs/")
    p.add_argument("--labels-script", type=Path, default=None,
                   help="caminho do labels_csv.py (padrao: <entrada>/labels_csv.py ou <entrada>/scripts/labels_csv.py)")
    p.add_argument("--build-timeout-min", type=float, default=0,
                   help="limite do build em minutos (padrao 0 = sem limite, como no .ps1)")
    p.add_argument("--run-cwd", choices=("dll", "repo"), default="dll",
                   help="diretorio de trabalho dos runners mtp/mtp-xunit/xunit3 (padrao: pasta da DLL)")
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


def main(argv: list[str]) -> int:
    signal.signal(signal.SIGTERM, _on_signal)
    signal.signal(signal.SIGINT, _on_signal)
    a = parse_args(argv)

    for d in ("repos", "results", "logs"):
        (a.work_dir / d).mkdir(parents=True, exist_ok=True)
    log = Log(a.work_dir / "logs" / "run_study.log")
    log("")
    log(f"run_study.py  {' '.join(argv)}")

    # Validacao (secao 5.5, passo 1): nada e executado se algo estiver errado.
    problems = []
    if not a.csv.is_file():
        problems.append(f"CSV nao encontrado: {a.csv}")
    if not a.labels_script.is_file():
        problems.append(f"labels_csv.py nao encontrado em {a.input_dir} nem em {a.input_dir / 'scripts'}")
    for tool in ("dotnet", "git"):
        if shutil.which(tool) is None:
            problems.append(f"'{tool}' nao esta no PATH")
    suites: list[Suite] = []
    if a.csv.is_file():
        suites, errors = load_csv(a.csv)
        problems += errors
    if problems:
        for msg in problems:
            log(f"ERRO: {msg}")
        log("Nada foi executado.")
        return 2

    if a.only:
        suites = [s for s in suites if a.only.lower() in s.suite.lower() or a.only.lower() in s.repo.lower()]
    if not suites:
        log("Nenhuma suite selecionada.")
        return 0

    if "CI" in os.environ:
        log("variavel CI removida do ambiente")
        os.environ.pop("CI", None)

    study = Study(a, log)
    study.write_environment()
    mode = "smoke (1 execucao)" if a.smoke else f"{a.auto_runs} + {a.manual_runs} execucoes"
    log(f"{len(suites)} suite(s) de {a.csv.name}; {mode}; resultados em {study.results}")

    try:
        for s in suites:
            study.process(s)
            study.write_summary()
    except Interrupted as e:
        log("")
        log(f"Interrompido ({e}). Rode o mesmo comando para retomar da proxima execucao que falta.")
        study.write_summary()
        study.print_summary()
        return 130
    study.write_summary()
    study.print_summary()
    return 1 if any(r["status"].startswith("ERRO") for r in study.summary) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
