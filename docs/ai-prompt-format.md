# AI Prompt / Agent-Definition Format

Prompts and agent-definitions in this homelab are fragmented across Claude Code
plugins & skills, imported skills, Claude Code routines, GitHub AW (agentic
workflows), `ai-workflows`, the Hermes `nix-hermes` bundle (skills + SOUL), and
n8n seed workflows. This document defines **one canonical, version-controlled
format** so a single source of truth can feed all of them.

> **Canonical home:** the [`dryvist/ai-llm-prompts`](https://github.com/dryvist/ai-llm-prompts)
> repository (owned/created elsewhere). This document is this repository's adopted
> reference and the mapping for its own consumers (Zammad, n8n). **Migration of the
> existing scattered sources is on hold** until after the first main push — the
> format is agreed now so nothing new is authored against a moving target.

## Design goal

Keep it simple yet valuable: **no bespoke schema**. The canonical unit is the file
the AI-agent open-source community already standardized on — an **Agent Skill**
(`SKILL.md`, supported by 16+ tools incl. Claude Code, Cursor, Gemini CLI, GitHub
Copilot, Letta) — extended so the *same file* is simultaneously:

- a valid **Agent Skill** — `name` + `description` + Markdown body;
- a valid **OKF concept** (Google's [Open Knowledge Format](https://cloud.google.com/blog):
  a directory of Markdown files whose one required field is `type`, with explicit
  Markdown links between concepts);
- **versioned** — an explicit `version` (semver), which neither base format mandates.

Skill-aware and OKF-aware consumers read the file directly. Behavior consumers
(Zammad, n8n, GitHub AW) render it through a thin adapter.

## The unit

One directory per unit; the file is named `SKILL.md` (drop-in for Agent Skills):

```text
ai-llm-prompts/
  splunk-triage/
    SKILL.md
  incident-severity/
    SKILL.md
```

```markdown
---
# Agent Skills — required
name: splunk-triage
description: Triage Splunk alerts into prioritized homelab incidents.
# OKF — required (single mandatory field)
type: agent            # agent | skill | knowledge | routine | workflow
# Explicit version — required here (semver)
version: 1.0.0
# Registry metadata — simple, optional
consumers: [zammad, hermes, claude, n8n, github-aw]
tags: [splunk, incident, triage]
# Per-consumer hints — optional; kept in frontmatter so the body stays portable
zammad:
  agent_type: ticket_tagger
---

The Markdown body is the actual prompt / instructions. Reference related
concepts with ordinary links so both humans and agents can navigate:
see [incident severity](../incident-severity/SKILL.md).
```

### Fields

| Field | Source | Required | Notes |
| --- | --- | --- | --- |
| `name` | Agent Skills | yes | Unique slug; matches the directory name. |
| `description` | Agent Skills | yes | One line; what the unit does / when to use it. |
| `type` | OKF | yes | Controlled vocabulary below. |
| `version` | this spec | yes | Semver. Bump on any body/behavior change. |
| `consumers` | registry | no | Which systems render this unit. Omit = all. |
| `tags` | registry | no | Free-form; reuse existing taxonomies where they exist. |
| `<consumer>` | registry | no | Per-consumer hint block (e.g. `zammad.agent_type`). |

### `type` vocabulary

| `type` | Meaning |
| --- | --- |
| `agent` | An autonomous/triggered agent definition (maps to Zammad `AI::Agent`, Hermes agent, GitHub AW). |
| `skill` | A reusable capability injected into a larger agent/session. |
| `knowledge` | Curated context / runbook (pure OKF concept, no action). |
| `routine` | A scheduled prompt (Claude Code routine, cron-driven). |
| `workflow` | A multi-step orchestration (n8n workflow, GitHub AW pipeline). |

## Consumer model

Each consumer either reads `SKILL.md` natively or renders it via a thin adapter
(adapters live in the canonical repo; built when migration resumes):

| Consumer | Consumption |
| --- | --- |
| Claude Code (plugins / skills / routines) | native — the file **is** an Agent Skill |
| Hermes | `nix-hermes` bundle ingests the skill directories (skills + SOUL) — existing precedent |
| Zammad AI Agents | adapter → `AI::Agent { name, agent_type, definition, action_definition }` |
| n8n | adapter → workflow JSON |
| GitHub AW | adapter → agentic-workflow file |

## Status

- **Now:** format agreed; this document adopted; Zammad's AI **provider** ("same
  brain" — the LiteLLM router) wired independently of the registry.
- **After the first main push:** stand up adapters, source Zammad `AI::Agent`
  seeds from `dryvist/ai-llm-prompts`, and migrate the scattered sources in.
