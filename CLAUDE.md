# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

A content pipeline that curates daily LLM/Agent arXiv papers and publishes them to
`README.md` / `README_en.md`, a public `feed-papers.json`, and per-paper summaries in
`summary/` and `summary_en/`. The pipeline is packaged as three **Claude Code skills**
under `skill/`, each with its own `SKILL.md` that is the authoritative operating manual.
Read the relevant `SKILL.md` before doing non-trivial work — the skills encode a
context-driven orchestration model, not a single linear script.

## The three skills (read their SKILL.md first)

- **`skill/paper-daily/`** — producer. Discovers + ranks arXiv candidates, enriches
  metadata, and publishes README/feed/summaries. Python.
- **`skill/paper-learning/`** — orchestration layer built *on top of* paper-daily.
  Publishes daily batches to Notion/Feishu, runs a Notion-based HITL queue, and triggers
  provider-based "deep reading". Python.
- **`skill/paper-subscribe/`** — consumer. Reads only the public `feed-papers.json` and
  delivers a filtered digest on a cron. Node.js (ES modules). Independent of the other two.

## Architectural model that spans files

The key design principle (see both producer SKILL.md files): **the skill orchestrates;
scripts are narrow, bounded primitives.** The runtime model decides which atomic action
to run based on current artifacts and gaps. Scripts must not become long-running or the
sole interface, and the LLM judging/summary-writing steps happen in skill context, *not*
inside the scripts.

paper-daily runs as a state machine over per-date artifacts rather than one command:

- `discover.py` → recall only (arXiv metadata + ranking), no model credentials needed.
- `enrich_metadata.py` → bounded metadata worker; arXiv API first, HTML fallback only
  after a retry threshold.
- `prepare_summary_requests.py` / `prepare_missing_summary_requests.py` → emit requests
  for the runtime skill to generate summary artifacts (scripts never call a fixed model).
- `check_daily_status.py` → readiness probe; prefer it over reading logs.
- `run_daily.py` → candidate production + gated publishing (compatibility entrypoint).
- `finalize_daily.py` → explicit promotion to official README/feed/state when status is
  `final_ready`. Preferred over the lower-level `generate_feed.py`.

Status semantics (`candidate_ready` → `finalize_blocked` → `final_ready` →
`final_published`) and metadata states (`api_pending`/`api_complete`/`html_complete`/
`failed_exhausted`) are defined in `skill/paper-daily/SKILL.md` — honor them rather than
inventing new gating.

Core logic lives in the `paper_daily/` package (discovery, ranker, filters, institutions,
metadata, run_state, summary, render, patch, feed, models). The matching package for the
learning skill is `paper_learning/` (daily_pipeline, queue_pipeline, deep_reading*,
notion_client, feishu_client, classifier, config, models).

## Data and artifact layout

- `data/paper-daily/` — `runs/<date>.json` (run state), `metadata-cache/<id>.json`,
  `summary-artifacts/<id>.json`, `pending-metadata.json`.
- `data/paper-learning/runs/` — per-run learning artifacts (git-ignored).
- `data/canonical-papers.json`, `data/state-feed.json`, `feed-papers.json` — generated
  publishing state. Treat as outputs; don't hand-edit.
- `summary/<YYYY-MM>/<id>.md`, `summary_en/<YYYY-MM>/<id>.md` — generated per-paper notes.
- Note `.gitignore` excludes `/docs/`, `.superpowers/`, `.local/`, and
  `skill/paper-daily/output/`.

## Dates

`--date` always means the arXiv `submittedDate` **UTC** date, not local calendar date.
When the user says "today", prefer the previous complete UTC date. paper-learning's
`run_daily_learning.py` requires an explicit `--date`.

## Auto-Execute Commands

When you type any of these patterns, Claude will automatically execute the corresponding script:

