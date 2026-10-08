param(
    [Parameter(Mandatory=$true)][string]$CsprojPath,
    [Parameter(Mandatory=$true)][string]$OutDir,
    [string]$Framework = "",
    [int]$Runs = 100
)

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$fwArg = ""
if ($Framework -ne "") {
    $fwArg = "-f $Framework"
}

Write-Host "Building once before the loop..."
Invoke-Expression "dotnet build `"$CsprojPath`" $fwArg -c Release" | Out-Null

for ($i = 1; $i -le $Runs; $i++) {
    Write-Host "Run $i of $Runs..."
    $logFile = "run_$i.trx"
    $cmd = "dotnet test `"$CsprojPath`" $fwArg -c Release --no-build --logger `"trx;LogFileName=$logFile`" --results-directory `"$OutDir`" --blame-hang-timeout 5m"
    Invoke-Expression $cmd | Out-Null
}

Write-Host "Done. $Runs runs completed. Results in $OutDir"
