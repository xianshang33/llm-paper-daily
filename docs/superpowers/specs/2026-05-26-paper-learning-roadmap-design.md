# Paper Learning Roadmap Design

Date: 2026-05-26

## Goal

Improve this repository as a personal research-learning system. The near-term product should help the user move from daily paper discovery to selection, deep reading, and durable Notion knowledge capture with minimal manual coordination.

The roadmap prioritizes:

- A stable daily learning loop.
- Skill-first orchestration instead of fixed script-first workflows.
- Pluggable deep-reading capability, so `ljg-paper` can be optimized or replaced later.
- Enough reliability and diagnostics to support daily use.
- Targeted review of Hugging Face recall quality.
- A Feishu robot notification design, documented now and implemented later.

## Non-Goals

- Do not build a dashboard before the workflow is used regularly.
- Do not build a complex research knowledge graph yet.
- Do not productize public subscriptions in this phase.
- Do not make Feishu a workflow state source.
- Do not hard-code `ljg-paper` as the only possible deep-reading implementation.
- Do not replace the current Python scripts wholesale. Keep scripts as execution primitives where they are useful.

## First Principles

The core problem is not "more paper sources" or "more scripts." The core problem is reducing the cost of deciding what to read, triggering the right depth of processing, and preserving useful research memory.

Therefore:

- Skill behavior should own intent resolution, confirmation, user-specific judgment, and tool selection.
- Scripts should own narrow, repeatable execution steps.
- Notion should remain the durable workflow state.
- Local artifacts should make the workflow debuggable, not become a second source of truth.
- Deep reading should be an interface, not a single implementation.

## Product Shape

### Daily Review

The daily stage should publish a concise Notion Inbox and optional Feishu report. Each paper should carry decision-oriented fields, not just metadata:

- `Reading Value`: why this paper may be useful.
- `Why It Matters`: the technical or research reason to care.
- `Deep Reading Fit`: whether it deserves deep reading now.
- `Suggested Action`: skip, skim, save, or deep read.

These fields should be short. Their job is to help the user decide quickly, not to create another long summary.

### Selection

The user may select papers in three ways:

- Mark `Selected` in Notion.
- Ask in chat for specific paper ids or titles.
- Ask the skill to choose a small subset from the daily report.

Direct, unambiguous single-paper requests may execute immediately. Notion-selected sets, fuzzy references, and agent-selected subsets must first show the resolved candidate list and ask for confirmation.

### Deep Reading

Deep reading should run behind a pluggable provider interface. The default provider is the current `ljg-paper` Org artifact path, but the orchestration must not assume it forever.

The interface should answer:

- What input does the provider need?
- How does the provider report readiness?
- How does the provider produce a `DeepNote`?
- How are provider errors surfaced?
- Which provider version or skill name produced the note?

An initial provider contract can look like:

```text
DeepReadingProvider
- name
- prepare_requests(selected_papers, config) -> request artifacts or instructions
- check_ready(selected_papers, config) -> readiness results
- read(selected_paper, config) -> DeepNote
```

The current `ljg-paper` integration becomes one provider:

```text
LjgPaperOrgProvider
- prepares requests for ljg-paper
- validates Org artifacts
- converts Org artifacts into DeepNote records
```

Later alternatives can be added without changing the queue pipeline:

- A faster abstract-level reading skill.
- A full PDF deep-reading skill.
- A model-specific provider.
- A manual-note import provider.

### Archive

The archive stage should classify notes into existing active research areas when confidence is high. If confidence is low or no active area fits, it should write `Proposed Area` and mark the item for review.

Manual `Research Areas` edits must be preserved unless the user explicitly asks to force reclassification.

## Skill-First Architecture

The `paper-learning` skill should be treated as the product entrypoint. It should decide:

- Which stage the user is asking about.
- Whether a date needs clarification.
- Whether summary artifacts are missing.
- Whether a deep-reading request needs confirmation.
- Which deep-reading provider to use.
- Whether execution should proceed or stop at readiness.

