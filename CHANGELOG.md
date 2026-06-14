# Changelog

## [1.35.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.34.5...v1.35.0) (2026-06-14)


### Features

* **unifi_metrics:** ship full UniFi controller telemetry to Splunk ([#425](https://github.com/dryvist/ansible-proxmox-apps/issues/425)) ([a180746](https://github.com/dryvist/ansible-proxmox-apps/commit/a1807469aef07f497752ebc3501a0377e5980369))

## [1.34.5](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.34.4...v1.34.5) (2026-06-14)


### Bug Fixes

* **schema:** accept FQDN in ingress ip field for DHCP-first guests ([#431](https://github.com/dryvist/ansible-proxmox-apps/issues/431)) ([44a31af](https://github.com/dryvist/ansible-proxmox-apps/commit/44a31af8d944692ce030694e57c57bb30dce4fd5))

## [1.34.4](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.34.3...v1.34.4) (2026-06-14)


### Bug Fixes

* **plex:** publish claimed server to plex.tv so clients can discover it ([#427](https://github.com/dryvist/ansible-proxmox-apps/issues/427)) ([307805a](https://github.com/dryvist/ansible-proxmox-apps/commit/307805a13329e781cbb1e07a9e753ecbd6767a5f))

## [1.34.3](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.34.2...v1.34.3) (2026-06-13)


### Bug Fixes

* **media:** self-own *arr keys, non-fatal seerr reg, secret preflights ([#422](https://github.com/dryvist/ansible-proxmox-apps/issues/422)) ([30802f0](https://github.com/dryvist/ansible-proxmox-apps/commit/30802f0e9da90ee719eb56630d352f4846efe46f))

## [1.34.2](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.34.1...v1.34.2) (2026-06-13)


### Bug Fixes

* **infra:** add restart-on-failure backoff to keystone LB services ([#421](https://github.com/dryvist/ansible-proxmox-apps/issues/421)) ([84c613c](https://github.com/dryvist/ansible-proxmox-apps/commit/84c613ca023118b474166261c4a428678e303d66))

## [1.34.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.34.0...v1.34.1) (2026-06-13)


### Bug Fixes

* **cribl_stream:** conditionally stamp Splunk metadata on the S2S input ([#417](https://github.com/dryvist/ansible-proxmox-apps/issues/417)) ([795d983](https://github.com/dryvist/ansible-proxmox-apps/commit/795d983614325048b3ef17ac0f34ffdc31c078d0))
* **inventory:** fail loud instead of silently using a stale cache ([#418](https://github.com/dryvist/ansible-proxmox-apps/issues/418)) ([b628045](https://github.com/dryvist/ansible-proxmox-apps/commit/b628045bde6d4de224b15fdcd5550c59b46cd3d2))

## [1.34.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.33.5...v1.34.0) (2026-06-13)


### Features

* **cribl:** route UniFi IPFIX/NetFlow to the netflow index ([#415](https://github.com/dryvist/ansible-proxmox-apps/issues/415)) ([b50f5e9](https://github.com/dryvist/ansible-proxmox-apps/commit/b50f5e9cce5253cb511ed9f3fae372aeac253268))

## [1.33.5](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.33.4...v1.33.5) (2026-06-12)


### Bug Fixes

* **media:** unprivileged-LXC /data access, DHCP-first addressing, Plex apt, servarr wiring ([#413](https://github.com/dryvist/ansible-proxmox-apps/issues/413)) ([6b64c8b](https://github.com/dryvist/ansible-proxmox-apps/commit/6b64c8ba46de7ccb0f0bbd114f7b08b9cc7ca4dd))

## [1.33.4](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.33.3...v1.33.4) (2026-06-12)


### Bug Fixes

* **media:** run VPN downloader last so it can't block the stack ([7ba5f0b](https://github.com/dryvist/ansible-proxmox-apps/commit/7ba5f0b209788e50d97b693370230a4047456fcd))

## [1.33.3](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.33.2...v1.33.3) (2026-06-12)


### Bug Fixes

* **cribl_stream:** S2S input must be tcpjson — cribl_tcp is distributed-only ([#408](https://github.com/dryvist/ansible-proxmox-apps/issues/408)) ([3443160](https://github.com/dryvist/ansible-proxmox-apps/commit/34431602589a8d9ddf3002bc89ab97090eceb917))

## [1.33.2](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.33.1...v1.33.2) (2026-06-12)


### Bug Fixes

* **technitium_dns:** point dhcp-first guest A records at reserved_ip ([#401](https://github.com/dryvist/ansible-proxmox-apps/issues/401)) ([f840552](https://github.com/dryvist/ansible-proxmox-apps/commit/f840552f551ba23ea5cc5f355baad1b554b2aefd))

## [1.33.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.33.0...v1.33.1) (2026-06-12)


### Bug Fixes

* **tests:** add cribl_s2s to the template-render fixture service_ports ([#406](https://github.com/dryvist/ansible-proxmox-apps/issues/406)) ([1054499](https://github.com/dryvist/ansible-proxmox-apps/commit/1054499c4aba583c8e720d115ff0aa6f8e6f9206))

## [1.33.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.32.1...v1.33.0) (2026-06-12)


### Features

* **media:** cut media stack over to unified /data hardlink layout + resilience ([#400](https://github.com/dryvist/ansible-proxmox-apps/issues/400)) ([4f4cf3b](https://github.com/dryvist/ansible-proxmox-apps/commit/4f4cf3bb1d005dedc31c3db53e6509fb7ff4598c))

## [1.32.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.32.0...v1.32.1) (2026-06-12)


### Bug Fixes

* **cribl:** idempotent converge — guard mode-edge, drift-check stream outputs ([#402](https://github.com/dryvist/ansible-proxmox-apps/issues/402)) ([91df14f](https://github.com/dryvist/ansible-proxmox-apps/commit/91df14fe32238d42548a255ce84ec0974d84efce))

## [1.32.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.31.0...v1.32.0) (2026-06-12)


### Features

* **inventory:** accept DHCP-first container fields (mac, reserved_ip, FQDN ip) ([#399](https://github.com/dryvist/ansible-proxmox-apps/issues/399)) ([1b0ef9f](https://github.com/dryvist/ansible-proxmox-apps/commit/1b0ef9f06c48421fe70d56e101441ddbeac893f7))

## [1.31.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.30.0...v1.31.0) (2026-06-12)


### Features

* **cribl:** S2S path — HAProxy :10300 frontend + Stream cribl_tcp input ([#393](https://github.com/dryvist/ansible-proxmox-apps/issues/393)) ([2607e2e](https://github.com/dryvist/ansible-proxmox-apps/commit/2607e2e0b9984360ea5b9c39df019994bb7eec0f))
* **inventory:** resolve inventory S3-first via amazon.aws (drop sync script) ([#397](https://github.com/dryvist/ansible-proxmox-apps/issues/397)) ([6e2688f](https://github.com/dryvist/ansible-proxmox-apps/commit/6e2688fa1e1c6e3b8b1186de946aaa188267b2f4))


### Bug Fixes

* **e2e:** search srcPort (Cribl netflow field name); unshadow inventory_path ([#395](https://github.com/dryvist/ansible-proxmox-apps/issues/395)) ([5150cf9](https://github.com/dryvist/ansible-proxmox-apps/commit/5150cf900a379503bb27a3c891c2f96f308ca89d))
* **inventory:** scrub manual terragrunt-output instructions from fail messages ([#398](https://github.com/dryvist/ansible-proxmox-apps/issues/398)) ([227dafa](https://github.com/dryvist/ansible-proxmox-apps/commit/227dafae6fc9c707b2b507bac0d6840b63f1a9fa))

## [1.30.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.29.3...v1.30.0) (2026-06-11)


### Features

* **pipeline:** consume syslog_port_map as single source of truth + FQDN Splunk host ([#390](https://github.com/dryvist/ansible-proxmox-apps/issues/390)) ([ec835af](https://github.com/dryvist/ansible-proxmox-apps/commit/ec835af6e7f73a54e3bccc97996c37959acb1be7))

## [1.29.3](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.29.2...v1.29.3) (2026-06-11)


### Bug Fixes

* **e2e:** repair validation harness — check mode, Edge paths, per-edge tests, loud gate ([#388](https://github.com/dryvist/ansible-proxmox-apps/issues/388)) ([673d20d](https://github.com/dryvist/ansible-proxmox-apps/commit/673d20dc4b5c09c8b8a2ed6ae9d064b4706b37c7))

## [1.29.2](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.29.1...v1.29.2) (2026-06-11)


### Bug Fixes

* **netmon:** make molecule pass + fix Starlink exporter image/flags ([#386](https://github.com/dryvist/ansible-proxmox-apps/issues/386)) ([a91086f](https://github.com/dryvist/ansible-proxmox-apps/commit/a91086fc2d4c71600b33c2b113cda26e2bf8a366))

## [1.29.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.29.0...v1.29.1) (2026-06-10)


### Bug Fixes

* **ci:** accept apex ingress entries in schema + wrap long test lines ([#385](https://github.com/dryvist/ansible-proxmox-apps/issues/385)) ([9e7bb38](https://github.com/dryvist/ansible-proxmox-apps/commit/9e7bb3896190675d87a82d4200f72256e36965a1))

## [1.29.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.28.0...v1.29.0) (2026-06-10)


### Features

* **netmon:** per-WAN Telegraf collection into the Splunk netmon index ([#383](https://github.com/dryvist/ansible-proxmox-apps/issues/383)) ([d4ec0f6](https://github.com/dryvist/ansible-proxmox-apps/commit/d4ec0f61a339f755088ab59831ade370c3815f51))

## [1.28.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.27.0...v1.28.0) (2026-06-09)


### Features

* **syslog_forwarder:** forward infra LXC logs to the Cribl pipeline ([#377](https://github.com/dryvist/ansible-proxmox-apps/issues/377)) ([5ba4e7c](https://github.com/dryvist/ansible-proxmox-apps/commit/5ba4e7c97750db63c4356b0cf08b5ce9d4097056))

## [1.27.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.26.6...v1.27.0) (2026-06-09)


### Features

* **traefik+technitium:** front Proxmox cluster UI at the subdomain apex ([#376](https://github.com/dryvist/ansible-proxmox-apps/issues/376)) ([ee2d23b](https://github.com/dryvist/ansible-proxmox-apps/commit/ee2d23b95cef7117857612ea6f03787ca0e6fe33))

## [1.26.6](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.26.5...v1.26.6) (2026-06-07)


### Bug Fixes

* **download_vpn:** re-assert lanroute table before deploy-time gate ([#371](https://github.com/dryvist/ansible-proxmox-apps/issues/371)) ([93d4981](https://github.com/dryvist/ansible-proxmox-apps/commit/93d498154819845ede340e92105247c7cfc40b48)), closes [#367](https://github.com/dryvist/ansible-proxmox-apps/issues/367)

## [1.26.5](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.26.4...v1.26.5) (2026-06-07)


### Bug Fixes

* **ntp+servarr_wiring:** reliable LXC detection and Sonarr v4 quality profile ([a12173e](https://github.com/dryvist/ansible-proxmox-apps/commit/a12173e97bc4bd52ed15a4119cbce7d6a244795f))

## [1.26.4](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.26.3...v1.26.4) (2026-06-07)


### Bug Fixes

* **ntp:** skip chrony service start in LXC; exclude download_vpn from apt proxy ([#366](https://github.com/dryvist/ansible-proxmox-apps/issues/366)) ([ddb411f](https://github.com/dryvist/ansible-proxmox-apps/commit/ddb411f2b30fc8f2823e845b465e4d01ae38755c))

## [1.26.3](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.26.2...v1.26.3) (2026-06-07)


### Bug Fixes

* **download_vpn:** skip apt cache refresh when the proxy is unreachable ([#364](https://github.com/dryvist/ansible-proxmox-apps/issues/364)) ([1909b3e](https://github.com/dryvist/ansible-proxmox-apps/commit/1909b3e50610c3b3a3967f237acc7a1dacfe0100)), closes [#363](https://github.com/dryvist/ansible-proxmox-apps/issues/363)

## [1.26.2](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.26.1...v1.26.2) (2026-06-07)


### Bug Fixes

* **download_vpn:** set qBittorrent auth whitelist via API, not template ([#361](https://github.com/dryvist/ansible-proxmox-apps/issues/361)) ([e6122d8](https://github.com/dryvist/ansible-proxmox-apps/commit/e6122d8e8babdb4096bba2f9190eb7b604e717c4)), closes [#355](https://github.com/dryvist/ansible-proxmox-apps/issues/355)

## [1.26.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.26.0...v1.26.1) (2026-06-07)


### Bug Fixes

* **download_vpn:** correct qBittorrent uTP/overhead rate-limit API field names ([#359](https://github.com/dryvist/ansible-proxmox-apps/issues/359)) ([1a56300](https://github.com/dryvist/ansible-proxmox-apps/commit/1a563004d6b34a91b214e5706e45a66702706869))

## [1.26.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.25.1...v1.26.0) (2026-06-07)


### Features

* **download_vpn:** API-driven bandwidth QoS + fail-closed LAN-reply routing ([#356](https://github.com/dryvist/ansible-proxmox-apps/issues/356)) ([3eabbc0](https://github.com/dryvist/ansible-proxmox-apps/commit/3eabbc00c043a12c36c3cbb2946b49a81e421a64))

## [1.25.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.25.0...v1.25.1) (2026-06-07)


### Bug Fixes

* **download_vpn:** tighten qBittorrent rate limits, schedule, and seeding ([#354](https://github.com/dryvist/ansible-proxmox-apps/issues/354)) ([4e28939](https://github.com/dryvist/ansible-proxmox-apps/commit/4e289395ef2b04be313b5d920e0dff2a11d1975b))

## [1.25.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.24.0...v1.25.0) (2026-06-06)


### Features

* **download_vpn:** skip qBittorrent WebUI auth for trusted subnets ([#352](https://github.com/dryvist/ansible-proxmox-apps/issues/352)) ([70b50d9](https://github.com/dryvist/ansible-proxmox-apps/commit/70b50d9ef98a68199ac15ce41358cd153bb10826))

## [1.24.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.23.0...v1.24.0) (2026-06-06)


### Features

* **download_vpn:** policy-route LAN web-UI replies for cross-subnet access ([#350](https://github.com/dryvist/ansible-proxmox-apps/issues/350)) ([4413289](https://github.com/dryvist/ansible-proxmox-apps/commit/4413289169daa0e39ac3dde79843838b3b14d47e))

## [1.23.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.22.1...v1.23.0) (2026-06-05)


### Features

* **openbao:** add OpenBao secrets-manager role (Raft node 1) ([f92ab0a](https://github.com/dryvist/ansible-proxmox-apps/commit/f92ab0a29272d548e517ae64d570682570ba8d54))

## [1.22.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.22.0...v1.22.1) (2026-06-04)


### Bug Fixes

* **technitium_dns:** authenticate per node for HA secondaries ([#346](https://github.com/dryvist/ansible-proxmox-apps/issues/346)) ([d5fcbd2](https://github.com/dryvist/ansible-proxmox-apps/commit/d5fcbd26f14fbb70ac3627ccd905213043d2e808))

## [1.22.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.21.0...v1.22.0) (2026-06-04)


### Features

* **immich:** self-hosted photo/video backup (Docker-in-LXC) ([#344](https://github.com/dryvist/ansible-proxmox-apps/issues/344)) ([9ea5216](https://github.com/dryvist/ansible-proxmox-apps/commit/9ea5216e31ebb9887d211bf04ecfcaedc1b59db8))

## [1.21.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.20.2...v1.21.0) (2026-06-04)


### Features

* **media:** bake torrent etiquette defaults — ratio/seed/anon-off/removeCompleted ([#327](https://github.com/dryvist/ansible-proxmox-apps/issues/327)) ([edd63f5](https://github.com/dryvist/ansible-proxmox-apps/commit/edd63f5a66aea2c7f1e7883a0904f297fa0fb77b))

## [1.20.2](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.20.1...v1.20.2) (2026-06-04)


### Bug Fixes

* **open_webui:** install sudo for become_user privilege drop ([b245e5a](https://github.com/dryvist/ansible-proxmox-apps/commit/b245e5a0f1614bcb6c592ee23e215d48931f2716))

## [1.20.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.20.0...v1.20.1) (2026-06-04)


### Bug Fixes

* **open_webui:** install curl/ca-certificates before uv installer ([61d7cc1](https://github.com/dryvist/ansible-proxmox-apps/commit/61d7cc131b5771ff036341526f066ffb889c1241))

## [1.20.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.19.4...v1.20.0) (2026-06-04)


### Features

* **traefik:** support HTTPS backends with self-signed certs ([#337](https://github.com/dryvist/ansible-proxmox-apps/issues/337)) ([57fa095](https://github.com/dryvist/ansible-proxmox-apps/commit/57fa095937e26fe17f30682ae321b0cf2176f3c5))

## [1.19.4](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.19.3...v1.19.4) (2026-06-04)


### Bug Fixes

* **ollama:** create systemd drop-in dir before env override ([5f2e453](https://github.com/dryvist/ansible-proxmox-apps/commit/5f2e4530634adbb8867335418eddef0008f9c029))

## [1.19.3](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.19.2...v1.19.3) (2026-06-04)


### Bug Fixes

* **ollama:** join GPU device-owning groups by runtime stat, not fixed GIDs ([94da2cf](https://github.com/dryvist/ansible-proxmox-apps/commit/94da2cfe6ee4e737c5d36b900d3749e743f9182c))

## [1.19.2](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.19.1...v1.19.2) (2026-06-04)


### Bug Fixes

* **ollama:** install curl/ca-certificates/zstd before Ollama install ([ecb4602](https://github.com/dryvist/ansible-proxmox-apps/commit/ecb46029ed79221d379176e39e45c1939cf80acd))

## [1.19.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.19.0...v1.19.1) (2026-06-04)


### Bug Fixes

* **inventory-schema:** make port registries extensible ([#326](https://github.com/dryvist/ansible-proxmox-apps/issues/326)) ([8bf0b39](https://github.com/dryvist/ansible-proxmox-apps/commit/8bf0b39bbd3a7f10d1fc8053f08d94f0f576d189))

## [1.19.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.18.0...v1.19.0) (2026-06-04)


### Features

* local Hermes LLM — ollama + open_webui roles ([7c90dc3](https://github.com/dryvist/ansible-proxmox-apps/commit/7c90dc3c4ac06dfb1026b9cd04d3c50ed22198e0))

## [1.18.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.17.1...v1.18.0) (2026-06-03)


### Features

* **technitium_dns:** native primary/secondary HA mode ([#319](https://github.com/dryvist/ansible-proxmox-apps/issues/319)) ([d38bd65](https://github.com/dryvist/ansible-proxmox-apps/commit/d38bd651035f7f44a683edc8c86761bce96beb26))

## [1.17.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.17.0...v1.17.1) (2026-06-03)


### Bug Fixes

* **traefik:** unprivileged-LXC systemd + HTTPS redirect + PROXMOX_SUBDOMAIN ingress base ([#316](https://github.com/dryvist/ansible-proxmox-apps/issues/316)) ([f33c73b](https://github.com/dryvist/ansible-proxmox-apps/commit/f33c73b29ced8cf50d7a10bd36e8e81050fd57be))

## [1.17.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.16.0...v1.17.0) (2026-06-03)


### Features

* **traefik:** HTTPS ingress for all service UIs via wildcard ACME ([58064c9](https://github.com/dryvist/ansible-proxmox-apps/commit/58064c9db1dba2cd4915fc42b6d09ef50e344182)), closes [#247](https://github.com/dryvist/ansible-proxmox-apps/issues/247)

## [1.16.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.15.0...v1.16.0) (2026-06-03)


### Features

* **media:** add validate-media playbook for indexer health and sync ([#311](https://github.com/dryvist/ansible-proxmox-apps/issues/311)) ([7b1809e](https://github.com/dryvist/ansible-proxmox-apps/commit/7b1809e7e0cd2e405e75f37a916d47bceb060639))

## [1.15.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.14.2...v1.15.0) (2026-06-03)


### Features

* **media:** migrate request app from deprecated Jellyseerr to Seerr ([#307](https://github.com/dryvist/ansible-proxmox-apps/issues/307)) ([4e03af1](https://github.com/dryvist/ansible-proxmox-apps/commit/4e03af1ddd4fdda959927a2fb8ec4209c5f72b41))
* **media:** split movies and shows into separate ZFS datasets ([#306](https://github.com/dryvist/ansible-proxmox-apps/issues/306)) ([8601008](https://github.com/dryvist/ansible-proxmox-apps/commit/86010086a37e079cd2e83504e939eba4e8eafc1b))


### Bug Fixes

* **jellyseerr:** complete owner + service registration automatically ([#304](https://github.com/dryvist/ansible-proxmox-apps/issues/304)) ([ea4aa53](https://github.com/dryvist/ansible-proxmox-apps/commit/ea4aa536daa24dc9c12b4a58fa84852a107bd299))
* **media:** reconcile Seerr Sonarr/Radarr root folder on drift ([#310](https://github.com/dryvist/ansible-proxmox-apps/issues/310)) ([3cc3b59](https://github.com/dryvist/ansible-proxmox-apps/commit/3cc3b59e2d5a181bb37e18e6c9504fdceae919fa))
* **servarr:** set a valid auth method so the UI isn't walled off ([#305](https://github.com/dryvist/ansible-proxmox-apps/issues/305)) ([5798012](https://github.com/dryvist/ansible-proxmox-apps/commit/57980120b694ba69b68435a14336750c553c5cae))

## [1.14.2](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.14.1...v1.14.2) (2026-06-02)


### Bug Fixes

* **media:** unblock downloads and complete last-mile media wiring ([#302](https://github.com/dryvist/ansible-proxmox-apps/issues/302)) ([b8da36a](https://github.com/dryvist/ansible-proxmox-apps/commit/b8da36a54168a04ffa6d70fdb7187f0b606603aa))

## [1.14.1](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.14.0...v1.14.1) (2026-06-01)


### Bug Fixes

* **download_vpn:** use wg-quick auto routing — drop recursive Table=off design ([#298](https://github.com/dryvist/ansible-proxmox-apps/issues/298)) ([a069b77](https://github.com/dryvist/ansible-proxmox-apps/commit/a069b778fd4c5f848bec9247596a18ea408293d8))
* **media:** self-healing Jellyseerr wiring + idempotent non-fatal Plex claim ([#301](https://github.com/dryvist/ansible-proxmox-apps/issues/301)) ([120bae7](https://github.com/dryvist/ansible-proxmox-apps/commit/120bae74641c94492701f03409af2ec7ef4b6b4f))

## [1.14.0](https://github.com/dryvist/ansible-proxmox-apps/compare/v1.13.0...v1.14.0) (2026-06-01)


### Features

* **download_vpn:** VPN-locked qBittorrent+Prowlarr LXC with fail-closed killswitch ([#286](https://github.com/dryvist/ansible-proxmox-apps/issues/286)) ([58cc4f3](https://github.com/dryvist/ansible-proxmox-apps/commit/58cc4f30d14cc0221621390cd37826abea1fafbe))
* **idrac_kvm_docker:** rebuild viewer image with AVCT client; LXC wiring + ports 5410/5710 ([#284](https://github.com/dryvist/ansible-proxmox-apps/issues/284)) ([e528aa5](https://github.com/dryvist/ansible-proxmox-apps/commit/e528aa56a1e5537faa55d3b03481ac50351691fd))
* **media:** add deterministic servarr API keys to SOPS for self-wiring ([#290](https://github.com/dryvist/ansible-proxmox-apps/issues/290)) ([963eced](https://github.com/dryvist/ansible-proxmox-apps/commit/963eced4a0e037045dde30a16d442fdc08c11344))
* **media:** jellyseerr role + idempotent Servarr-API self-wiring ([#289](https://github.com/dryvist/ansible-proxmox-apps/issues/289)) ([af2b707](https://github.com/dryvist/ansible-proxmox-apps/commit/af2b7079cda6cd4d618a12360e0b2575f7eb2429))
* **plex:** switch to Plex v2 apt repo (ed25519) for Debian 13 ([#297](https://github.com/dryvist/ansible-proxmox-apps/issues/297)) ([0d0f202](https://github.com/dryvist/ansible-proxmox-apps/commit/0d0f202175ee6a6707918a56134711d00b4617d3))
* **zot_registry:** self-hosted Zot registry + docker mirror client config ([#287](https://github.com/dryvist/ansible-proxmox-apps/issues/287)) ([dffd5a5](https://github.com/dryvist/ansible-proxmox-apps/commit/dffd5a5097e9e75a3d4e58738cfa4745415e32c8))


### Bug Fixes

* **ci:** repoint release-please caller to org-native reusable workflow ([#292](https://github.com/dryvist/ansible-proxmox-apps/issues/292)) ([aecf5e4](https://github.com/dryvist/ansible-proxmox-apps/commit/aecf5e4581b04be40f85ec129602b7bae1aed30a))
* **download_vpn:** add openresolv so wg-quick DNS= directive works on Debian 13 LXC ([#293](https://github.com/dryvist/ansible-proxmox-apps/issues/293)) ([f05532b](https://github.com/dryvist/ansible-proxmox-apps/commit/f05532b6b066ec85734b63488580618b44033755))

## [1.13.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.12.1...v1.13.0) (2026-05-25)


### Features

* **infisical:** add infisical_docker role + group_vars + tests ([#277](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/277)) ([a87e579](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/a87e579145d6273782ec5787ea3728bd9c8c134f))

## [1.12.1](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.12.0...v1.12.1) (2026-05-25)


### Bug Fixes

* **deps:** refresh gh-aw action SHA pins [aw:gh-aw-pin-refresh] ([#278](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/278)) ([110058d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/110058d08ce4713db7e5d0e7098e87c0dd70fcd8))

## [1.12.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.11.0...v1.12.0) (2026-05-24)


### Features

* **healthchecks:** self-hosted deadman receiver LXC role ([#275](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/275)) ([f506b03](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/f506b0334bd87d0750a2416164c7e9ad1a08078a))

## [1.11.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.10.0...v1.11.0) (2026-05-24)


### Features

* **e2e:** add macOS Cribl Edge -&gt; Splunk freshness gate ([80926fb](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/80926fb2bed16c89a90e93cfaac628d1d7c2cf3a))

## [1.10.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.9.4...v1.10.0) (2026-05-24)


### Features

* **haproxy:** add opt-in HTTP/HTTPS reverse proxy frontends ([1cbd09b](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/1cbd09b7b83b3646ad5e0a7c997f891dbd651de7))

## [1.9.4](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.9.3...v1.9.4) (2026-05-24)


### Bug Fixes

* **pre-commit:** exclude release-please CHANGELOG.md from markdownlint ([#266](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/266)) ([ad8b71c](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/ad8b71c5462705cbd38e2e7807da1ed401e3eb5b))

## [1.9.3](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.9.2...v1.9.3) (2026-05-22)


### Bug Fixes

* **tests:** roll Cribl fixture image to :latest ([#260](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/260)) ([6dbf6d7](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/6dbf6d7203530ef04b603817975278c79aa50919))

## [1.9.2](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.9.1...v1.9.2) (2026-05-21)


### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([#262](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/262)) ([e15de38](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/e15de38c006b8bbd1b289a8959fc19e23e51ae22))

## [1.9.1](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.9.0...v1.9.1) (2026-05-18)


### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([#258](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/258)) ([afbd69d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/afbd69d59c6456e600a21886a7c77af9b974ada9))

## [1.9.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.8.0...v1.9.0) (2026-05-16)


### Features

* **idrac_kvm_docker:** add HTML5 iDRAC KVM role with ipmitool fallback ([#256](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/256)) ([ecf2390](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/ecf23908492378c2a323dc81919fce7554a988bd))

## [1.8.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.7.1...v1.8.0) (2026-05-15)


### Features

* **ntp:** vendor ntp role and add client baseline ([#253](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/253)) ([27264e4](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/27264e4a742218bd5aabc4daf78316fe6dc09437)), closes [#243](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/243)

## [1.7.1](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.7.0...v1.7.1) (2026-05-15)


### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([#251](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/251)) ([d89e82d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/d89e82ddb98215aa125bdc59559f202d549bcb16))

## [1.7.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.6.2...v1.7.0) (2026-05-13)


### Features

* **openproject:** add OpenProject CE Docker-in-LXC role ([#244](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/244)) ([b370e76](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/b370e765ab7f47732d38a1ef338ad208e8326238))

## [1.6.2](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.6.1...v1.6.2) (2026-05-11)


### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([#240](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/240)) ([db96357](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/db96357f6089ccf75089020ff525e565f72c7222))

## [1.6.1](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.6.0...v1.6.1) (2026-05-08)

### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([319b1e4](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/319b1e493d4a47dd85e42b2a2fdc3a3f22f69f34))

## [1.6.0](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.11...v1.6.0) (2026-05-07)

### Features

* **cribl_packs:** deploy orphan Cribl packs and add E2E schedule ([#228](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/228)) ([dc2be6c](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/dc2be6cab5337a7afb08ecde03e28e4898fa2ec6))

## [1.5.11](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.10...v1.5.11) (2026-05-04)

### Bug Fixes

* **deps:** refresh gh-aw action SHA pins ([#233](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/233)) ([1e422f7](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/1e422f710e96ea288870ce8826e9890b94c91b28))

## [1.5.10](https://github.com/JacobPEvans/ansible-proxmox-apps/compare/v1.5.9...v1.5.10) (2026-05-03)

### Bug Fixes

* **ci:** remove deprecated app-id secret passthrough ([8b22c0a](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/8b22c0a194fc1497d865006ef5a2932404a9b078))

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
* configure Cribl Stream Splunk HEC output
  ([#13](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/13))
  ([459bcc5](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/459bcc54d7489dc4d67992109c4b595adf7fb96c)),
  closes [#8](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/8)
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
* **lxc:** fix proxmox_pct_remote connection vars and Docker fuse-overlayfs for ZFS-backed LXC
  ([#78](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/78))
  ([361dd6c](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/361dd6c9cab23b0b1e08d96f6c4714c3e7f3fb3b))
* **pipeline:** add Cribl config and stable syslog entry point ([#30](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/30)) ([8257488](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/825748812a89365fbafe63d99d3deb6e226f01b9))
* remove blanket auto-merge workflow ([#100](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/100)) ([559e12b](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/559e12b06bab12b3ca49dade8f65304c25ba9ff2))
* Remove broken tag-based role conditions from playbooks ([#23](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/23)) ([d40f19f](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/d40f19f6d84532ed0567fb702eb34e8e17528290))
* Remove ipaddr filter from terraform inventory loader ([#22](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/22)) ([870555d](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/870555d8a7fa62b59a7a76dba566e6bf270b50df))
* replace ansible-core with ansible in flake.nix ([#106](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/106)) ([c1d0629](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/c1d06298c30e30df829be948a5f6d9d0cba30ff6))
* use SPLUNK_ADMIN_PASSWORD envvar name to match Doppler ([#33](https://github.com/JacobPEvans/ansible-proxmox-apps/issues/33)) ([91c4a99](https://github.com/JacobPEvans/ansible-proxmox-apps/commit/91c4a990852784a910f0042c5ca0ebd301871ad7))
