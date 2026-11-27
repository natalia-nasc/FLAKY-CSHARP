# Renames every global.json in the repository (REPLICACAO.md, section 6.1):
# the pinned SDK is not installed, or global.json switches "dotnet test" to
# MTP mode, where "--logger trx" does not exist. Safe to run more than once.
Get-ChildItem -Path . -Recurse -File -Filter global.json |
    Where-Object { $_.FullName -notmatch '[\\/]\.git[\\/]' } |
    ForEach-Object { Move-Item -LiteralPath $_.FullName -Destination "$($_.FullName).bak" -Force }
