#!/bin/bash
# Paper Learning CLI - Simplified interface to paper-learning skill

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$SCRIPT_DIR"
CONFIG_FILE="${HOME}/.paper-learning/config.json"

# Load environment if available
if [[ -f .local/paper-learning.env ]]; then
    source .local/paper-learning.env
fi

# Default values
DATE=""
ACTION="daily"
DRY_RUN=false

# Print help
show_help() {
    cat << EOF
Usage: ./run-paper-learning.sh [OPTIONS]

Paper Learning - Notion orchestration and deep reading workflow

ACTIONS:
  daily [DATE]           Run daily learning pipeline (publish to Notion)
  queue                  Process Notion queue
  deep-read [PAPERS]     Trigger deep reading for papers
  status [DATE]          Check learning workflow status

COMMON FLAGS:
  --date DATE            Learning pipeline date (YYYY-MM-DD, default: previous UTC date)
  --dry-run              Dry run without writing to Notion/Feishu
  --config PATH          Custom config file (default: ~/.paper-learning/config.json)
  --skip-summary         Test discovery without generating summaries
  --help                 Show this help message

EXAMPLES:
  ./run-paper-learning.sh daily --date 2026-05-31
  ./run-paper-learning.sh daily --dry-run
  ./run-paper-learning.sh queue
  ./run-paper-learning.sh deep-read 2606.01152 2606.01311

REQUIREMENTS:
  - Configuration file at ~/.paper-learning/config.json
  - Environment variables from .local/paper-learning.env (optional)
  - Notion database setup

EOF
}

# Parse arguments
if [[ $# -eq 0 ]] || [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    show_help
    exit 0
fi

ACTION=$1
shift

PAPERS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        --date)
            DATE="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --config)
            CONFIG_FILE="$2"
            shift 2
            ;;
        --skip-summary)
            SKIP_SUMMARY="--skip-summary"
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            # Treat as paper ID for deep-read
            PAPERS+=("$1")
            shift
            ;;
    esac
done

# If no date provided, use the previous complete UTC date.
# --date means arXiv submittedDate (UTC); "today" is usually still incomplete,
# so the previous UTC day is the safe default — and consistent with run-paper-daily.sh.
if [[ -z "$DATE" ]]; then
    DATE=$(python3 -c "from datetime import datetime, timedelta; print((datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d'))")
fi

# Check config file exists
if [[ ! -f "$CONFIG_FILE" ]]; then
    echo "❌ Error: Config file not found at $CONFIG_FILE"
    echo "Please create config from ~/.paper-learning/config.json or use --config"
    exit 1
fi

# Execute action
case $ACTION in
    daily)
        echo "📅 Running daily learning pipeline for $DATE..."
        CMD="python3 skill/paper-learning/scripts/run_daily_learning.py --config $CONFIG_FILE --date $DATE"
        if $DRY_RUN; then
            CMD="$CMD --dry-run"
        fi
        if [[ -n "$SKIP_SUMMARY" ]]; then
            CMD="$CMD $SKIP_SUMMARY"
        fi
        $CMD
        echo "✅ Daily pipeline complete"
        echo "📝 Check Notion Paper Inbox for new entries"
        ;;
    queue)
        echo "📋 Processing Notion queue..."
        python3 skill/paper-learning/scripts/process_notion_queue.py --config "$CONFIG_FILE" --limit 5
        echo "✅ Queue processing complete"
        ;;
    deep-read)
        if [[ ${#PAPERS[@]} -eq 0 ]]; then
            echo "❌ Error: No papers specified for deep-read"
            echo "Usage: ./run-paper-learning.sh deep-read PAPER_ID [PAPER_ID2...]"
            exit 1
        fi
        echo "📖 Triggering deep reading for ${#PAPERS[@]} papers..."
        for paper_id in "${PAPERS[@]}"; do
            echo "  - $paper_id"
        done
        # This would integrate with deep reading provider
        echo "⚠️  Deep reading trigger requires skill context"
        ;;
    status)
        echo "📊 Checking learning workflow status for $DATE..."
        python3 skill/paper-daily/scripts/check_daily_status.py --repo-root . --date "$DATE"
        ;;
    *)
        echo "❌ Unknown action: $ACTION"
        show_help
        exit 1
        ;;
esac

echo "✓ Done!"
