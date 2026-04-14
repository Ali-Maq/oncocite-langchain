#!/usr/bin/env bash
# Attach the normalized CIViC artifact + coverage report to the v1.0-preprint
# GitHub Release on both repositories, and update the README download links.
set -euo pipefail

JSONL=${1:-data/normalized/civic_normalized_evidence_v1.jsonl}
REPORT=${2:-data/normalized/civic_normalized_coverage_report.md}

if [[ ! -f "$JSONL" ]]; then
    echo "ERROR: $JSONL not found — run normalize_civic_corpus.py first" >&2
    exit 2
fi
if [[ ! -f "$REPORT" ]]; then
    echo "ERROR: $REPORT not found — run normalize_civic_corpus.py first" >&2
    exit 2
fi

# Compress the JSONL for a smaller upload
GZ="${JSONL}.gz"
gzip -kf "$JSONL"
ls -la "$GZ" "$REPORT"

for repo in Ali-Maq/oncocite-langchain Ali-Maq/civic-extraction-agent; do
    echo "--- $repo ---"
    gh release upload v1.0-preprint "$GZ" "$REPORT" --repo "$repo" --clobber
done

echo "Done. Download URLs:"
for repo in Ali-Maq/oncocite-langchain Ali-Maq/civic-extraction-agent; do
    echo "  https://github.com/$repo/releases/download/v1.0-preprint/$(basename "$GZ")"
    echo "  https://github.com/$repo/releases/download/v1.0-preprint/$(basename "$REPORT")"
done
