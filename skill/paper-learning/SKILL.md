---
name: paper-learning
description: Use this skill whenever the user wants to run, debug, extend, or reason about the paper-learning workflow built on top of paper-daily, especially when the task involves daily paper publishing, Notion as a HITL control plane, chat-triggered deep reading, queue execution, or AI-assisted archive classification.
---

# Paper Learning

Use this skill for the personal paper learning workflow built on top of `paper-daily`.

## When to Use

Use this skill when the user wants to:

- publish a daily paper batch into Notion or Feishu
- review, triage, or process a Notion `Paper Inbox`
- trigger deep reading from chat, from a Notion-selected set, or from a daily report
- generate or consume `ljg-paper` Org artifacts
- reason about queue execution, archive classification, or HITL design in this workflow

## When NOT to Use

Do not use this skill when the user wants to:

- work only on `paper-daily` feed generation without the learning workflow
- work only on `paper-subscribe`
- analyze a single paper in isolation without touching the workflow
- build a new generic agent orchestration framework unrelated to this repo

## Operating Model

Treat this skill as the primary product surface. The user should interact with the workflow through chat and context, not through a pile of scripts.

The intended layering is:

- `paper-learning` skill decides what stage the user is in, what inputs are missing, whether clarification is required, and when to execute.
- Python scripts are narrow execution primitives, rehearsal tools, or debugging tools.
- Notion is the durable workflow state and review surface, but chat is the primary trigger surface for deep reading.

## Skill-First Operation

This skill is the product entrypoint. Prefer using the skill to resolve intent, date, stage, provider, confirmation, and recovery path before calling low-level scripts.

Scripts are execution primitives. They should stay narrow and repeatable; they should not become the only way the user can operate the workflow.

Deep reading is provider-based. The default provider is `ljg-paper`, but the queue must work through a `DeepReadingProvider` boundary so another deep-reading skill can replace it later without rewriting queue orchestration.

## Boundary

- `paper-daily` discovers and summarizes candidate papers.
- `paper-learning` orchestrates Notion, Feishu, human selection, deep reading, and archive classification.
- `paper-subscribe` is not part of this workflow.

## Dependency Rules

- arXiv discovery does not require model credentials.
- The full `paper-daily` path now requires runtime-generated summary artifacts rather than a fixed in-script model provider.
- `--dry-run` disables Notion, Feishu, and runtime writes. It does not skip source calls by itself.
- Use `--skip-summary` when you need to test arXiv discovery into the Notion/Feishu orchestration layer without generated summary artifacts. This uses abstracts as temporary digest text and marks summary provenance as `not_generated`.

## Workflow

The workflow has two product stages:

1. `daily stage`
2. `deep reading stage`

Do not model this as “one workflow that users rerun twice.” The daily stage is scheduled publishing. The deep-reading stage is chat-triggered HITL execution.

### Daily Stage

1. Run the daily stage with `run_daily_learning.py`.
2. If summaries are missing, first run `prepare_daily_learning_requests.py`, execute the returned summary requests through the runtime skill, then rerun `run_daily_learning.py`.
3. Review candidates in the Notion `Paper Inbox`.

### Deep Reading Stage

Deep reading is skill-first and chat-triggered.

The user may express intent in three ways:

- explicit paper selection
- “use what I marked `Selected` in Notion”
- “pick a subset for me” or “process the whole daily report”

The skill should:

1. resolve the intended candidate set
2. decide whether confirmation is required
3. collect or preserve `Human Instruction`
4. make sure `ljg-paper` Org artifacts exist
5. execute queue processing
6. report the resulting `Deep Notes` and archive updates

## Deep Reading Providers

Use the configured `deep_reading.provider` when preparing, checking, or executing deep reading.

Supported provider in this phase:

- `ljg-paper-org`: uses the `ljg-paper` skill to write Org artifacts, validates those artifacts, and converts them into `Deep Notes`.

Provider requirements:

- expose readiness for selected papers
- produce or locate provider artifacts
- convert one selected paper into one `DeepNote`
- surface provider errors without hiding the paper id
- record enough provider metadata for later review

