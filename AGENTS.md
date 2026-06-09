# Repository Guidelines

## Project Structure & Module Organization
This repository is a content pipeline for daily LLM and Agent paper curation.

- `skill/paper-daily/` contains the producer workflow and Python modules.
- `skill/paper-daily/scripts/run_daily.py` is the main end-to-end entrypoint.
- `skill/paper-daily/scripts/paper_daily/` holds discovery, ranking, summarization, rendering, and feed/state logic.
- `skill/paper-daily/references/` stores prompt and institution reference data.
- `skill/paper-learning/` contains the Notion-centered learning workflow orchestration layer. It consumes `paper-daily` records, publishes daily reports to Notion and Feishu, processes Notion-selected papers, writes deep-reading notes, and manages archive classification.
- `skill/paper-subscribe/` contains the consumer-side subscription scripts in Node.js.
- `summary/` and `summary_en/` contain generated paper summaries.
- `data/` and `feed-papers.json` are generated artifacts and runtime state.
- `.github/workflows/paper-daily.yml` runs the scheduled production job.

There is no dedicated `tests/` directory at the moment.

## Build, Test, and Development Commands
Use targeted scripts rather than a full build system.

- `python3 skill/paper-daily/scripts/discover.py --date YYYY-MM-DD --select 5`
  Inspect ranked arXiv candidates for a UTC date.
- `python3 skill/paper-daily/scripts/run_daily.py --repo-root . --date YYYY-MM-DD --view-only`
  Run discovery and selection without modifying repository artifacts.
- `python3 skill/paper-daily/scripts/run_daily.py --repo-root . --date YYYY-MM-DD`
  Produce summaries, patch `README.md`, and update feed/state files.
- `python3 skill/paper-learning/scripts/run_daily_learning.py --config skill/paper-learning/templates/config.example.json --date YYYY-MM-DD --dry-run --skip-paper-daily`
  Preview the Notion/Feishu daily learning workflow without external writes.
- `python3 skill/paper-learning/scripts/bootstrap_notion.py --config skill/paper-learning/templates/config.example.json --parent-page <NOTION_PAGE_URL> --write-config`
  Create the required Notion databases and write a local config file with the resulting IDs.
- `python3 skill/paper-learning/scripts/process_notion_queue.py --config skill/paper-learning/templates/config.example.json --dry-run --limit 1`
  Preview selected-paper queue processing without external writes.
- `python3 -m unittest discover tests/paper_learning -v`
  Run the paper-learning unit tests.
- `node skill/paper-subscribe/scripts/prepare-digest.js --config ~/.paper-subscribe/config.json`
  Preview the subscriber digest from the public feed.

## Coding Style & Naming Conventions
Follow the existing style in each language.

- Python uses 4-space indentation, snake_case names, and small single-purpose modules.
- JavaScript in `paper-subscribe` uses ES modules and straightforward synchronous filesystem access where appropriate.
- Keep generated content out of logic modules. Put reusable data in `references/` and runtime outputs in `data/`, `summary/`, and `summary_en/`.
- Prefer explicit filenames such as `run_daily.py`, `generate_feed.py`, and `prepare-digest.js`.

## Testing Guidelines
This repo currently relies on script-level verification rather than a formal test suite.

- Use `discover.py` for discovery sanity checks.
- Use `run_daily.py --view-only` before any publishing change.
- For subscription changes, run `prepare-digest.js` against a local config and inspect the emitted JSON.
- If you add non-trivial logic, include a minimal reproducible verification path in the PR description.

## Commit & Pull Request Guidelines
Recent history uses short conventional-style subjects such as `fix: ...` and `chore: ...`. Keep commits focused and imperative, for example `fix: repair summary excerpt parsing`.

PRs should state what changed, why it changed, and how it was verified. Mention any required environment variables such as `NOTION_TOKEN` or `FEISHU_WEBHOOK_URL`, and call out whether a change affects generated artifacts, scheduled workflow behavior, or subscriber-facing output.
