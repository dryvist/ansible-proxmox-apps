FROM ubuntu:26.04

ARG RUNNER_VERSION=2.322.0
ARG SOPS_VERSION=3.12.1
ARG YQ_VERSION=4.44.1
ARG TARGETARCH=amd64
ARG RUNNER_ARCH=x64

# Install curl first (not in ubuntu:24.04 base image)
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

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER runner
WORKDIR /home/runner/actions-runner

ENTRYPOINT ["/entrypoint.sh"]
