# syntax=docker/dockerfile:1
#
# Ambiente da coleta de testes flaky (secao 4 do REPLICACAO.md), em Linux:
#   - .NET SDK 10.0.403 (traz o runtime 10.0.14 e o ASP.NET Core 10.0.14)
#   - runtimes .NET 8.0 (Microsoft.NETCore.App e Microsoft.AspNetCore.App)
#   - Python 3.14, Git + Git LFS
#   - PowerShell 7 (so para os setup/<repo>.ps1)
#   - run_study.py (versao Linux do run_study.ps1)
#
# Nao instala o runtime 9.0, como na maquina Windows: as suites net9.0 rodam no
# 10.0 via DOTNET_ROLL_FORWARD=Major (coluna env do CSV).

FROM ubuntu:24.04

ARG TARGETARCH
ARG DOTNET_SDK_VERSION=10.0.403
# Runtime 8.0 da mesma leva de patches do SDK 10.0.403 (25/10/2026).
# Troque pela versao que `dotnet --list-runtimes` mostra na maquina Windows.
ARG DOTNET8_RUNTIME_VERSION=8.0.33
ARG PYTHON_VERSION=3.14
ARG UV_VERSION=0.11.32
ARG POWERSHELL_VERSION=7.6.10
ARG STUDY_UID=1000

# Dependencias do .NET (as mesmas da imagem oficial runtime-deps:10.0-noble),
# Git, Git LFS (o Git for Windows ja vem com ele) e tini (PID 1 que repassa sinais).
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl git git-lfs tini \
      libc6 libgcc-s1 libicu74 libssl3t64 libstdc++6 libatomic1 zlib1g \
      tzdata tzdata-legacy \
 && rm -rf /var/lib/apt/lists/* \
 && git lfs install --system \
 && git config --system --add safe.directory '*'

# .NET: SDK fixo + runtimes 8.0, com verificacao de SHA-512.
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in \
      amd64) a=x64 ;; arm64) a=arm64 ;; \
      *) echo "arquitetura nao suportada: ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    b=https://builds.dotnet.microsoft.com/dotnet; s="${DOTNET_SDK_VERSION}"; r="${DOTNET8_RUNTIME_VERSION}"; \
    mkdir -p /tmp/dl /usr/share/dotnet; cd /tmp/dl; \
    curl -fsSL \
      -O "$b/Sdk/$s/dotnet-sdk-$s-linux-$a.tar.gz" \
      -O "$b/Sdk/$s/dotnet-sdk-$s-linux-$a.tar.gz.sha512" \
      -O "$b/Runtime/$r/dotnet-runtime-$r-linux-$a.tar.gz" \
      -O "$b/aspnetcore/Runtime/$r/aspnetcore-runtime-$r-linux-$a.tar.gz" \
      -O "$b/checksums/$r-sha.txt"; \
    sha512sum -c "dotnet-sdk-$s-linux-$a.tar.gz.sha512"; \
    test "$(sha512sum -c "$r-sha.txt" --ignore-missing 2>/dev/null | grep -c ': OK$')" -ge 2; \
    tar -xzf "dotnet-sdk-$s-linux-$a.tar.gz" -C /usr/share/dotnet --no-same-owner; \
    tar -xzf "dotnet-runtime-$r-linux-$a.tar.gz" -C /usr/share/dotnet --no-same-owner ./shared/Microsoft.NETCore.App; \
    tar -xzf "aspnetcore-runtime-$r-linux-$a.tar.gz" -C /usr/share/dotnet --no-same-owner ./shared/Microsoft.AspNetCore.App; \
    ln -s /usr/share/dotnet/dotnet /usr/bin/dotnet; \
    cd /; rm -rf /tmp/dl; \
    dotnet --list-sdks; dotnet --list-runtimes

# Python 3.14 (CPython "standalone", instalado pelo uv).
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in amd64) a=x86_64 ;; arm64) a=aarch64 ;; esac; \
    curl -fsSL "https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/uv-$a-unknown-linux-gnu.tar.gz" \
      | tar -xz -C /tmp; \
    UV_PYTHON_INSTALL_DIR=/opt/python UV_PYTHON_BIN_DIR=/usr/local/bin UV_CACHE_DIR=/tmp/uv-cache \
      "/tmp/uv-$a-unknown-linux-gnu/uv" python install "${PYTHON_VERSION}"; \
    minor="$(echo "${PYTHON_VERSION}" | cut -d. -f1,2)"; \
    ln -sf "/usr/local/bin/python$minor" /usr/local/bin/python3; \
    ln -sf "/usr/local/bin/python$minor" /usr/local/bin/python; \
    rm -rf /tmp/uv-*; \
    python3 --version

# PowerShell 7, com verificacao de SHA-256 (hashes.sha256 da release).
RUN set -eux; \
    case "${TARGETARCH:-amd64}" in amd64) a=x64 ;; arm64) a=arm64 ;; esac; \
    v="${POWERSHELL_VERSION}"; f="powershell-$v-linux-$a.tar.gz"; \
    cd /tmp; \
    curl -fsSL -O "https://github.com/PowerShell/PowerShell/releases/download/v$v/$f" \
               -O "https://github.com/PowerShell/PowerShell/releases/download/v$v/hashes.sha256"; \
    iconv -f UTF-16 -t UTF-8 hashes.sha256 | tr -d '\r' | grep " \*$f\$" | sha256sum -c -; \
    mkdir -p /opt/microsoft/powershell/7; \
    tar -xzf "$f" -C /opt/microsoft/powershell/7; \
    chmod +x /opt/microsoft/powershell/7/pwsh; \
    ln -s /opt/microsoft/powershell/7/pwsh /usr/bin/pwsh; \
    rm -f "$f" hashes.sha256; \
    pwsh -NoProfile -Command '$PSVersionTable.PSVersion.ToString()'

ENV DOTNET_ROOT=/usr/share/dotnet \
    DOTNET_NOLOGO=1 \
    DOTNET_CLI_TELEMETRY_OPTOUT=1 \
    POWERSHELL_TELEMETRY_OPTOUT=1 \
    POWERSHELL_UPDATECHECK=Off \
    STUDY_DOTNET_SDK=${DOTNET_SDK_VERSION} \
    STUDY_DOTNET8_RUNTIME=${DOTNET8_RUNTIME_VERSION}

# Usuario comum (no Windows os testes rodaram sem privilegio de administrador;
# como root, testes de permissao de arquivo se comportariam de outro jeito).
# As pastas sao criadas aqui para que os volumes nomeados herdem o dono.
RUN if id -u ubuntu >/dev/null 2>&1; then userdel -r ubuntu; fi \
 && useradd --create-home --uid "${STUDY_UID}" --shell /bin/bash study \
 && mkdir -p /study/input /study/repos /study/results /study/logs /home/study/.nuget/packages \
 && chown -R study:study /study /home/study

COPY --chmod=755 run_study.py /opt/study/run_study.py

USER study
ENV HOME=/home/study \
    STUDY_INPUT=/study/input \
    STUDY_WORK=/study
WORKDIR /study

# Primeira execucao do SDK (inclui o certificado HTTPS de desenvolvimento,
# como acontece na primeira execucao no Windows).
RUN dotnet dev-certs https >/dev/null 2>&1 || true

ENTRYPOINT ["/usr/bin/tini", "--", "python3", "/opt/study/run_study.py"]
CMD []
