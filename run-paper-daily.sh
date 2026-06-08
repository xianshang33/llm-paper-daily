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
        # --retries 3 activates the client's 429 backoff (Retry-After / exponential),
        # which is dead code at the default --retries 0.
        MAX_PASSES=8
        PREV_REMAINING=-1
        STALL=0
        ENRICH_ERR=$(mktemp)
        for pass in $(seq 1 $MAX_PASSES); do
            # Capture stdout (the JSON result) and stderr separately: a traceback
            # on stderr must never corrupt the JSON channel. Tolerate a non-zero
            # exit (|| ENRICH_RC=$?) so a transient hard error retries on the next
            # pass instead of aborting the whole script under `set -e`.
            ENRICH_OUT=$(python3 skill/paper-daily/scripts/enrich_metadata.py --repo-root . --date "$DATE" \
                --budget-seconds 120 --max-papers 20 --retries 3 --force-due 2>"$ENRICH_ERR") && ENRICH_RC=0 || ENRICH_RC=$?
            REMAINING=$(echo "$ENRICH_OUT" | python3 -c \
                'import sys,json; d=json.load(sys.stdin); print(d.get("remaining_eligible", -1))' 2>/dev/null || echo "-1")
            FINALIZE_READY=$(echo "$ENRICH_OUT" | python3 -c \
                'import sys,json; print("yes" if json.load(sys.stdin).get("finalize_ready") else "no")' 2>/dev/null || echo "no")

            if [ "$REMAINING" = "-1" ]; then
                # enrich did not return parseable JSON — surface the real cause
                # rather than letting the stall branch mislabel it as throttling.
                echo "  pass $pass/$MAX_PASSES: enrich returned no JSON (exit=$ENRICH_RC)"
                tail -n 3 "$ENRICH_ERR" | sed 's/^/    | /'
            else
                echo "  pass $pass/$MAX_PASSES: remaining_eligible=$REMAINING finalize_ready=$FINALIZE_READY"
            fi

            if [ "$FINALIZE_READY" = "yes" ]; then
                echo "✅ All selected papers enriched"
                break
            fi
            if [ "$REMAINING" = "0" ]; then
                echo "✅ Metadata enrich complete (finalize blocked — run summary generation then finalize)"
                break
            fi
            if [ "$REMAINING" = "$PREV_REMAINING" ]; then
                STALL=$((STALL+1))
            else
                STALL=0
            fi
            if [ "$STALL" -ge 2 ]; then
                if [ "$REMAINING" = "-1" ]; then
                    echo "❌ enrich failed to return JSON for 2 passes (exit=$ENRICH_RC). See errors above."
                else
                    echo "⚠️  No progress for 2 passes ($REMAINING still remaining). Likely arXiv throttling."
                    echo "    Retry 'enrich' later — the bounded worker resumes the same pending queue."
                    echo "    (Do not hand-seed candidates with --arxiv-id; the metadata cache derives"
                    echo "     titles/authors from the run-state pack and arXiv, not from manual stubs.)"
                fi
                break
            fi
            PREV_REMAINING="$REMAINING"
            [ "$pass" -lt "$MAX_PASSES" ] && sleep 8
        done
        rm -f "$ENRICH_ERR"
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
