---
name: paper-daily
description: Paper Daily recall: use for daily arXiv LLM/Agent paper discovery, candidate ranking, metadata readiness, summary-request preparation, and README/feed publishing.
---

# Paper Daily

Use this skill when you want broad daily recall of LLM/Agent papers from arXiv. The default goal is coverage first, not deep reading.

## Preference Profile
When judging recalled papers, prioritize the user's taste over generic paper quality.

- Strong interests: `Agentic RL`, `Rubric`, `Agents`, `On-Policy Distillation`, `Reasoning`, `Reinforcement Learning`, `Benchmark`, `Synthetic Data Generation`
- Secondary interests: agent workflows, multi-agent systems, memory, tool use, skill learning, evaluation, and agent infrastructure
- Prefer papers that are technically concrete, empirically grounded, or benchmark-oriented
- Keep technical reports and major-lab papers unless they are clearly off-taste or too weak to justify inclusion
- Aim for a final daily list of about `20` papers unless the user asks otherwise.
- Use `50` arXiv results per priority keyword by default so daily recall is coverage-oriented.

## Workflow

Use context-driven orchestration instead of treating one script as the whole workflow. The local scripts are deterministic primitives; the skill decides the next primitive from current artifacts, failures, and user intent.

### Orchestration Loop

1. Assess the date first.
   - Read the per-date run state, discovery artifact, metadata cache, summary artifacts, and pending metadata queue.
   - Identify the smallest current gap: missing candidate pack, missing metadata, missing summary, or ready-to-finalize.
   - Done when you can name exactly one current stage: `missing_candidates`, `candidate_ready`, `finalize_blocked`, `final_ready`, or `final_published`.
2. Produce a candidate pack only when needed.
   - Reuse an existing `discovered-YYYY-MM-DD.json` or run state when it is clearly for the requested date.
   - Run discovery only when no usable candidate pack exists or the user explicitly asks for fresh recall.
   - Give discovery a global `--budget-seconds` so arXiv API retries, listing fallback, and HTML hydration cannot consume the whole interactive context.
   - Keep `--api-search-budget-seconds` smaller than the global budget, so a slow arXiv API attempt still leaves time for listing fallback.
   - Keep Agent Reach / Exa enabled as a tertiary recall fallback when the arXiv API is unavailable or suspiciously returns zero results. It only contributes candidates after the arXiv abs page confirms the target UTC submitted date.
   - Disable that tertiary fallback with `--disable-agent-reach-fallback` when debugging Agent Reach or mcporter itself.
   - In listing fallback, accept `arxiv-listing` / `partial` records only into the recall `candidate_pool`; do not treat them as final selected papers.
   - Final selection and summary requests require complete metadata, especially a non-empty abstract.
   - When a fresh discovery artifact exists, pass it through `run_daily.py --discovered-json ...` so ranking context and source fields are preserved.
   - Done when the date has a candidate pool and every selected candidate is metadata-complete or explicitly listed as a blocker.
3. Improve readiness in bounded steps.
   - Metadata enrichment is API-first and non-blocking at the workflow level.
   - Use `enrich_metadata.py` as a short worker with a time/paper budget.
   - Do not switch to HTML fallback on the first API failure; allow fallback only after the retry threshold or when the current context shows continued transient API failure.
   - Use `--force-due` only when the current conversation/run context makes progress more important than waiting for `next_retry_at`, for example after repeated 429s in an interactive repair session.
   - Treat scripted HTML parsing as the normal webpage fallback. If that fails because the page shape changed or a specific paper is anomalous, use the runtime browser context as a manual rescue for that small set of papers, then write the standard metadata artifact.
   - If summary artifacts are missing, run `prepare_missing_summary_requests.py` and generate only the missing artifacts instead of repeatedly enriching metadata or hand-writing ad hoc JSON.
   - If summary preparation reports blocked metadata, run metadata enrichment first; do not summarize title-only or listing-only records.
   - Done when `check_daily_status.py` reports `final_ready`, or the remaining blockers are printed with paper ids and next command.
4. Finalize explicitly.
   - Promote candidate output to official README/feed/state only when readiness checks pass.
   - Do not let a background metadata task silently rewrite official publishing artifacts.
   - Done when `finalize_daily.py` succeeds and the status is `final_published`.

