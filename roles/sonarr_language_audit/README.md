# sonarr_language_audit

Scheduled, read-only audit comparing every Sonarr episode file's audio
language against a required-language policy. Runs entirely outside Sonarr —
a systemd timer + oneshot service that only reads Sonarr's API. No Sonarr
connection, setting, or event hook is touched.

## Why an external audit and not a Sonarr connection

Sonarr already records each imported file's audio languages
(`mediaInfo.audioLanguages`) but never compares that against anything. An
external, scheduled audit catches files that are already wrong — not just
newly imported ones — and it runs independently of import timing, so it can
never slow or wedge an import.

Sonarr no longer exposes a per-series required-language field: its old
Language Profile API is a deprecated stub (`SeriesResource.LanguageProfileId`
is hardcoded to always return `1` in current Sonarr). Language enforcement
now lives in Custom Formats, not a queryable series attribute, so this role
compares against one library-wide policy value
(`sonarr_language_audit_required_language`) instead of a per-series lookup.

## Installation

Runs on the Sonarr host, after the `sonarr` role. Deploy via this repo:

```bash
ansible-playbook -i inventory/hosts.yml playbooks/site.yml --tags sonarr_language_audit
```

## Requirements

- A running Sonarr instance on the same host (this role always talks to
  `127.0.0.1`, never a remote address).
- `jq` (installed by this role) — parses the Sonarr API responses.
- `ffmpeg` (installed by this role) — `ffprobe` is the fallback ground truth
  when the stored MediaInfo field is empty (see below).

## How it works

1. On its systemd timer schedule, the script reads Sonarr's own deterministic
   API key from `config.xml` and calls `GET /api/v3/series`, then
   `GET /api/v3/episodefile?seriesId={id}` for each series.
2. For every episode file, it reads `mediaInfo.audioLanguages`. If that is
   empty, it falls back to probing the file directly with `ffprobe`. **Rescan
   will not repopulate this field** — it only re-extracts MediaInfo when a
   file's size on disk has changed. **Refresh does** re-extract it. The
   fallback exists so the audit is correct either way, without depending on
   either having been run.
3. It checks whether `sonarr_language_audit_required_language` appears in the
   language(s) found. A file with no language from either source is skipped
   and logged as undetermined — **never treated as a mismatch**.
4. Mismatches are always logged (`logger -t sonarr-language-audit`); if
   `sonarr_language_audit_action` is `notify` (the default) and any exist,
   they are also summarized in a single ntfy alert. A clean run stays quiet.
5. Anything the script cannot complete (unreadable API key, unreachable
   Sonarr) is logged and the run exits — it never guesses.

The script never deletes, modifies, or blocklists anything. It is a report
generator for a human.

## Key variables

See `defaults/main.yml`.

- `sonarr_language_audit_required_language` — required audio language, as
  Sonarr's MediaInfo reports it (ISO 639-2, three-letter — default `eng`).
- `sonarr_language_audit_action` — mismatch response, `log` or `notify`
  (default `notify`). `log` always happens; `notify` adds the ntfy alert.
  No blocklist/delete option exists.
- `sonarr_language_audit_on_calendar` / `_randomized_delay_sec` — systemd
  `OnCalendar` schedule (default daily) + jitter.
- `sonarr_language_audit_ntfy_url` — ntfy alert target (tofu-derived domain).
- `sonarr_language_audit_manage_services` — gates enabling/starting the live
  timer (false under Molecule/CI, where no Sonarr instance is running).

## Usage

```yaml
- name: Configure the audio-language audit
  hosts: sonarr_group
  become: true
  roles:
    - role: sonarr_language_audit
```
