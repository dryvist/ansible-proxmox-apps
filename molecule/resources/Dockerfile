# The one image every Molecule scenario runs on. Built and published to GHCR
# by .github/workflows/molecule-image.yml and handed to jobs as
# MOLECULE_BASE_IMAGE; scenarios never build it themselves.
#
# What it bakes in, and why:
#   * apt proxy config -- every apt run in every scenario goes through the
#     estate cache; https repositories stay direct because the cache cannot
#     serve them.
#   * ca-certificates, curl, gnupg -- the transport prerequisites every role
#     installs first. In a job they cost minutes of dpkg/postinst under a
#     loaded host; here they cost nothing.
#   * Docker Engine -- the docker_engine role skips its whole apt block when
#     `docker --version` answers, so the scenarios that need it skip two
#     apt-get updates, a key fetch and a repository add. Harmless elsewhere.
#
# Local use (a workstation with an amd64 daemon):
#   docker build -t <tag> molecule/resources && MOLECULE_BASE_IMAGE=<tag> molecule test
ARG BASE_IMAGE=geerlingguy/docker-debian12-ansible:latest
FROM ${BASE_IMAGE}

# Empty means go direct -- the same contract as molecule/resources/tasks/apt_proxy.yml.
ARG APT_PROXY_URL=""

RUN export DEBIAN_FRONTEND=noninteractive \
 && . /etc/os-release \
 && if [ -n "${APT_PROXY_URL}" ]; then \
      printf '%s\n' "Acquire::http::Proxy \"${APT_PROXY_URL}\";" \
        'Acquire::https::Proxy "DIRECT";' > /etc/apt/apt.conf.d/01proxy; \
    fi \
 && apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg \
 && install -m 0755 -d /etc/apt/keyrings \
 && curl -fsSL "https://download.docker.com/linux/${ID}/gpg" \
      -o /etc/apt/keyrings/docker.asc \
 && chmod a+r /etc/apt/keyrings/docker.asc \
 && echo "deb [signed-by=/etc/apt/keyrings/docker.asc]" \
      "https://download.docker.com/linux/${ID} ${VERSION_CODENAME} stable" \
      > /etc/apt/sources.list.d/docker.list \
 && apt-get update \
 && apt-get install -y --no-install-recommends \
      docker-ce docker-ce-cli containerd.io \
      docker-buildx-plugin docker-compose-plugin \
 && apt-get clean \
 && rm -rf /var/lib/apt/lists/*