Do not hard-code queue behavior to `ljg-paper`. Treat `ljg-paper-org` as the default provider, not the permanent architecture.

### Human-in-the-Loop Rules

Use conditional confirmation:

- Direct, unambiguous single-paper requests can execute immediately.
- Explicit “process them all” requests can execute immediately.
- Requests based on Notion `Selected`, agent-chosen subsets, or fuzzy references should first show the resolved candidate list and ask for confirmation.

Notion `Selected` means “human-marked candidate set.” It is not, by itself, an automatic execution trigger.

### Script Role

Scripts support the skill. They are not the primary user experience.

- `run_daily_learning.py` is the daily-stage executor.
- `process_notion_queue.py` is the queue executor once the paper set is already known.
- `request_deep_reading.py` and `confirm_deep_reading_request.py` are transition/debugging tools while the chat-facing deep-reading flow is being formalized.

For local queue-stage testing without live Notion selections:

1. Generate a local `selected-papers.json` artifact from the current daily outputs.
2. Prepare `ljg-paper` requests from that artifact, or use the one-shot queue preparation command.
3. Write Org artifacts to `deep_reading.org_artifact_dir`.
4. Run `process_notion_queue.py --selected-papers-json ... --dry-run`.

## Date Rules

- Treat `--date` as the arXiv `submittedDate` UTC date, not the user's local calendar date.
- When the user says "today", do not blindly use the local date. Prefer the previous complete UTC date unless the user explicitly asks for a specific arXiv date.
- `run_daily_learning.py` requires an explicit `--date`; resolve that date deliberately before running the command.
- If a requested date returns unexpectedly few papers, check the previous UTC date before treating it as a data or ranking failure.

## Commands

Daily stage executor:

```bash
python3 skill/paper-learning/scripts/run_daily_learning.py --config ~/.paper-learning/config.json --date YYYY-MM-DD
```

Daily-stage summary request preparation:

```bash
python3 skill/paper-learning/scripts/prepare_daily_learning_requests.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --limit 3
```

Queue executor:

```bash
python3 skill/paper-learning/scripts/process_notion_queue.py --config ~/.paper-learning/config.json
```

Deep-reading request resolution helper:

```bash
python3 skill/paper-learning/scripts/request_deep_reading.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --use-notion-selected
python3 skill/paper-learning/scripts/request_deep_reading.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --all-from-report
python3 skill/paper-learning/scripts/request_deep_reading.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --paper-id arxiv:2605.19932
```

Deep-reading request confirmation helper:

```bash
python3 skill/paper-learning/scripts/confirm_deep_reading_request.py --request data/paper-learning/runs/YYYY-MM-DD/deep-reading-request.json
```

Local selected-papers rehearsal helper:

```bash
python3 skill/paper-learning/scripts/prepare_selected_papers.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --limit 1
```

Local queue-stage rehearsal helper:

```bash
python3 skill/paper-learning/scripts/prepare_queue_stage_requests.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --limit 1
```

`ljg-paper` request preparation:

```bash
python3 skill/paper-learning/scripts/prepare_ljg_paper_requests.py --config ~/.paper-learning/config.json --limit 1
```

`ljg-paper` request preparation from a resolved deep-reading request:

```bash
python3 skill/paper-learning/scripts/prepare_ljg_paper_requests.py --config ~/.paper-learning/config.json --deep-reading-request-json data/paper-learning/runs/YYYY-MM-DD/deep-reading-request.json
```

Daily-stage dry-run:

```bash
python3 skill/paper-learning/scripts/run_daily_learning.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --dry-run
```

Summary-free daily-stage dry-run:

```bash
python3 skill/paper-learning/scripts/run_daily_learning.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --dry-run --skip-summary
```

Queue dry-run:

```bash
python3 skill/paper-learning/scripts/process_notion_queue.py --config skill/paper-learning/templates/config.example.json --dry-run --limit 1
```

Queue dry-run from local `selected-papers.json`:

```bash
python3 skill/paper-learning/scripts/process_notion_queue.py --config skill/paper-learning/templates/config.example.json --selected-papers-json data/paper-learning/runs/YYYY-MM-DD/selected-papers.json --dry-run --limit 1
```

