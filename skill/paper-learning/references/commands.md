# Paper Learning Commands

All `--date` values are UTC arXiv `submittedDate` values.

## Daily Stage

Run the daily stage:

```bash
python3 skill/paper-learning/scripts/run_daily_learning.py --config ~/.paper-learning/config.json --date YYYY-MM-DD
```

Prepare daily-stage summary requests:

```bash
python3 skill/paper-learning/scripts/prepare_daily_learning_requests.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --limit 3
```

Dry-run the daily stage:

```bash
python3 skill/paper-learning/scripts/run_daily_learning.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --dry-run
```

Dry-run without generated summaries:

```bash
python3 skill/paper-learning/scripts/run_daily_learning.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --dry-run --skip-summary
```

## Deep Reading Stage

Resolve deep-reading requests:

```bash
python3 skill/paper-learning/scripts/request_deep_reading.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --use-notion-selected
python3 skill/paper-learning/scripts/request_deep_reading.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --all-from-report
python3 skill/paper-learning/scripts/request_deep_reading.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --paper-id arxiv:2605.19932
```

Confirm a resolved request:

```bash
python3 skill/paper-learning/scripts/confirm_deep_reading_request.py --request data/paper-learning/runs/YYYY-MM-DD/deep-reading-request.json
```

Prepare `ljg-paper` requests:

```bash
python3 skill/paper-learning/scripts/prepare_ljg_paper_requests.py --config ~/.paper-learning/config.json --limit 1
python3 skill/paper-learning/scripts/prepare_ljg_paper_requests.py --config ~/.paper-learning/config.json --deep-reading-request-json data/paper-learning/runs/YYYY-MM-DD/deep-reading-request.json
```

Run the queue executor:

```bash
python3 skill/paper-learning/scripts/process_notion_queue.py --config ~/.paper-learning/config.json
```

## Local Rehearsal

Create a local selected-papers artifact:

```bash
python3 skill/paper-learning/scripts/prepare_selected_papers.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --limit 1
```

Prepare local queue-stage requests:

```bash
python3 skill/paper-learning/scripts/prepare_queue_stage_requests.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --limit 1
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

Full local rehearsal:

```bash
python3 skill/paper-learning/scripts/rehearse_pipeline.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --daily-limit 3 --queue-limit 1 --include-queue
```

## Readiness And Setup

Check readiness:

```bash
python3 skill/paper-learning/scripts/check_pipeline_readiness.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --stage daily --limit 3
python3 skill/paper-learning/scripts/check_pipeline_readiness.py --config ~/.paper-learning/config.json --date YYYY-MM-DD --stage queue --selected-papers-json data/paper-learning/runs/YYYY-MM-DD/selected-papers.json --limit 1
```

Bootstrap Notion:

```bash
python3 skill/paper-learning/scripts/bootstrap_notion.py --config skill/paper-learning/templates/config.example.json --parent-page <NOTION_PAGE_URL> --write-config
```

Load local secrets before real Notion or Feishu calls:

```bash
. skill/paper-learning/scripts/load_env.sh .local/paper-learning.env
```
