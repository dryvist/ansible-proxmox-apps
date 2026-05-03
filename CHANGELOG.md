# Changelog

## [1.5.9](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.8...v1.5.9) (2026-05-03)


### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([#229](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/229)) ([9f2c8f9](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/9f2c8f980a99c25d075689490e67e6b49edd297c))

## [1.5.8](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.7...v1.5.8) (2026-04-29)


### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([#226](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/226)) ([6c27210](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/6c2721066f0977babd758ddfb97ed58e22f965c8))

## [1.5.7](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.6...v1.5.7) (2026-04-26)


### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([a8d4b79](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/a8d4b79080495d4e880aa410777da85e1aa2801b))

## [1.5.6](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.5...v1.5.6) (2026-04-24)


### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([#218](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/218)) ([4f2a598](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/4f2a5986fc134fbf6e173ba93da67c12c1b9b931))

## [1.5.5](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.4...v1.5.5) (2026-04-21)


### Bug Fixes

* **ci:** add gh-aw-pin-refresh workflow and recompile lock files ([3a77fdf](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/3a77fdf5a5e6ab7800e5b5e4da7a5511084adedf))

## [1.5.4](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.3...v1.5.4) (2026-04-13)


### Bug Fixes

* add automation bots to AI Moderator skip-bots ([#208](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/208)) ([802af38](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/802af38c30c775fc9678e002572a3caae7aa83bb))

## [1.5.3](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.2...v1.5.3) (2026-04-13)


### Bug Fixes

* **gh-aw:** recompile agentic workflow lock files with v0.68.1 ([d8fcfbd](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/d8fcfbd3fe150b3a5cfaa2d02c63017a4df5bacc))

## [1.5.2](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.1...v1.5.2) (2026-04-12)


### Bug Fixes

* **cribl_edge:** deploy all config to local/edge instead of local/cribl ([#191](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/191)) ([cb0fdc4](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/cb0fdc4806e3f5af438e06c24eb2938f5fa2317b))

## [1.5.1](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.0...v1.5.1) (2026-04-12)


### Bug Fixes

* **cribl_edge:** correct inputs.yml key format to plain ID ([d4fbfba](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/d4fbfbab89a41bcf571766d569794547dbb26b28))

## [1.5.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.4.3...v1.5.0) (2026-04-12)


### Features

* **cspell:** migrate to shared org-wide dictionary hierarchy ([08c71ea](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/08c71eaf8a445228b5a6bcc0f07f776cffabfd5e))


### Bug Fixes

* **validate:** check cribl-edge.service not cribl.service ([#181](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/181)) ([9e3d6b7](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/9e3d6b7e992bf8d894e0916d25ab0ddc719071a4))

## [1.4.3](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.4.2...v1.4.3) (2026-04-12)


### Bug Fixes

* **mssql_docker:** set data dir owner to UID 10001 for SQL Server ([#178](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/178)) ([f948617](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/f948617a59910714e939d4d8359bb0c26700694a))

## [1.4.2](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.4.1...v1.4.2) (2026-04-12)


### Bug Fixes

* **apt_cacher_ng:** append :443$ to PassThroughPattern for CONNECT match ([#176](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/176)) ([b4c0b69](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/b4c0b693b3eadeb735c62719511290bfa503a0cd))

## [1.4.1](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.4.0...v1.4.1) (2026-04-11)


### Bug Fixes

* **cribl_edge:** correct systemd service name cribl → cribl-edge ([#175](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/175)) ([77917ac](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/77917acdb037877357bc9c333a1a86a66791a009))
* **cribl:** install sudo so become_user: cribl actually works ([#173](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/173)) ([eb63022](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/eb630223b33ab053dcf476f6c3bb96e26236f586))

## [1.4.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.3.2...v1.4.0) (2026-04-11)


### Features

* **minio:** mirror infra artifacts into local bucket for offline hosts ([#171](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/171)) ([47bfbfe](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/47bfbfe384f805fdff0ee2e03b0565a4be3170f9))

## [1.3.2](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.3.1...v1.3.2) (2026-04-11)


### Bug Fixes

* **technitium_dns:** override ansible_become + fix Build A records loop ([#170](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/170)) ([a826633](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/a8266330d1fa4cb139f54db184f330c38411e880))
* **technitium:** use ?token= query param instead of X-Api-Token header ([#168](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/168)) ([2fa92c1](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/2fa92c1ea813fdd1a03b87bf060dd41e7d0d82dd))

## [1.3.1](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.3.0...v1.3.1) (2026-04-11)


### Bug Fixes

* **technitium_install:** correct API params for changePassword + createToken ([#166](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/166)) ([fde2fc9](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/fde2fc9954260e121b057416b3cc84832e4a14c2))

## [1.3.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.2.1...v1.3.0) (2026-04-11)


### Features

* **minio:** add validation checks and 10-year noncurrent lifecycle policy ([#163](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/163)) ([a1106c2](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/a1106c2249037351f6d79107b76fed8afd974234))

## [1.2.1](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.2.0...v1.2.1) (2026-04-11)


### Bug Fixes

* apt-cacher-ng startup + minio restricted-outbound deployment ([#161](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/161)) ([60d6811](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/60d6811029a8014f4d5d415b18217bc64207ee96))

## [1.2.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.1.7...v1.2.0) (2026-04-07)


### Features

* add MinIO role for artifact storage ([#158](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/158)) ([15338f2](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/15338f2f1a50d9da00883bc51d02784367854119))

## [1.1.7](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.1.6...v1.1.7) (2026-04-06)


### Bug Fixes

* resolve E2E deployment blockers ([#153](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/153)) ([f83f333](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/f83f33390f915554e45592950af505986376703b))

## [1.1.6](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.1.5...v1.1.6) (2026-04-04)


### Bug Fixes

* remove claude-review workflow — replaced by Gemini + Copilot ([#154](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/154)) ([a9db8d2](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/a9db8d221f0bde14cb7cc7355ca846492e111f54))

## [1.1.5](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.1.4...v1.1.5) (2026-04-02)


### Bug Fixes

* SHA-pin dopplerhq/secrets-fetch-action ([#151](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/151)) ([667187d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/667187d6b712e2c3156def3495e89132cd06ed06))

## [1.1.4](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.1.3...v1.1.4) (2026-03-30)


### Bug Fixes

* use nix-devenv ansible-apps shell instead of local flake.nix ([#148](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/148)) ([5c42908](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/5c42908737aa0471578ac273d03fc7fe14b0c52d))

## [1.1.3](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.1.2...v1.1.3) (2026-03-26)


### Bug Fixes

* add systemd restart policies via shared role ([#146](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/146)) ([e45fd0e](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/e45fd0e01b203646f2332ab37c157b88cc5ddc78))

## [1.1.2](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.1.1...v1.1.2) (2026-03-25)


### Bug Fixes

* replace uv run with bare commands for Nix dev shell ([#142](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/142)) ([8786839](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/87868399bc4fdff3e14d4090eb4e5dd79d950204))

## [1.1.1](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.1.0...v1.1.1) (2026-03-25)


### Bug Fixes

* correct FQCN and add missing cribl-stream-02 to static inventory ([#141](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/141)) ([24c9cf1](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/24c9cf1f10f8131319668c44663b2025cf304e01))

## [1.1.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.0.0...v1.1.0) (2026-03-19)


### Features

* add Qdrant vector DB and LlamaIndex RAG with Molecule tests ([#127](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/127)) ([eb34db0](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/eb34db004ec39ccd02e8b03a23f83e527171fb30))
* add self-hosted GitHub Actions runners on docker-host VM ([#123](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/123)) ([9ff3a30](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/9ff3a308e6b5bb58979fd5e9864138a55e4559b2))
* **ci:** integrate Doppler secrets-fetch-action for molecule tests ([#134](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/134)) ([a0a8578](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/a0a8578165424ab478b5a55dbed04b4bfb52e1a2))
* fix UniFi syslog pipeline and add E2E testing ([03d633d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/03d633d8d93c712a9f743c4996abe26c78b35ba8))
* **github_runner:** multi-repo support with admin PAT ([#128](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/128)) ([d4fb7f1](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/d4fb7f199353de2cb3af6adea0ba3873faee17c7))
* move IPFIX to Cribl Stream and upgrade to latest image ([12641cc](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/12641cc7280f1dedcb87923fb7a558982e339f9c))
* replace Docker Swarm pipeline with native LXC Cribl deployment ([93cb2c5](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/93cb2c507d7b426189112bd0f3aed145396585f3))


### Bug Fixes

* add missing cribl_docker_stack_hec_tls_verify to template test ([f8d5fe8](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/f8d5fe87c96bbef2e30920aa810266b3b24f4553))
* address code review findings across E2E pipeline ([2e27422](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/2e27422a7d671083176d114c5b36f01cede75e9e))
* address PR review feedback (security, validation, cleanup) ([f93aeb1](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/f93aeb121ba23f328a13d392b863e89842353dbe))
* address review feedback and fix template rendering tests ([5c5240d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/5c5240d8c5ec1013bd5ccfde513bcebda3500361))
* align E2E test fixtures with inventory tag predicates and constants ([360d872](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/360d872f7ccde38370d4be956fa8b9bd828b9985))
* **ci:** add pull-requests: write for release-please auto-approval ([#124](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/124)) ([694cbe4](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/694cbe446eba14f1e6d678d588d981c58b226722))
* **ci:** gate E2E tests on runner availability variable ([#131](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/131)) ([e1f6e4d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/e1f6e4d0130ec7d485635e061187b6b228f85871))
* **ci:** implement Merge Gatekeeper pattern with ci-gate.yml ([#115](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/115)) ([dad325a](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/dad325a7e0b2fbdfb36ead969439d5a029b88136))
* **ci:** restore Merge Gatekeeper pattern and fix E2E workflow ([3957454](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/3957454eb97e7de6e87d6eb7f69efcfaafeb291b))
* **ci:** use GitHub App token for release-please to trigger CI Gate ([#112](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/112)) ([56cca89](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/56cca89016765aa570c030367045873a6b7fcaed))
* complete E2E fixture alignment with inventory predicates and constants ([a4d1517](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/a4d15174299797bb5354286429482a8b7ebd8972))
* correct cribl_edge inventory group name in documentation ([642c485](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/642c485cfd8f374f3069bd9cab3fadbf5a646ff9))
* grant contents: write for release-please workflow ([d42a540](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/d42a540d7cbc95e5cf26a71218eeea30490d57b8))
* improve service validation and UDP port checks in pipeline playbook ([6735ca3](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/6735ca396f464197f3043b674117774392a20d39))
* **inventory:** add dedicated SSH key for Docker VM access ([#130](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/130)) ([9ec350b](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/9ec350be00cad2e8e9f705d7378cda5bee01f6cd))
* migrate release-please config to packages format ([4342b7a](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/4342b7a2cc805541f3195ad385dd70b3667b0adf))
* replace 10.0.1.x IPs with 192.168.0.x in test fixtures ([4a637a7](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/4a637a73995f166b9bea8dbcc1089b1953836073))
* replace Docker Swarm references with LXC-native Cribl targets ([6b9111a](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/6b9111adfb2a30f5b14e97bac375f9e06f80de1c))
* resolve 13 deployment bugs preventing pipeline from functioning ([b799bff](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/b799bff285499794657ab5a6b85d38432782e84f))
* update template test assertion for HTTPS HEC URL ([36880c5](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/36880c5312d29302ea12152a2cf30b5a1dd9cc07))

## 1.0.0 (2026-03-11)


### Features

* add CI auto-fix workflow for Claude Code ([#47](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/47)) ([e6eb088](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/e6eb0886054885f359d9f8797017f6029b83594e))
* add daily repo health audit agentic workflow ([#109](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/109)) ([1a89187](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/1a891877e43c1738d094ca7e177326c3209c95ba))
* add Duck Yeah Splunk app to splunk_docker role ([#24](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/24)) ([a8d162d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/a8d162d48998a3da6c03841c537335b38176822a))
* add final PR review workflow ([#50](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/50)) ([3cbd5d5](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/3cbd5d5e4d9fb7de0ab9b35824df7a544fd9c17f))
* add GitHub Agentic Workflows ([#95](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/95)) ([70fc880](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/70fc8807ffd281b570a75612a8ac6049d566dfa3))
* add LXC pct_remote connection and Splunk Docker role [SUPERSEDED] ([#2](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/2)) ([75f5f06](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/75f5f06308b9925fe698e75f3f979bab1767ea0f))
* add mailpit and ntfy Docker roles ([#74](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/74)) ([c07da63](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/c07da63af0f611b8788f459bce8ff86c022a2716))
* add per-repo devShell replacing broken central shell reference ([#93](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/93)) ([293b6af](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/293b6affc3e0b754e64221f962ce881be113cbf8))
* add qdrant_docker role with CI fixes ([#105](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/105)) ([e7689a8](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/e7689a8900440f5fffeba98d651ce79ded2e5d3d))
* add SOPS integration for encrypted secrets at rest ([#45](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/45)) ([ceb045d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/ceb045d4f0af045820d8159ff1d0392f6ad38138))
* add splunk_docker play to site.yml ([#11](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/11)) ([17ead61](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/17ead61d8edbb2fc008f604ad38d3b1761c89a69))
* add Terraform inventory integration infrastructure ([#4](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/4)) ([1613977](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/1613977d50aba1467818740fb666090ca84ba242))
* Add UDP syslog support and UniFi index routing ([#19](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/19)) ([72dc8ae](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/72dc8ae8113dbc98cb5dfe48fe5f366d088f77c2))
* Add UniFi Cloud TA for Splunk syslog parsing ([#20](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/20)) ([c40cd12](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/c40cd125a1717db587cdf99c7a3473fb49443c5f))
* **apt-cacher-ng:** add caching proxy role for offline apt access ([#27](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/27)) ([a52b3ba](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/a52b3bac93bbf8959d11c6dc4f5582357d8b99b7))
* auto-enable squash merge on all PRs when opened ([#87](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/87)) ([cca2682](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/cca268245893ac17aae38e67ced4bfe31f61cdf4))
* **ci:** unified issue dispatch pattern with AI-created issue support ([#73](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/73)) ([4bf6b5c](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/4bf6b5cb33d15efc65d636a5aaf64f430cb47ec9))
* configure Cribl Edge syslog listeners for all ports ([#12](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/12)) ([ad14c74](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/ad14c743280ae1020da5ddcc6e30386cff3ae8f1))
* configure Cribl Stream Splunk HEC output ([#13](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/13)) ([459bcc5](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/459bcc54d7489dc4d67992109c4b595adf7fb96c)), closes [#8](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/8)
* **copilot:** add Copilot coding agent support + CI fail issue workflow ([#86](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/86)) ([21830a8](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/21830a8c0d45edcf8a648167ee70e9c3e81cfcc1))
* **cribl:** migrate to Docker Swarm with automated E2E validation ([#29](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/29)) ([d878715](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/d878715625d1a663084e1b742e5fae8ff556a397))
* disable automatic triggers on Claude-executing workflows ([8985b72](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/8985b7244b0c7cb532f41cac5aac3aacfdda03d7))
* **mssql_docker:** add role to deploy SQL Server 2022 via Docker Compose ([#72](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/72)) ([7a2607e](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/7a2607ecda52ac16b46801f620d6e1f021420e96))
* pipeline sync - remove splunk role, centralize constants ([#44](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/44)) ([2b663fc](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/2b663fc4544fb86b9d95139008c573af6cebdc96))
* **pipeline:** add NetFlow UDP 2055 to HAProxy and Cribl Edge ([#28](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/28)) ([6814be8](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/6814be8320c3d0eb51485b8435917200df2682cf))
* **renovate:** extend shared preset, remove duplicated rules ([#89](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/89)) ([0417581](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/04175819181efba0da00570b720312c9eb9422b3))
* switch to ai-workflows reusable workflows ([#51](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/51)) ([8e9db57](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/8e9db57e951233bb16c9320a01986845b80cbf4f))


### Bug Fixes

* Add 'always' tag to terraform inventory loader ([#21](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/21)) ([922e3e3](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/922e3e346a94751fa44d331c7d06044e18174719))
* add SSH key to VM inventory and gitignore terraform_inventory.json ([#26](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/26)) ([6226e82](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/6226e8258990e2ceca8dcc7730c9f23da9138a35))
* apt-cacher-ng proper integration + SOPS secrets clarification ([#107](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/107)) ([afa32c4](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/afa32c421e8b7e90c00424e3ed66e03f88cba870))
* bump ai-workflows callers to v0.2.9 and add OIDC permissions ([#58](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/58)) ([1731921](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/1731921ecd0f0790b1f8636e6a6f7aec24f25ee2))
* bump ai-workflows to v0.2.6 and add id-token:write ([#56](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/56)) ([73c21b8](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/73c21b8b2e16145459d1c6321debb078d76e2feb))
* bump all callers to ai-workflows v0.2.3 with explicit permissions ([#55](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/55)) ([cbe61c6](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/cbe61c6582db7d8e68066921168b3aedc55e0e5b))
* **ci:** add dispatch pattern for post-merge and bot guard for triage ([#69](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/69)) ([abb083f](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/abb083f11ce62c7bcbee5fe08162a8058edcebe6))
* Docker collection and Splunk config updates ([#25](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/25)) ([1fc88a5](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/1fc88a53c24d3df2925ff3dc17c70c2d18cbfcfd))
* **inventory:** add haproxy_group and cribl_edge dynamic groups ([#36](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/36)) ([44df9e8](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/44df9e81db44077b80c3c916a525910c26f82e12))
* **lxc:** fix proxmox_pct_remote connection vars and Docker fuse-overlayfs for ZFS-backed LXC ([#78](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/78)) ([361dd6c](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/361dd6c9cab23b0b1e08d96f6c4714c3e7f3fb3b))
* **pipeline:** add Cribl config and stable syslog entry point ([#30](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/30)) ([8257488](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/825748812a89365fbafe63d99d3deb6e226f01b9))
* remove blanket auto-merge workflow ([#100](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/100)) ([559e12b](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/559e12b06bab12b3ca49dade8f65304c25ba9ff2))
* Remove broken tag-based role conditions from playbooks ([#23](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/23)) ([d40f19f](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/d40f19f6d84532ed0567fb702eb34e8e17528290))
* Remove ipaddr filter from terraform inventory loader ([#22](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/22)) ([870555d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/870555d8a7fa62b59a7a76dba566e6bf270b50df))
* replace ansible-core with ansible in flake.nix ([#106](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/106)) ([c1d0629](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/c1d06298c30e30df829be948a5f6d9d0cba30ff6))
* use SPLUNK_ADMIN_PASSWORD envvar name to match Doppler ([#33](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/33)) ([91c4a99](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/91c4a990852784a910f0042c5ca0ebd301871ad7))