| Your Input | Executes | Purpose |
|-----------|----------|---------|
| `/paper-daily discover [--date DATE]` | `./run-paper-daily.sh discover --date DATE` | Discover papers |
| `/paper-daily status [--date DATE]` | `./run-paper-daily.sh status --date DATE` | Check status |
| `/paper-daily enrich [--date DATE]` | `./run-paper-daily.sh enrich --date DATE` | Enrich metadata |
| `/paper-daily run [--date DATE]` | `./run-paper-daily.sh run --date DATE` | Full pipeline |
| `/paper-daily finalize [--date DATE]` | `./run-paper-daily.sh finalize --date DATE` | Publish |
| `/paper-learning daily [--date DATE]` | `./run-paper-learning.sh daily --date DATE` | Publish to Notion |
| `/paper-learning queue` | `./run-paper-learning.sh queue` | Process queue |
| `/paper-learning status [--date DATE]` | `./run-paper-learning.sh status --date DATE` | Check status |

**Default date handling:**
- If no `--date` specified: paper-daily uses yesterday's UTC date, paper-learning uses today's

## Commands

### Quick Start (Simplified CLI)

For most use cases, use the simplified wrapper scripts (see `PAPER_DAILY_QUICK_START.md`):

```bash
# Paper Daily (arXiv discovery & publishing)
./run-paper-daily.sh discover --date 2026-05-31     # Discover papers
./run-paper-daily.sh status --date 2026-05-31       # Check status
./run-paper-daily.sh enrich --date 2026-05-31       # Enrich metadata
./run-paper-daily.sh finalize --date 2026-05-31     # Publish

# Paper Learning (Notion integration)
./run-paper-learning.sh daily --date 2026-05-31     # Publish to Notion
./run-paper-learning.sh queue                       # Process Notion queue
```

### Full Script Commands

Tests (run from repo root; tests import the `skill/paper_*_import.py` path shims):

```bash
python3 -m unittest discover tests/paper_daily
python3 -m unittest discover tests/paper_learning
python3 -m unittest tests.paper_daily.test_run_state_and_worker   # single module
```

Producer dry-run / publish:

```bash
python3 skill/paper-daily/scripts/discover.py --date YYYY-MM-DD --select 5
python3 skill/paper-daily/scripts/run_daily.py --repo-root . --date YYYY-MM-DD --view-only   # no repo writes
python3 skill/paper-daily/scripts/check_daily_status.py --repo-root . --date YYYY-MM-DD
python3 skill/paper-daily/scripts/finalize_daily.py --repo-root . --date YYYY-MM-DD
```

Learning workflow (loads secrets via `. skill/paper-learning/scripts/load_env.sh .local/paper-learning.env`):

```bash
python3 skill/paper-learning/scripts/run_daily_learning.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --dry-run
python3 skill/paper-learning/scripts/process_notion_queue.py --config skill/paper-learning/templates/config.example.json --dry-run --limit 1
python3 skill/paper-learning/scripts/rehearse_pipeline.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --include-queue
```

`--dry-run` disables Notion/Feishu/runtime writes but still hits external paper sources
(arXiv, Hugging Face). `--skip-summary` tests discovery→orchestration without generating
summaries (uses abstracts as placeholder digest text).

Subscriber:

```bash
node skill/paper-subscribe/scripts/prepare-digest.js --config ~/.paper-subscribe/config.json
```

## Environment

- `poppler-utils` (`pdftotext`) is needed for PDF first-page institution extraction (the
  CI workflow installs it).
- `NOTION_TOKEN` is required for real paper-learning writes to Notion. Optional Feishu
  delivery uses `FEISHU_WEBHOOK_URL` and, when signing is enabled, `FEISHU_WEBHOOK_SECRET`.
- Summary generation is intentionally runtime-skill based: local scripts prepare summary
  artifact requests and consume the resulting JSON artifacts, but do not call a fixed
  model provider or require model credentials. arXiv discovery itself needs no credentials.

## Conventions

- Python: 4-space indent, snake_case, small single-purpose modules. Keep generated content
  out of logic modules — reference data in `references/`, runtime outputs in `data/`.
- Commits: short conventional-style subjects (`fix:`, `feat:`, `refactor:`, `docs:`).
- User-facing reports must not expose internal filtering/ranking/selection criteria, and
  must not claim full-paper certainty when only abstract-level evidence is available
  (see paper-daily SKILL.md "Writing Guidance").
