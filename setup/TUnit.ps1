# Ajustes do TUnit (commit f08f178): as suites de mocks nao trazem a extensao de relatorio TRX.
foreach ($n in "Mocks.Tests", "Mocks.Http.Tests", "Mocks.Logging.Tests") {
    $f = "tests\TUnit.$n\TUnit.$n.csproj"
    $t = Get-Content $f -Raw
    if ($t -notmatch "TrxReport") {
        $t = $t -replace '</Project>', "  <ItemGroup>`r`n    <PackageReference Include=`"Microsoft.Testing.Extensions.TrxReport`" />`r`n  </ItemGroup>`r`n</Project>"
        Set-Content $f $t -NoNewline -Encoding UTF8
    }
}
