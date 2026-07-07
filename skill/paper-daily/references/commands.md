# Paper Daily Commands

All dates are UTC arXiv `submittedDate` values.

## Discovery

Run a real arXiv dry-run:

```bash
python3 skill/paper-daily/scripts/discover.py --date YYYY-MM-DD
```

Write JSON output:

```bash
python3 skill/paper-daily/scripts/discover.py --date YYYY-MM-DD --json --out /tmp/papers.json
```

Ask for broad recall:

```bash
python3 skill/paper-daily/scripts/discover.py --date YYYY-MM-DD --max-results-per-keyword 50 --select 20
```

Keep interactive discovery bounded:

```bash
python3 skill/paper-daily/scripts/discover.py --date YYYY-MM-DD --max-results-per-keyword 50 --select 20 --budget-seconds 180 --api-search-budget-seconds 30
```

Disable the Agent Reach fallback while debugging it:

```bash
python3 skill/paper-daily/scripts/discover.py --date YYYY-MM-DD --disable-agent-reach-fallback
```

Check Agent Reach before relying on it:

```bash
agent-reach doctor --json
mcporter call 'exa.web_search_exa(query: "site:arxiv.org/abs Agent LLM", numResults: 1)'
```

## Candidate Runs

Prepare runtime summary requests:

```bash
python3 skill/paper-daily/scripts/prepare_summary_requests.py --repo-root . --date YYYY-MM-DD --out /tmp/paper-daily-summary-requests.json
```

Create or inspect a candidate run:

```bash
python3 skill/paper-daily/scripts/run_daily.py --repo-root . --date YYYY-MM-DD
python3 skill/paper-daily/scripts/run_daily.py --repo-root . --date YYYY-MM-DD --view-only
```

Create a candidate run from a known discovery artifact:

```bash
python3 skill/paper-daily/scripts/run_daily.py --repo-root . --discovered-json /tmp/discovered-YYYY-MM-DD.json --view-only
```

Manually publish specific arXiv IDs with an explicit display date:

```bash
python3 skill/paper-daily/scripts/run_daily.py --repo-root . --date YYYY-MM-DD --arxiv-id 2505.14359v6 --arxiv-id 2512.06746
```

## Readiness And Publishing

Check whether a candidate run is ready to finalize:

```bash
python3 skill/paper-daily/scripts/check_daily_status.py --repo-root . --date YYYY-MM-DD
```

Run a bounded metadata worker slice:

```bash
python3 skill/paper-daily/scripts/enrich_metadata.py --repo-root . --date YYYY-MM-DD --budget-seconds 60 --max-papers 5
```

Prepare requests for only missing summary artifacts:

```bash
python3 skill/paper-daily/scripts/prepare_missing_summary_requests.py --repo-root . --date YYYY-MM-DD --out /tmp/missing-summary-requests.json
```

Finalize a ready candidate run into official repo artifacts:

```bash
python3 skill/paper-daily/scripts/finalize_daily.py --repo-root . --date YYYY-MM-DD
```

Generate only canonical/feed outputs:

```bash
python3 skill/paper-daily/scripts/generate_feed.py --repo-root . --date YYYY-MM-DD
```
