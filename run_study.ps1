# run_study.ps1 - roda 100 + 20 execucoes de cada suite do suites.csv (ver colunas no suites.csv)
# Uso: powershell -ExecutionPolicy Bypass -File .\run_study.ps1 [-Smoke] [-Only texto] [-SkipBuild]
param(
    [string]$Csv = "suites.csv",
    [string]$Only = "",
    [switch]$Smoke,
    [switch]$SkipBuild,
    [int]$AutoRuns = 100,
    [int]$ManualRuns = 20
)

$ErrorActionPreference = "Continue"
$Root = $PSScriptRoot
Set-Location $Root
Remove-Item Env:CI -ErrorAction SilentlyContinue

function Log($m) { Write-Host "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $m" }
function Val($r, $name, $default) {
    $v = $r.$name
    if ($null -eq $v -or "$v".Trim() -eq "") { return $default }
    return "$v".Trim()
}
function Quote($x) { if ("$x" -match '[\s"]') { '"' + ("$x" -replace '"', '\"') + '"' } else { "$x" } }

# ---------- labels_csv.py ----------
$Labels = @("labels_csv.py", "scripts\labels_csv.py") | ForEach-Object { Join-Path $Root $_ } |
    Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Labels) { Write-Host "ERRO: labels_csv.py nao encontrado na raiz nem em scripts\"; exit 1 }

# ---------- CSV ----------
$csvPath = Join-Path $Root $Csv
if (-not (Test-Path $csvPath)) { Write-Host "ERRO: $csvPath nao existe"; exit 1 }
$rows = @(Import-Csv $csvPath | Where-Object { $_.repo -and -not $_.repo.Trim().StartsWith("#") })
if ($Only) { $rows = @($rows | Where-Object { $_.suite -like "*$Only*" -or $_.repo -like "*$Only*" }) }
if ($rows.Count -eq 0) { Write-Host "Nenhuma suite selecionada."; exit 0 }

$runners = "vstest", "mtp", "mtp-xunit", "xunit3"
$bad = $false
foreach ($r in $rows) {
    foreach ($c in "repo", "url", "commit", "suite", "project", "runner") {
        if (-not (Val $r $c "")) { Write-Host "ERRO: coluna '$c' vazia na suite '$($r.suite)'"; $bad = $true }
    }
    if ($runners -notcontains (Val $r "runner" "")) { Write-Host "ERRO: runner '$($r.runner)' invalido em '$($r.suite)'"; $bad = $true }
}
$dups = $rows | Group-Object suite | Where-Object Count -gt 1
foreach ($d in $dups) { Write-Host "ERRO: suite repetida: $($d.Name)"; $bad = $true }
foreach ($g in ($rows | Group-Object repo)) {
    if (@($g.Group.commit | Sort-Object -Unique).Count -gt 1) { Write-Host "ERRO: commits diferentes para o repo $($g.Name)"; $bad = $true }
}
if ($bad) { exit 1 }

New-Item -ItemType Directory -Force (Join-Path $Root "repos"), (Join-Path $Root "results"), (Join-Path $Root "logs") | Out-Null
$failed = @{}     # suite -> motivo
$summary = @()

# ---------- 1. clone / checkout / setup ----------
function Prepare-Repo($name, $r0) {
    $dir = Join-Path $Root "repos\$name"
    if (-not (Test-Path $dir)) {
        Log "clone $name"
        git clone $r0.url $dir
        if ($LASTEXITCODE -ne 0) {
            Remove-Item $dir -Recurse -Force -ErrorAction SilentlyContinue
            return "falha no git clone"
        }
    }
    $head = "$(git -C $dir rev-parse HEAD)".Trim()
    if ($head -ne $r0.commit.Trim()) {
        $dirty = git -C $dir status --porcelain --untracked-files=no
        if ($dirty) { return "repo com alteracoes locais e HEAD diferente do commit do CSV" }
        Log "checkout $name $($r0.commit)"
        git -C $dir checkout --quiet $r0.commit
        if ($LASTEXITCODE -ne 0) {
            git -C $dir fetch --quiet origin $r0.commit
            git -C $dir checkout --quiet $r0.commit
        }
        if ($LASTEXITCODE -ne 0) { return "falha no checkout" }
    }
    if (Test-Path (Join-Path $dir ".gitmodules")) {
        git -C $dir submodule update --init --recursive
        if ($LASTEXITCODE -ne 0) { return "falha nos submodulos" }
    }
    $setup = Join-Path $Root "setup\$name.ps1"
    if (Test-Path $setup) {
        Log "setup $name"
        Push-Location $dir
        try { & $setup } catch { Pop-Location; return "erro no setup: $_" }
        Pop-Location
    }
    return $null
}

foreach ($g in ($rows | Group-Object repo)) {
    $why = Prepare-Repo $g.Name $g.Group[0]
    if ($why) {
        Log "ERRO $($g.Name): $why. Tentando de novo em 30 s..."
        Start-Sleep 30
        $why = Prepare-Repo $g.Name $g.Group[0]
    }
    if ($why) {
        Log "ERRO $($g.Name) de novo: $why. Indo para o proximo repo."
        foreach ($s in $g.Group) { $failed[$s.suite] = $why }
    }
}

# ---------- funcoes por suite ----------
function Set-SuiteEnv($s) {
    $saved = @{}
    foreach ($kv in (Val $s "env" "").Split(";", [StringSplitOptions]::RemoveEmptyEntries)) {
        $k, $v = $kv.Split("=", 2)
        $k = $k.Trim()
        $saved[$k] = [Environment]::GetEnvironmentVariable($k)
        Set-Item "Env:$k" "$v"
    }
    return $saved
}
function Restore-SuiteEnv($saved) {
    foreach ($k in $saved.Keys) {
        if ($null -eq $saved[$k]) { Remove-Item "Env:$k" -ErrorAction SilentlyContinue }
        else { Set-Item "Env:$k" $saved[$k] }
    }
}
function Extra-Props($s) { return @((Val $s "build_props" "").Split(" ", [StringSplitOptions]::RemoveEmptyEntries)) }

function Get-Dll($s, $proj) {
    $a = @("msbuild", $proj, "-nologo", "-getProperty:TargetPath", "-p:Configuration=$(Val $s 'config' 'Release')")
    $fw = Val $s "framework" ""
    if ($fw) { $a += "-p:TargetFramework=$fw" }
    $a += Extra-Props $s
    $out = & dotnet @a 2>$null
    $dll = $out | Where-Object { "$_" -match '\.dll\s*$' } | Select-Object -Last 1
    if ($dll) { return "$dll".Trim() }
    return $null
}

function Invoke-Run($s, $proj, $dll, $out, $i, $logDir) {
    $trx = "run_$i.trx"
    switch (Val $s "runner" "") {
        "vstest" {
            $a = @("test", $proj, "-c", (Val $s "config" "Release"))
            $fw = Val $s "framework" ""
            if ($fw) { $a += @("-f", $fw) }
            $a += @("--no-build", "--logger", "trx;LogFileName=$trx", "--results-directory", $out)
        }
        "mtp"       { $a = @($dll, "--report-trx", "--report-trx-filename", $trx, "--results-directory", $out) }
        "mtp-xunit" { $a = @($dll, "--report-xunit-trx", "--report-xunit-trx-filename", $trx, "--results-directory", $out) }
        "xunit3"    { $a = @($dll, "-result-trx", (Join-Path $out $trx)) }
    }
    $argLine = ($a | ForEach-Object { Quote $_ }) -join " "
    $p = Start-Process -FilePath "dotnet" -ArgumentList $argLine -NoNewWindow -PassThru -WorkingDirectory $Root `
        -RedirectStandardOutput (Join-Path $logDir "last.out") -RedirectStandardError (Join-Path $logDir "last.err")
    $null = $p.Handle
    $limit = [int](Val $s "timeout_min" "60") * 60000
    if (-not $p.WaitForExit($limit)) {
        taskkill /PID $p.Id /T /F 2>&1 | Out-Null
        Start-Sleep 2
        Remove-Item (Join-Path $out $trx) -ErrorAction SilentlyContinue
        return "timeout"
    }
    $p.WaitForExit()
    return $p.ExitCode
}

function Add-Summary($s, $round, $status, $txt) {
    $m = @{}
    foreach ($l in $txt) {
        if ("$l" -match '^(execucoes \(\.trx\)|testes distintos|stable|flaky|broken|skipped): (\d+)') { $m[$matches[1]] = [int]$matches[2] }
    }
    $script:summary += [pscustomobject]@{
        repo = $s.repo; suite = $s.suite; rodada = $round; status = $status
        trx = $m["execucoes (.trx)"]; distintos = $m["testes distintos"]
        stable = $m["stable"]; flaky = $m["flaky"]; broken = $m["broken"]; skipped = $m["skipped"]
    }
}

# ---------- 2. build e execucoes ----------
$i0 = 0
foreach ($s in $rows) {
    $i0++
    $suite = $s.suite
    Log "===== [$i0/$($rows.Count)] $suite ($($s.repo))"
    if ($failed.ContainsKey($suite)) { Add-Summary $s "-" "ERRO: $($failed[$suite])" @(); continue }

    $proj = Join-Path $Root "repos\$($s.repo)\$($s.project)"
    $logDir = (New-Item -ItemType Directory -Force (Join-Path $Root "logs\$suite")).FullName
    if (-not (Test-Path $proj)) { Log "ERRO: projeto nao encontrado: $proj"; Add-Summary $s "-" "ERRO: csproj nao encontrado" @(); continue }

    # suite ja completa: nao recompila nem roda, so regera os labels
    $doneA = (Test-Path (Join-Path $Root "results\automated-runs\${suite}_runs")) -and
             @(Get-ChildItem (Join-Path $Root "results\automated-runs\${suite}_runs") -Filter "run_*.trx").Count -ge $AutoRuns
    $doneM = (Test-Path (Join-Path $Root "results\manual-runs\${suite}_manual_runs")) -and
             @(Get-ChildItem (Join-Path $Root "results\manual-runs\${suite}_manual_runs") -Filter "run_*.trx").Count -ge $ManualRuns
    $complete = (-not $Smoke) -and $doneA -and $doneM

    $saved = Set-SuiteEnv $s
    try {
        if ($complete) { Log "$suite ja completa (pulando build e execucoes)" }
        if (-not $SkipBuild -and -not $complete) {
            $a = @("build", $proj, "-c", (Val $s "config" "Release"))
            $fw = Val $s "framework" ""
            if ($fw) { $a += @("-f", $fw) }
            $a += @("-p:NuGetAudit=false", "-p:TreatWarningsAsErrors=false") + (Extra-Props $s)
            Log "build $suite"
            & dotnet @a 2>&1 | Out-File (Join-Path $logDir "build.log") -Encoding utf8
            if ($LASTEXITCODE -ne 0) {
                Log "build de $suite falhou. Tentando de novo..."
                & dotnet build-server shutdown 2>&1 | Out-Null
                & dotnet @a 2>&1 | Out-File (Join-Path $logDir "build.log") -Encoding utf8
            }
            if ($LASTEXITCODE -ne 0) {
                Log "ERRO no build de $suite (2 tentativas). Indo para a proxima suite. Linhas com erro (log completo em logs\$suite\build.log):"
                Select-String -Path (Join-Path $logDir "build.log") -Pattern "error" | Select-Object -First 10 | ForEach-Object { Write-Host "   $($_.Line.Trim())" }
                Add-Summary $s "-" "ERRO: build" @()
                continue
            }
        }

        $dll = $null
        if (-not $complete -and (Val $s "runner" "") -ne "vstest") {
            $dll = Get-Dll $s $proj
            if (-not $dll -or -not (Test-Path $dll)) {
                Log "ERRO: DLL de $suite nao encontrada (preencha a coluna framework se o projeto tiver varios alvos)"
                Add-Summary $s "-" "ERRO: dll nao encontrada" @()
                continue
            }
        }

        if ($Smoke) {
            $rounds = @(@{k = "automated-runs"; sfx = "_runs"; n = 1; lab = "_smoke_labels.csv"; name = "smoke" })
        } else {
            $rounds = @(@{k = "automated-runs"; sfx = "_runs"; n = $AutoRuns; lab = "_labels.csv"; name = "100" },
                        @{k = "manual-runs"; sfx = "_manual_runs"; n = $ManualRuns; lab = "_manual_labels.csv"; name = "20" })
        }

        foreach ($r in $rounds) {
            $out = (New-Item -ItemType Directory -Force (Join-Path $Root "results\$($r.k)\$suite$($r.sfx)")).FullName
            $status = "ok"
            for ($i = 1; $i -le $r.n; $i++) {
                if (Test-Path (Join-Path $out "run_$i.trx")) { continue }
                Log "$suite $($r.k) $i/$($r.n)"
                $rc = Invoke-Run $s $proj $dll $out $i $logDir
                if (-not (Test-Path (Join-Path $out "run_$i.trx"))) {
                    Log "   sem TRX (saida: $rc). Tentando a execucao $i de novo..."
                    $rc = Invoke-Run $s $proj $dll $out $i $logDir
                }
                if (-not (Test-Path (Join-Path $out "run_$i.trx"))) {
                    $status = "ERRO: execucao $i sem TRX (saida $rc)"
                    Log "   sem TRX de novo (saida: $rc). Veja logs\$suite\last.out e last.err. Indo para a proxima suite."
                    break
                }
            }
            $txt = & python $Labels $out (Join-Path $Root "results\$suite$($r.lab)") 2>&1
            $txt | ForEach-Object { Write-Host "   $_" }
            Add-Summary $s $r.name $status $txt
            if ($status -ne "ok") { break }
        }
    } finally {
        Restore-SuiteEnv $saved
    }
}

# ---------- 3. resumo ----------
Write-Host ""
Log "===== RESUMO"
Write-Host ($summary | Format-Table suite, rodada, status, trx, distintos, stable, flaky, broken, skipped -AutoSize | Out-String -Width 250)
$name = $(if ($Smoke) { "summary_smoke.csv" } else { "summary.csv" })
$summary | Export-Csv (Join-Path $Root "results\$name") -NoTypeInformation -Encoding UTF8
Log "resumo salvo em results\$name"