Queue dry-run from a resolved deep-reading request:

```bash
python3 skill/paper-learning/scripts/process_notion_queue.py --config skill/paper-learning/templates/config.example.json --deep-reading-request-json data/paper-learning/runs/YYYY-MM-DD/deep-reading-request.json --dry-run
```

Readiness checks:

```bash
python3 skill/paper-learning/scripts/check_pipeline_readiness.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --stage daily --limit 3
python3 skill/paper-learning/scripts/check_pipeline_readiness.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --stage queue --selected-papers-json data/paper-learning/runs/YYYY-MM-DD/selected-papers.json --limit 1
```

Full local rehearsal:

```bash
python3 skill/paper-learning/scripts/rehearse_pipeline.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --daily-limit 3 --queue-limit 1 --include-queue
```

Notion bootstrap:

```bash
python3 skill/paper-learning/scripts/bootstrap_notion.py --config skill/paper-learning/templates/config.example.json --parent-page <NOTION_PAGE_URL> --write-config
```

## Testing Checklist

- For real Notion or Feishu calls, load local secrets first:

```bash
. skill/paper-learning/scripts/load_env.sh .local/paper-learning.env
```

- Full paper-daily runs also need the summary artifacts prepared ahead of time; summary-free dry runs can use `--skip-summary`.
- `--dry-run` disables Notion, Feishu, and runtime writes, but source aggregation can still call external paper sources such as arXiv and Hugging Face.
- For schema or payload changes, first run the daily dry-run and inspect `data/paper-learning/runs/<date>.json`.
- For real Notion validation, use `--limit 1` first to avoid creating or updating a full batch while testing.
- `process_notion_queue.py` returning `processed: []` is normal when no Paper Inbox row has `Status = Selected`; it validates queue query plumbing but not deep-note creation.
- After deleting Notion properties, verify generated payloads do not contain the removed property names. Existing Notion UI column order is only a usability concern; API reads and writes use property names.

## Output Contract

The daily stage creates or updates:

- Notion `Paper Inbox` rows.
- One Notion daily report page.
- One Feishu daily report document or webhook message.
- One local run artifact under `data/paper-learning/runs/`.
- Optional deep-reading request artifacts as execution/debugging byproducts.

The queue stage creates or updates:

- Notion `Deep Notes` rows.
- `Paper Inbox` status, archive fields, and deep-note relation.
- Local processing results printed as JSON.

## Notion Rules

- Treat Notion as the only workflow state source.
- Treat chat as the primary deep-reading trigger surface. Notion `Selected` is a human candidate signal, not an automatic execution trigger by itself.
- Deep Note page titles should be stable and searchable. Use `笔记：<论文原标题>` for the Notion page title instead of the ljg-paper condensed title.
- `Digest Summary` in Notion should be normalized to a pure summary. Strip source-side institution prefixes before writing it into the inbox row, but keep the original daily report rendering unchanged.
- `Human Instruction` is human-only input. The automation must never inject debug logs, test notes, or other machine-generated text into this field.
- When a chat-triggered deep-reading request resolves from Notion `Selected` or an agent-chosen subset, the caller should confirm the candidate list with the user before executing the queue stage.
- Do not overwrite manually set `Research Areas` unless the user explicitly requests force reclassification.
- Treat `Institutions` as a weak rich-text label.
- Use `Proposed Area` for new taxonomy ideas instead of creating official `Research Areas` automatically.

## Maintenance Guidance

- Prefer improving this skill’s SOP and trigger logic before adding new workflow scripts.
- Add Python entrypoints only when they provide a stable, reusable primitive or a rehearsal/debugging capability.
- If a future change is primarily about user intent, clarification, or confirmation, solve it here in the skill first.

## References

- Starter research areas: `references/research_areas.example.json`
- Config template: `templates/config.example.json`
- Feishu notification research: `references/feishu_notification_research.md`
- ljg-paper Org adapter: configure `deep_reading.mode = "org_artifact"` after an agent runtime has used the `ljg-paper` skill and written the resulting Org document into `deep_reading.org_artifact_dir`.
- Artifact naming helper: `arxiv:2605.00001` becomes `arxiv_2605.00001.org`.
