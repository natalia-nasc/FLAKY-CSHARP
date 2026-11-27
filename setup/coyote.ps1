# coyote: as suites BugFinding, Actors.BugFinding e Rewriting reescrevem o binario depois do build
# com a ferramenta coyote.exe em bin\net8.0. Ela precisa existir antes do build dos testes.
if (-not (Test-Path "bin\net8.0\coyote.exe")) {
    dotnet build Tools\CLI\Coyote.CLI.csproj -c Release -f net8.0 -p:NuGetAudit=false -p:TreatWarningsAsErrors=false
    if ($LASTEXITCODE -ne 0) { throw "falha ao compilar Tools\CLI (coyote.exe)" }
}