Scripts should remain small execution primitives:

- `run_daily_learning.py`: daily stage execution.
- `process_notion_queue.py`: queue execution once selected papers and provider outputs are available.
- `request_deep_reading.py`: request resolution helper.
- `prepare_ljg_paper_requests.py`: provider-specific preparation for the default deep-reading provider.
- `check_pipeline_readiness.py`: stage readiness checks.
- `rehearse_pipeline.py`: local rehearsal.

The roadmap should avoid pushing more product logic into fixed command combinations. If a task requires judgment or user intent, the skill should own it.

## Reliability Design

### Unified User-Facing Actions

Expose a small set of actions through the skill and optionally through a thin CLI wrapper:

- `daily-check`: validate whether a daily report can run.
- `daily-run`: run the daily stage.
- `deep-check`: validate the selected papers and deep-reading provider readiness.
- `deep-run`: run deep reading.
- `status`: show the state for a given date.

The skill may call underlying scripts, but the user should not need to remember a long command sequence.

### Stage Manifest

Each date should have a manifest under:

```text
data/paper-learning/runs/YYYY-MM-DD/manifest.json
```

The manifest is a local diagnostic snapshot. It records:

- discovery status
- summary artifact readiness
- daily Notion report status
- Feishu delivery status
- selected paper count
- deep-reading provider
- provider readiness
- processed deep-note results
- warnings
- latest error
- recommended next action

Notion remains the workflow source of truth. The manifest only explains local execution state.

### Readiness First

Execution commands should check readiness before mutating external systems. Missing summary artifacts, invalid Notion config, missing Org artifacts, or unresolved paper ids should stop the run before partial execution when possible.

Readiness output should support:

- a concise human-readable summary
- JSON for future automation

### Recovery

Daily failures should be recoverable from existing discovery and summary artifacts. Deep-reading failures should skip existing deep notes unless `--force` is requested.

Errors should be written to:

- the Notion `Error` field when a paper-specific failure occurs
- the local manifest for stage-level failures

## Hugging Face Recall Review

The current Hugging Face recall code is useful but should be revised before it becomes important to daily selection quality.

Observed risks:

- `fetch_hf_daily_papers()` can fail the whole daily pipeline even though Hugging Face is only a supplemental source.
- The code slices `raw[:limit]` before normalization, so invalid items can reduce the effective recall count.
- Hugging Face and arXiv records are not deduplicated. The same arXiv paper can appear as both `arxiv:...` and `hf:...`.
- `score` currently uses `numComments`, which is weak and may not match the desired ordering.
- Hugging Face Daily Papers is broad. Without taste filtering, it can add noise to a personal LLM/Agent workflow.
- The implementation calls the REST endpoint directly. Hugging Face also exposes `HfApi.list_daily_papers(date=..., sort=..., limit=...)`, which may be a better long-term adapter boundary.

Recommended design:

- Treat Hugging Face as a supplemental candidate source, not a final append.
- Fetch, normalize, dedupe by arXiv id where possible, then merge with arXiv candidates.
- Add source provenance such as `hf_rank`, `hf_num_comments`, and `hf_url`.
- Use Hugging Face failures as warnings unless the user explicitly requests a Hugging Face-only run.
- Let the skill decide whether Hugging Face candidates are relevant enough to show.
- Add tests for invalid items, duplicate arXiv ids, endpoint failures, and sort/limit behavior.

References:

- Hugging Face Hub API docs: `https://huggingface.co/docs/hub/main/api`
- Hugging Face `HfApi.list_daily_papers`: `https://huggingface.co/docs/huggingface_hub/main/package_reference/hf_api`

## Feishu Robot Notification Research

This phase should only document a feasible approach. Do not implement the notification module yet.

Current state:

- `FeishuClient.deliver_report()` sends a text webhook payload.
- It does not distinguish reports from operational notifications.
- It does not model event types.
- It does not support signed webhook payloads.
- It does not use card messages for concise actionable alerts.

