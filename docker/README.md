# Coleta em Docker (Linux)

Esta pasta roda a coleta descrita no `REPLICACAO.md` dentro de um container Linux. O container tem o mesmo ferramental da seção 4: SDK 10.0.403, runtimes .NET 8.0 e 10.0, Python 3.14 e Git. A orquestração fica a cargo do `run_study.py`, versão Linux do `run_study.ps1`. Ele lê o **mesmo CSV**, aceita os **mesmos parâmetros**, usa o **seu `labels_csv.py`** e os **seus `setup\<repo>.ps1`** e grava as saídas na **mesma estrutura** da seção 5.6.

## 1. Arquivos

```
<raiz do estudo>\
├── run_study.ps1, labels_csv.py, suites.csv, suites2.csv, setup\   (já existentes)
├── compose.yaml          ← novo
└── docker\               ← novo
    ├── Dockerfile
    ├── run_study.py
    └── README.md
```

O que a imagem contém:

| Item | Versão | Observação |
|---|---|---|
| Sistema | Ubuntu 24.04, x64 | mesma base das imagens oficiais do .NET 10 |
| .NET SDK | 10.0.403 | traz o runtime e o ASP.NET Core 10.0.14 |
| Runtimes 8.0 | 8.0.33 (`Microsoft.NETCore.App` e `Microsoft.AspNetCore.App`) | o 9.0 não é instalado, como no Windows; as suítes `net9.0` usam `DOTNET_ROLL_FORWARD=Major` |
| Python | 3.14 | roda o `labels_csv.py` |
| Git | 2.43 + Git LFS | o Git for Windows já inclui o LFS |
| PowerShell | 7.6 | só para os `setup\<repo>.ps1` |

Os downloads do .NET e do PowerShell são conferidos por SHA-512 e SHA-256.

## 2. Pré-requisitos

- **Windows:** Docker Desktop com WSL 2. **Linux:** Docker Engine com o plugin `compose`.
- **CPU e memória.** O número de núcleos muda o paralelismo dos testes e, com ele, a instabilidade. No Docker Desktop, o limite vem do WSL 2 (`%UserProfile%\.wslconfig`, chaves `processors` e `memory`). O container registra o que vê em `results-linux\ambiente.txt`.
- **Só em host Linux:** crie as pastas de saída antes da primeira execução, para que não sejam criadas como root. Se o seu uid não for 1000, passe-o no build:
  ```bash
  mkdir -p results-linux logs-linux
  STUDY_UID=$(id -u) docker compose build
  ```

## 3. Uso

Na raiz do estudo:

```powershell
docker compose build                                       # uma vez (baixa SDK, runtimes, Python)
docker compose run --rm study -Smoke -Csv suites2.csv      # 1 execução por suíte
docker compose run --rm study -Csv suites2.csv             # 100 + 20 execuções
```

Os parâmetros são os mesmos do `.ps1`. Pode escrevê-los no estilo PowerShell (`-SkipBuild`) ou no estilo GNU (`--skip-build`):

| Parâmetro | Padrão | Efeito |
|---|---|---|
| `-Csv` | `suites.csv` | arquivo com a lista de suítes (relativo à raiz do estudo) |
| `-Only` | vazio | só as linhas cujo `suite` ou `repo` contém o texto |
| `-Smoke` | desligado | 1 execução por suíte, que vale como `run_1` da rodada automática; os labels vão para `*_smoke_labels.csv` |
| `-SkipBuild` | desligado | não compila |
| `-AutoRuns` / `-ManualRuns` | 100 / 20 | número de execuções de cada rodada |
| `--build-timeout-min` | 0 (sem limite) | limite do build; o `.ps1` não tem limite |
| `--run-cwd dll\|repo` | `dll` | diretório de trabalho dos runners `mtp`, `mtp-xunit` e `xunit3` (ver seção 6) |

**Rodadas longas.** Para rodar em segundo plano e acompanhar:

```powershell
docker compose run -d --name coleta study -Csv suites2.csv
docker logs -f coleta                 # ou: Get-Content logs-linux\run_study.log -Wait
```

A suspensão do host continua importando: mantenha o `powercfg /change standby-timeout-ac 0` no Windows.

**Retomar.** Rode o mesmo comando de novo. Execuções que já têm `run_N.trx` são puladas e suítes completas só têm os labels gerados de novo. Um `docker stop coleta` ou um Ctrl+C encerra a execução em andamento junto com os processos filhos e apaga o TRX parcial. Os clones ficam no volume `repos`, então a retomada não clona de novo.

**Shell dentro do container**, para depurar uma suíte:

```powershell
docker compose run --rm --entrypoint bash study
```

## 4. Onde ficam as saídas

