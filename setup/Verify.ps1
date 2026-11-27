# Ajustes do Verify (commit b3ea8e5): roda com SDK 10, sem o SDK 11 RC do global.json.
if (Test-Path global.json) { Rename-Item global.json global.json.bak -Force }
foreach ($f in "src\Verify\Verify.csproj", "src\Verify.XunitV3\Verify.XunitV3.csproj", "src\Verify.Tests\Verify.Tests.csproj") {
    $t = Get-Content $f -Raw
    $n = $t -replace '<TargetFrameworks>[^<]*</TargetFrameworks>', '<TargetFrameworks>net10.0</TargetFrameworks>'
    if ($n -ne $t) { Set-Content $f $n -NoNewline -Encoding UTF8 }
}
foreach ($f in "src\StaticSettingsTests\StaticSettingsTests.csproj", "src\ApplyScrubbersTests\ApplyScrubbersTests.csproj") {
    $t = Get-Content $f -Raw
    $n = $t -replace '<TargetFramework>net11\.0</TargetFramework>', '<TargetFramework>net10.0</TargetFramework>'
    if ($n -ne $t) { Set-Content $f $n -NoNewline -Encoding UTF8 }
}
