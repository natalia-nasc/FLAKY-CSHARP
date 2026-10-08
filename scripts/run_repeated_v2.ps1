param(
    [Parameter(Mandatory=$true)][string]$CsprojPath,
    [Parameter(Mandatory=$true)][string]$OutDir,
    [Parameter(Mandatory=$true)][string]$Framework,
    [int]$Runs = 100,
    [int]$StartAt = 1,
    [string]$ResetDir = "",
    [int]$ResetWaitSeconds = 15
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Write-Host "Build unico antes do loop..."
dotnet build $CsprojPath -f $Framework -c Release -p:NuGetAudit=false
if ($LASTEXITCODE -ne 0) { Write-Host "BUILD FALHOU. Abortando."; return }

for ($i = $StartAt; $i -le $Runs; $i++) {
    Write-Host "=== Run $i de $Runs ==="
    dotnet test $CsprojPath -f $Framework -c Release --no-build --logger "trx;LogFileName=run_$i.trx" --results-directory $OutDir
    if (-not (Test-Path (Join-Path $OutDir "run_$i.trx"))) {
        Write-Host "  AVISO: run_$i.trx NAO foi gerado"
    }
    if ($ResetDir -ne "") {
        Push-Location $ResetDir
        docker compose restart
        Pop-Location
        Start-Sleep -Seconds $ResetWaitSeconds
    }
}
Write-Host "Done. Results in $OutDir"

