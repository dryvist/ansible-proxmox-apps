FROM ubuntu:26.04

# 2.328+ required for actions that declare `using: node24` (e.g. checkout v7).
ARG RUNNER_VERSION=2.336.0
ARG SOPS_VERSION=3.12.1
ARG YQ_VERSION=4.44.1
ARG TARGETARCH=amd64
ARG RUNNER_ARCH=x64

# Image version — bump on any toolchain change so a converge rebuilds the image.
LABEL org.opencontainers.image.version="2.1.0"

# Install curl first (not in ubuntu base image)
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates gnupg apt-transport-https \
    && rm -rf /var/lib/apt/lists/*

# Add gh CLI repo + install remaining packages
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
      | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=${TARGETARCH} signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
      > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends \
      git jq make python3 python3-pip python3-venv python3-pytest libicu78 gh \
    && rm -rf /var/lib/apt/lists/*

# Docker CLI client — molecule-plugins[docker] drives the daemon over the host
# socket the compose file bind-mounts (/var/run/docker.sock); only the client
# belongs in the image, not a daemon.
RUN curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
      -o /usr/share/keyrings/docker-archive-keyring.asc \
    && echo "deb [arch=${TARGETARCH} signed-by=/usr/share/keyrings/docker-archive-keyring.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
      > /etc/apt/sources.list.d/docker.list \
    && apt-get update && apt-get install -y --no-install-recommends docker-ce-cli \
    && rm -rf /var/lib/apt/lists/*

# uv — the same installer CI uses (astral-sh/setup-uv)
RUN curl -fsSL https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh

# CI Python toolchain, pre-installed system-wide so molecule / data-contract /
# lint jobs don't rebuild it every run. Mirrors the install lists in
# .github/workflows/_molecule.yml and _data-contract.yml.
# ponytail: baked onto the base image's system python3; a workflow that pins a
# different interpreter via setup-python still provisions its own — these then
# serve manual/fallback runs and keep the docker CLI + collections path warm.
# --break-system-packages is required: the apt python3 is PEP-668 externally-managed.
RUN uv pip install --system --break-system-packages \
      'ansible-core>=2.16' \
      ansible-lint \
      molecule \
      'molecule-plugins[docker]>=23.0.0' \
      'docker>=7.0.0' \
      netaddr \
      jsonschema \
      check-jsonschema

# sops
RUN curl -fsSL "https://github.com/getsops/sops/releases/download/v${SOPS_VERSION}/sops-v${SOPS_VERSION}.linux.${TARGETARCH}" \
    -o /usr/local/bin/sops && chmod +x /usr/local/bin/sops

# age (encryption backend for sops)
RUN curl -fsSL "https://dl.filippo.io/age/latest?for=linux/${TARGETARCH}" \
    | tar xz -C /usr/local/bin/ --strip-components=1

# yq (YAML processor, required by mask-secrets composite action)
RUN curl -fsSL "https://github.com/mikefarah/yq/releases/download/v${YQ_VERSION}/yq_linux_${TARGETARCH}" \
    -o /usr/local/bin/yq && chmod +x /usr/local/bin/yq

# GitHub Actions runner (uses x64 not amd64 in release filenames)
RUN useradd -m -d /home/runner runner \
    && mkdir -p /home/runner/actions-runner \
    && cd /home/runner/actions-runner \
    && curl -fsSL "https://github.com/actions/runner/releases/download/v${RUNNER_VERSION}/actions-runner-linux-${RUNNER_ARCH}-${RUNNER_VERSION}.tar.gz" \
    | tar xz \
    && chown -R runner:runner /home/runner

# Pre-install the Galaxy content this repo pins, into the runner user's default
# lookup paths. The data-contract jobs install without --force, so a warm
# collections/roles path turns those installs into a fast no-op.
COPY requirements.yml /tmp/requirements.yml
RUN ansible-galaxy collection install -r /tmp/requirements.yml \
      -p /home/runner/.ansible/collections \
    && ansible-galaxy role install -r /tmp/requirements.yml \
      -p /home/runner/.ansible/roles \
    && chown -R runner:runner /home/runner/.ansible \
    && rm -f /tmp/requirements.yml

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER runner
WORKDIR /home/runner/actions-runner

ENTRYPOINT ["/entrypoint.sh"]