### Status Semantics

- `candidate_ready`: a selected candidate pack exists for the date, but official publishing may still be blocked.
- `finalize_blocked`: candidate pack exists, but metadata or summary artifacts are incomplete.
- `final_ready`: all selected papers meet the publishing gate; the date can be finalized.
- `final_published`: official README/feed/state artifacts have been written.

For metadata, prefer state over source:

- `api_pending` / `api_retrying`: keep trying arXiv API in bounded worker steps.
- `api_complete`: official structured metadata is cached.
- `html_complete`: all required fields are present from arXiv HTML fallback.
- `failed_exhausted`: API and fallback both failed; report this as an explicit blocker.

Official publishing requires complete fields, not necessarily `api_complete`. Requiring API source would make arXiv API a hard dependency again.

### Recall Ladder

Discovery climbs this ladder only as needed:

1. arXiv API search over priority keywords `Agent`, `Agents`, `LLM` and categories `cs.AI`, `cs.CL`, `cs.LG`, `stat.ML`, `cs.SE`, `cs.MA`.
2. arXiv listing + abs HTML fallback when the API fails or exhausts its budget.
3. Agent Reach / Exa recall when arXiv discovery is unavailable or suspiciously empty; arXiv abs HTML must confirm the target UTC submitted date before a candidate is accepted.

After recall, dedupe by normalized arXiv id, filter obvious non-LLM/Agent noise, rank by keyword/category/institution signals, and keep about `20` papers when supply allows.

## Stage Boundaries

- `discover.py` is recall-only. It queries arXiv metadata, ranks candidates, writes a lightweight discovery artifact, and does not require model credentials.
- `prepare_summary_requests.py` prepares runtime summary-artifact requests for the runtime skill. The actual LLM work should happen outside the local scripts, using skill context instead of a fixed in-script model workflow.
- `run_daily.py` is the compatibility entrypoint for candidate production and gated publishing. It must not wait on long metadata recovery.
- `enrich_metadata.py` is a bounded metadata worker. It tries arXiv API first and only falls back to HTML after the configured threshold.
- `check_daily_status.py` is the skill-facing readiness probe. Prefer it over reading logs.
- `prepare_missing_summary_requests.py` is the skill-facing summary gap probe. It reads run state and emits requests only for missing summary artifacts.
- `finalize_daily.py` is the explicit official publishing step. It consumes a ready candidate run and writes README/feed/state. After a successful `final_published`, it sends a **Feishu reminder** (a lightweight interactive card listing the published papers) via `paper_daily/notify.py` when `FEISHU_WEBHOOK_URL` is set (optionally signed with `FEISHU_WEBHOOK_SECRET`). The reminder is best-effort: a delivery failure prints `notify=failed` but never fails finalize, and an unset webhook is a silent `notify=skipped`. Use `--no-notify` to suppress it or `--notify-dry-run` to build the payload without sending. This is the producer-side `daily_ready` notification described in `skill/paper-learning/references/feishu_notification_research.md`; it does not replace paper-learning's full-report `FeishuClient.deliver_report`.
- `generate_feed.py` is a lower-level legacy canonical/feed writer. Prefer `finalize_daily.py` for daily operation because it enforces readiness state.
- `--view-only` prevents repository writes, but it still requires the summary artifacts because it validates the canonical publishing path.
- If the goal is only to test arXiv recall or Notion orchestration without summaries, do not use `run_daily.py`; use `discover.py` or the `paper-learning --skip-summary` path.

## Output Contract
The skill should produce two outputs in sequence:

1. `Paper list`
   - around `20` papers by default
   - include arXiv ID, title, link, date, and inferred keywords
2. `Report`
   - a bilingual report based on the selected paper list
   - include a short batch overview, then per-paper entries
   - do not expose internal filtering, ranking, or selection criteria in the report

## Report Format
After the paper list, write the report in concise Markdown with:

### 1. Batch Overview
- Summarize the dominant themes in the selected batch
- State the practical reading value of the batch
- Keep this section short

### 2. Per-Paper Entries
For each selected paper, include:

1. Paper title
2. Authors and venue/source
3. Link(s) and date
4. Chinese review, around `200-300` Chinese words
5. English review in concise academic prose
6. Metadata table with semantic keywords, not raw arXiv categories
7. Appendix when useful, such as code, project page, benchmark relevance, or related papers

