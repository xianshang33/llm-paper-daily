#!/bin/bash
# Paper Daily CLI - Simplified interface to paper-daily skill

set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
REPO_ROOT="$SCRIPT_DIR"

# Default values
DATE=""
ACTION="discover"
VIEW_ONLY=false
DRY_RUN=false

# Print help
show_help() {
    cat << EOF
Usage: ./run-paper-daily.sh [OPTIONS]

Paper Daily - arXiv paper discovery and ranking

OPTIONS:
  discover [DATE]         Discover and rank papers for a date (default)
  status [DATE]          Check publication status for a date
  enrich [DATE]          Enrich metadata for papers
  run [DATE]             Run full daily pipeline
  finalize [DATE]        Finalize and publish to README

COMMON FLAGS:
  --date DATE            Paper discovery date (YYYY-MM-DD, default: yesterday UTC)
  --view-only            Preview without writing to repo
  --dry-run              Dry run without external calls
  --help                 Show this help message

EXAMPLES:
  ./run-paper-daily.sh discover --date 2026-05-31
  ./run-paper-daily.sh status --date 2026-05-31
  ./run-paper-daily.sh enrich --date 2026-05-31 --view-only
  ./run-paper-daily.sh finalize --date 2026-05-31

EOF
}

# Parse arguments
if [[ $# -eq 0 ]] || [[ "$1" == "--help" ]] || [[ "$1" == "-h" ]]; then
    show_help
    exit 0
fi

ACTION=$1
shift

while [[ $# -gt 0 ]]; do
    case $1 in
        --date)
            DATE="$2"
            shift 2
            ;;
        --view-only)
            VIEW_ONLY=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --help)
            show_help
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            show_help
            exit 1
            ;;
    esac
done

# If no date provided, use yesterday's UTC date
if [[ -z "$DATE" ]]; then
    DATE=$(python3 -c "from datetime import datetime, timedelta; print((datetime.utcnow() - timedelta(days=1)).strftime('%Y-%m-%d'))")
fi

# Execute action
case $ACTION in
    discover)
        echo "🔍 Discovering papers for $DATE..."
        python3 skill/paper-daily/scripts/discover.py --date "$DATE" --max-results-per-keyword 50 --select 20 --budget-seconds 180
        EXIT_CODE=$?

        if [ $EXIT_CODE -ne 0 ]; then
            echo "❌ Error during discovery"
            exit 1
        fi

        # Check the generated JSON file
        DISCOVERED_FILE="skill/paper-daily/output/discovered-$DATE.json"
        if [ ! -f "$DISCOVERED_FILE" ]; then
            echo "❌ No output file generated"
            exit 1
        fi

        SELECTED=$(python3 -c "import json; data=json.load(open('$DISCOVERED_FILE')); print(data['counts']['selected'])")

        if [ "$SELECTED" -eq 0 ]; then
            echo ""
            echo "⚠️  ERROR: No papers found for $DATE"
            echo "This date may have had no Agent/LLM paper submissions."
            echo ""
            PREV_DATE=$(python3 -c "from datetime import datetime, timedelta; print((datetime.strptime('$DATE', '%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%d'))")
            NEXT_DATE=$(python3 -c "from datetime import datetime, timedelta; print((datetime.strptime('$DATE', '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d'))")
            echo "🔍 Try nearby dates:"
            echo "   ./run-paper-daily.sh discover --date $PREV_DATE"
            echo "   ./run-paper-daily.sh discover --date $NEXT_DATE"
            exit 1
        fi

        # Print summary
        echo ""
        echo "✅ Discovered $SELECTED papers"
        echo "📄 Full output: $DISCOVERED_FILE"
        ;;
    status)
        echo "📊 Checking status for $DATE..."
        OUTPUT=$(python3 skill/paper-daily/scripts/check_daily_status.py --repo-root . --date "$DATE" 2>&1)
        EXIT_CODE=$?

        if [ $EXIT_CODE -ne 0 ] || echo "$OUTPUT" | grep -q "No run found"; then
            echo "❌ No papers found for $DATE"
            echo "Run discovery first: ./run-paper-daily.sh discover --date $DATE"
            exit 1
        fi

        echo "$OUTPUT"
        ;;
    enrich)
        echo "🔧 Enriching metadata for $DATE..."
        python3 skill/paper-daily/scripts/enrich_metadata.py --repo-root . --date "$DATE" --budget-seconds 120 --max-papers 20 --force-due
        ;;
    run)
        echo "▶️  Running daily pipeline for $DATE..."
        if $VIEW_ONLY; then
            python3 skill/paper-daily/scripts/run_daily.py --repo-root . --date "$DATE" --view-only
        else
            python3 skill/paper-daily/scripts/run_daily.py --repo-root . --date "$DATE"
        fi
        ;;
    finalize)
        echo "✅ Finalizing and publishing $DATE..."
        python3 skill/paper-daily/scripts/finalize_daily.py --repo-root . --date "$DATE"
        ;;
    *)
        echo "Unknown action: $ACTION"
        show_help
        exit 1
        ;;
esac

echo "✓ Done!"
