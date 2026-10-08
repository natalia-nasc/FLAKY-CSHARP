param(
    [Parameter(Mandatory=$true)][string]$TestDllPath,
    [Parameter(Mandatory=$true)][string]$OutDir,
    [int]$Runs = 100
)
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
for ($i = 1; $i -le $Runs; $i++) {
    Write-Host "=== Run $i of $Runs ==="
    $logFile = "run_$i.trx"
    dotnet "$TestDllPath" --report-trx --report-trx-filename $logFile --results-directory "$OutDir"
}
Write-Host "Done. $Runs runs completed. Results in $OutDir"