As saídas ficam em pastas separadas das da coleta no Windows (`results\` e `logs\`). Assim, uma suíte que já rodou no Windows não é tomada como "completa" no Linux.

```
results-linux\
├── automated-runs\<suite>_runs\run_1.trx ... run_100.trx
├── manual-runs\<suite>_manual_runs\run_1.trx ... run_20.trx
├── <suite>_labels.csv, <suite>_manual_labels.csv
├── summary.csv  (ou summary_smoke.csv)
└── ambiente.txt          ← sistema, CPUs, memória, dotnet --info, LANG/TZ
logs-linux\
├── <suite>\build.log, last.out, last.err
├── _repos\<repo>.log     ← git e setup de cada repositório
└── run_study.log         ← tudo o que apareceu no terminal, com data e hora
```

Os clones e o cache do NuGet ficam nos volumes `flaky-replication_repos` e `flaky-replication_nuget`. Para começar do zero, use `docker compose down -v`, que apaga os dois volumes e não toca nos resultados.

## 5. Correspondência com o `run_study.ps1`

| Passo (seção 5.5) | `run_study.py` |
|---|---|
| 1. Validação do CSV | mesmas quatro verificações (colunas obrigatórias, runner, suíte repetida, commit por repo); também confere se `labels_csv.py`, `dotnet` e `git` existem. Se algo falhar, nada é executado. Aceita CSV com BOM, CRLF ou cp1252. |
| `CI` | removida no início; a coluna `env` pode defini-la de novo (caso do Verify) |
| 2. Preparação do repo | `git clone` → `checkout` do commit (com `fetch`, se preciso; não faz checkout se houver alterações locais e o HEAD estiver em outro commit) → submódulos → `setup\<repo>.ps1` com `pwsh`. Se falhar, espera 30 s e tenta mais uma vez, apagando o clone incompleto. |
| 3. Build | mesmo comando; se falhar, roda `dotnet build-server shutdown` e tenta de novo |
| 4. DLL | `dotnet msbuild -getProperty:TargetPath` |
| 5. Rodadas | mesmos comandos dos quatro runners e mesmos nomes `run_N.trx`. O timeout encerra o grupo de processos e os descendentes, como o `taskkill /T /F`, e apaga o TRX parcial. Sem TRX, a execução é repetida uma vez. |
| 6. Labels | `python3 labels_csv.py <pasta> <saída>`, com o seu script |
| Resumo | mesmas colunas; `rodada` vale `auto`, `manual` ou `smoke` |

O caminho do `project` no CSV pode usar `\` e não diferencia maiúsculas de minúsculas, como no Windows.

## 6. O que muda em relação à coleta no Windows

Trocar o sistema operacional muda o ambiente da replicação. Os rótulos obtidos no container **não são diretamente comparáveis** aos da máquina Windows. Para um conjunto de dados de um ambiente só, rode todas as suítes no container. Se quiser usar os dois, apresente o container como um ambiente adicional. As diferenças que mais afetam os resultados:

1. **Testes que dependem do Windows** (registro, caminhos com `\`, alvos `net*-windows`, WinForms/WPF) não compilam ou viram `broken`.
2. **Maiúsculas e minúsculas.** O script resolve o caminho do CSV sem diferenciá-las, mas as referências internas dos repositórios não, como `ProjectReference` e arquivos de dados com grafia diferente. Algumas suítes podem deixar de compilar.
3. **Quebras de linha.** No Linux, o Git faz checkout com LF e `Environment.NewLine` é `\n`. Testes de snapshot ou de comparação de texto podem mudar de resultado.
4. **Cultura e fuso.** No Windows, os testes usam as configurações regionais do usuário. No container, usam `LANG` e `TZ` do `compose.yaml` (padrão `pt_BR.UTF-8` e `America/Sao_Paulo`). Confira com `Get-Culture` e `Get-TimeZone` na máquina Windows e ajuste via `STUDY_LANG` e `STUDY_TZ`.
5. **Diretório de trabalho dos runners `mtp`/`xunit3`.** O `run_study.py` executa a DLL a partir da pasta dela, como o `dotnet test` faz com o testhost. Confira qual pasta o `Start-Process` usa no seu `.ps1`. Se for a pasta do repositório, use `--run-cwd repo`.
6. **Usuário.** Os testes rodam como um usuário comum (`study`, uid 1000), não como root, para se parecer com um usuário Windows sem privilégio de administrador.
7. **Ordem e paralelismo** continuam os padrões de cada framework, como na seção 9.

## 7. Ajustes

- **Versões.** Ficam nos `args` do `compose.yaml`. Para ficar igual à máquina Windows, troque `DOTNET8_RUNTIME_VERSION` pela versão que `dotnet --list-runtimes` mostra lá.
- **Lote do SDK 11.** Gere uma segunda imagem com outro SDK, para não misturar com a do SDK 10:
  `docker compose build --build-arg DOTNET_SDK_VERSION=<versão 11.0.x>` e mude o `image:`.
- **Scripts de setup.** Os `.ps1` rodam no PowerShell 7 para Linux. Cmdlets com caminhos usando `\` (`Get-Content`, `Rename-Item`, `Test-Path`) funcionam. Chamadas a programas nativos com `\` no caminho ou a ferramentas só do Windows podem não funcionar. Para esses casos, crie `setup\<repo>.sh`: se ele existir, roda **no lugar** do `.ps1`, só no container. CRLF no `.sh` é tratado.
- **`labels_csv.py`.** Roda no Python 3.14 do container. Se ele montar caminhos com `"\\"` fixo, o resumo vai mostrar `ERRO: labels`. Nesse caso, troque por `os.path.join` ou `pathlib`.

## 8. Problemas comuns

| Sintoma | O que fazer |
|---|---|
| `permission denied` em `results-linux` (host Linux) | crie as pastas antes e use `STUDY_UID=$(id -u)` no build |
| `ERRO: repo (...)` | veja `logs-linux\_repos\<repo>.log` |
| `ERRO: build` | veja `logs-linux\<suite>\build.log`; as primeiras linhas com `error` aparecem no terminal |
| `ERRO: execucao N sem TRX` | veja `logs-linux\<suite>\last.out` e `last.err` |
| primeiro build lento | é o restore do NuGet; o cache fica no volume `nuget` |