## Writing Guidance
- The report is reader-facing. Do not mention filtering standards, ranking rules, taste profile, score logic, or why a paper was selected.
- The report should still be analytical, not just a list rewrite.
- Borrow the paper-summary style, but simplify it for abstract-level evidence: background -> concrete problem -> what the paper does -> method shape -> reported evidence.
- Adapt that style to abstract-level evidence; do not write as if the full paper was read.
- Prefer compact, evidence-based writing over template-heavy praise.
- Use `title + abstract + categories + institution hints` as the main basis for judgment, but surface semantic keywords instead of raw arXiv categories in the report.
- Do not pretend full-paper certainty when only abstract-level evidence is available.
- The Chinese review should cover: background, challenge, what the paper does, core method, and reported evidence. Do not force limitations unless the abstract explicitly states a constraint.
- The English review should be concise, factual, and non-formulaic.
- The metadata table should include fields such as: arXiv ID, keywords, authors, institution hints, code availability, and source/date.
- Infer `keywords` from the paper topic using concise labels such as `Agent`, `RL`, `Benchmark`, `Reasoning`, `Synthetic Data`, `Evaluation`, `Distillation`, `Tool Use`, or `Multimodal`.
- Keep the batch overview short so most of the output budget goes to the selected papers.
- Avoid generic motivation such as "LLMs are important." Start from the technical baseline or task setting.
- Do not copy abstract sentences verbatim. Reframe the paper in your own words.
- If the abstract reports numbers, include the headline numbers and baseline context. If it does not, say the result evidence is not visible from the abstract.

## Commands

Read `references/commands.md` when you need exact CLI syntax.

## Scheduled Run Date Semantics

- All `--date` values in `discover.py`, `run_daily.py`, `check_daily_status.py`, `prepare_summary_requests.py`, `prepare_missing_summary_requests.py`, `enrich_metadata.py`, and `finalize_daily.py` are UTC dates.
- For scheduled production runs triggered in a non-UTC timezone, target the most recent fully completed UTC date instead of the local calendar date.
- Example: if the automation starts at `2026-06-08 10:30 Asia/Shanghai`, use `--date 2026-06-07` because the UTC day `2026-06-08` is still in progress.
- If an automation or agent is orchestrating this workflow, explicitly tell it to use the repository's `paper-daily` skill instead of treating the task as generic script execution.

## Judging Stage

After recall:

- Read the top recalled papers from `selected` or `ranked`.
- Judge only from `title`, `abstract`, categories, and lightweight institution hints.
- Prefer papers aligned with the preference profile.
- Keep the final list around `20` papers unless the user asks for a different size.
- After the final list is fixed, write the report immediately instead of stopping at the list.
- Replace raw arXiv categories with inferred topic keywords in user-facing metadata.
- Keep judging rationale internal; the user-facing report should focus on the papers.

## Notes

- arXiv Atom metadata usually does not include author affiliations. Institution matching in this MVP checks title/abstract and PDF first-page extraction, so it remains a weak signal compared with a dedicated affiliation enricher.
- `discover.py` is the primary command for this skill. It stays metadata-first and does not download PDFs.
- `discover.py` always saves a lightweight recall artifact unless you redirect it with `--out`.
- Shared defaults are `--max-results-per-keyword 50` and `--select 20` across discovery, publishing, and paper-learning integration unless explicitly overridden.
- The LLM judging step belongs to the skill workflow, not to the local discovery script. Judge by the preference profile above, not by generic quality alone.
- `run_daily.py` is a publishing workflow. It does not call a fixed model provider; it expects summary artifacts generated by the runtime skill.
- Keep short aliases conservative. Do not match ambiguous aliases like `MIT` across the full abstract because words such as `committed` can create false positives.
- Respect arXiv API etiquette. The CLI defaults to a delay between keyword queries.
- Summary artifacts are JSON files keyed by arXiv ID under `data/paper-daily/summary-artifacts/` by default.
- This skill operates on `README.md`, `README_en.md`, `summary/`, and `summary_en/`.

## References

- Commands: `references/commands.md`
- Institution whitelist: `references/institutions.json`
- Discovery implementation: `scripts/paper_daily/`
