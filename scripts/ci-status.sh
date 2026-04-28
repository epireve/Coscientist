#!/bin/sh
# scripts/ci-status.sh — query GitHub Actions CI for the current branch.
#
# Wraps `gh` CLI. Surfaces:
#   - Latest run status + conclusion
#   - Failed step + log tail when red
#   - Quick rerun command
#
# Usage:
#   scripts/ci-status.sh           # latest run, current branch
#   scripts/ci-status.sh --watch   # poll until terminal state
#   scripts/ci-status.sh --logs    # full failed-step logs
#   scripts/ci-status.sh --rerun   # rerun failed jobs

set -e

if ! command -v gh >/dev/null 2>&1; then
    echo "[ci-status] gh CLI not installed. brew install gh"
    exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
    echo "[ci-status] gh not authed. Run: gh auth login"
    exit 1
fi

BRANCH=$(git rev-parse --abbrev-ref HEAD)
REPO=$(gh repo view --json nameWithOwner -q .nameWithOwner 2>/dev/null)

case "${1:-}" in
    --watch)
        echo "[ci-status] watching latest run on $BRANCH..."
        RUN_ID=$(gh run list --branch "$BRANCH" --limit 1 \
            --json databaseId -q '.[0].databaseId')
        gh run watch "$RUN_ID"
        exit $?
        ;;
    --logs)
        echo "[ci-status] full failed-step logs for $BRANCH..."
        RUN_ID=$(gh run list --branch "$BRANCH" --limit 1 \
            --json databaseId -q '.[0].databaseId')
        gh run view "$RUN_ID" --log-failed
        exit $?
        ;;
    --rerun)
        RUN_ID=$(gh run list --branch "$BRANCH" --limit 1 \
            --json databaseId -q '.[0].databaseId')
        echo "[ci-status] rerunning failed jobs of $RUN_ID..."
        gh run rerun "$RUN_ID" --failed
        exit $?
        ;;
esac

# Default: status of latest run.
echo "[ci-status] repo=$REPO branch=$BRANCH"
gh run list --branch "$BRANCH" --limit 1 \
    --json databaseId,status,conclusion,workflowName,createdAt,headSha \
    --template '
{{- range . -}}
Run #{{.databaseId}} — {{.workflowName}}
  Status:     {{.status}}
  Conclusion: {{.conclusion}}
  Started:    {{.createdAt}}
  Commit:     {{.headSha}}
{{end -}}
'

CONCLUSION=$(gh run list --branch "$BRANCH" --limit 1 \
    --json conclusion -q '.[0].conclusion')
RUN_ID=$(gh run list --branch "$BRANCH" --limit 1 \
    --json databaseId -q '.[0].databaseId')

if [ "$CONCLUSION" = "failure" ]; then
    echo ""
    echo "[ci-status] failed. Failed steps:"
    gh run view "$RUN_ID" --json jobs \
        -q '.jobs[] | select(.conclusion=="failure") |
            "  ✗ \(.name): " + (
                (.steps[] | select(.conclusion=="failure") | .name)
                // "(no failed step)"
            )' || true
    echo ""
    echo "[ci-status] options:"
    echo "  scripts/ci-status.sh --logs   # see failure logs"
    echo "  scripts/ci-status.sh --rerun  # rerun failed jobs"
fi