Feasible future design:

- Add a separate `NotificationClient` or `FeishuNotificationClient`.
- Keep daily report delivery separate from operational notifications.
- Support text messages first, then interactive cards.
- Support optional webhook signing with `timestamp` and `sign`.
- Read credentials from config/env:
  - `FEISHU_WEBHOOK_URL`
  - `FEISHU_WEBHOOK_SECRET` for signed requests
- Emit notifications for:
  - `daily_ready`: report generated, candidate count, Notion link.
  - `deep_reading_confirmation_required`: resolved papers waiting for confirmation.
  - `deep_reading_done`: note count and links.
  - `pipeline_failed`: stage, error summary, recommended recovery action.

Notification content should stay short. Feishu should tell the user what happened and where to act, not duplicate the full report.

References:

- Feishu custom bot guide: `https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot`
- Feishu card message with custom bot: `https://open.feishu.cn/document/common-capabilities/message-card/getting-started/send-message-cards-with-a-custom-bot`

## Backlog

### P0: Personal Learning Loop

- Add decision-oriented paper fields to the daily report model.
- Make the skill expose a clear daily review and deep-reading flow.
- Add a provider abstraction for deep reading.
- Keep `ljg-paper` as the default provider.
- Preserve manual Notion research-area choices.

### P1: Reliability

- Add stage manifest support.
- Make readiness checks the default before execution.
- Add status reporting for a date.
- Improve recovery behavior for partial daily and deep-reading failures.

### P1: Hugging Face Recall

- Add tests for current behavior.
- Decide whether to keep direct REST calls or wrap `huggingface_hub`.
- Dedupe Hugging Face papers against arXiv records.
- Make Hugging Face failures non-blocking by default.
- Add relevance filtering before Hugging Face candidates enter the Inbox.

### P2: Feishu Notifications

- Keep this as a documented design until the core loop is used.
- Later implement a notification client with event types and optional signing.
- Prefer short cards for actionable alerts.

### P2: Knowledge Base Enhancements

- Weekly theme summary.
- Reading history by research area.
- Related-paper suggestions from existing deep notes.
- Proposed area review workflow.

These should wait until there are enough real notes to learn from.

## Testing Strategy

Tests should focus on contracts and failure modes:

- Deep-reading provider contract tests.
- `ljg-paper` provider readiness and conversion tests.
- Manifest update tests.
- Hugging Face normalization, failure, and dedupe tests.
- Notification payload rendering tests when Feishu notifications are implemented.
- End-to-end dry-run tests through daily and deep stages.

Manual verification remains important:

- Run daily dry-run with `--skip-summary`.
- Run queue dry-run from local `selected-papers.json`.
- Inspect generated manifest and Notion dry-run payloads.

## Open Decisions

- Whether to implement the user-facing actions as a new CLI, skill-only instructions, or both.
- Whether to depend on `huggingface_hub` for Hugging Face daily papers or keep direct REST calls.
- What exact decision fields should be written into Notion versus only rendered in reports.
- Which deep-reading provider metadata should be stored on `Deep Notes`.

## Acceptance Criteria

The first implementation plan is successful when:

- The user can run a daily review loop without remembering multiple low-level scripts.
- The user can select papers and trigger deep reading through the skill.
- The default `ljg-paper` provider works behind a replaceable interface.
- The workflow can report what is missing before mutating Notion or Feishu.
- Hugging Face recall risks are either fixed or explicitly downgraded with warnings.
- Feishu robot notifications have a local documented design ready for a later module.

## Implementation Status

- Skill-first operation documented.
- Deep reading provider interface implemented with `ljg-paper-org` as the default provider.
- Queue and readiness paths route through the provider interface.
- Stage manifests record daily and queue status.
- Hugging Face recall is supplemental, deduped against arXiv, and non-blocking by default.
- Feishu robot notification design is documented for a future module; notification sending is not implemented in this slice.
