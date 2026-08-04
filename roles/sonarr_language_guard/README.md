# sonarr_language_guard

Post-import audio-language verification for Sonarr. Sonarr's own MediaInfo
scan already records an imported file's audio languages; this role adds the
missing enforcement step — compare that value against the series' required
language (its language profile cutoff) and react on mismatch.

Wired as a Sonarr [Custom Script](https://wiki.servarr.com/sonarr/custom-scripts)
connection, triggered on the `Download` event (covers both On Import and On
Upgrade). The script never deletes or otherwise mutates the imported file —
see [Mismatch response](#mismatch-response) for what it does instead.

## Installation

Runs on the Sonarr host, after the `sonarr` role. Deploy via this repo:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags sonarr_language_guard
```

## Requirements

- A running Sonarr instance on the same host (this role always talks to
  `127.0.0.1`, never a remote address).
- `jq` and `ffmpeg` (installed by this role) — `jq` parses the Sonarr API
  responses, `ffprobe` (from `ffmpeg`) is the fallback ground truth when
  Sonarr's own MediaInfo field is empty.

## How it works

1. Sonarr invokes the deployed script on every import/upgrade, passing episode
   details as environment variables (see the Servarr wiki link above).
2. The script reads `sonarr_episodefile_mediainfo_audiolanguages` — the audio
   languages Sonarr already detected. If that is empty and `ffprobe` is
   available, it probes the file directly instead.
3. It looks up the series' language profile (`GET /api/v3/series/{id}` →
   `languageProfileId` → `GET /api/v3/languageprofile/{id}` → `cutoff.name`)
   and compares.
4. On anything it cannot determine — no language found, no series id, the API
   unreachable — it logs and exits quietly. **It never guesses, and it never
   blocks the import.**
5. On an actual mismatch, it reacts per `sonarr_language_guard_action`.

## Mismatch response

`sonarr_language_guard_action` (default `notify`):

- `log` — journal entry only (`logger -t sonarr-language-guard`).
- `notify` — journal entry + an ntfy alert.
- `blocklist` — journal entry + ntfy alert + blocklists the grabbed release
  via Sonarr's history API (`POST /api/v3/history/failed/{id}`), so it is not
  re-grabbed. **Still never deletes the already-imported file.**

## Key variables

See `defaults/main.yml`.

- `sonarr_language_guard_action` — mismatch response (`log`/`notify`/`blocklist`).
- `sonarr_language_guard_ntfy_url` — ntfy alert target (tofu-derived domain).
- `sonarr_language_guard_bin_dir` / `sonarr_language_guard_script_name` —
  where the script is deployed; also the path wired into the Custom Script
  connection.
- `sonarr_language_guard_manage_services` — gates the live API wiring step
  (false under Molecule/CI, where no Sonarr instance is running).

## Usage

```yaml
- name: Configure the audio-language guard
  hosts: sonarr_group
  become: true
  roles:
    - role: sonarr_language_guard
```
