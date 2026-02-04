#!/usr/bin/env bash
# debug_eval.sh — Run a single NestCheck evaluation and print the full trace.
#
# Usage:
#   ./debug_eval.sh "123 Main St, City, ST"
#   ./debug_eval.sh "123 Main St, City, ST" http://localhost:5001
#
# Requirements:
#   - Server must be running (locally or the URL you specify)
#   - Builder mode cookie required for /debug/eval endpoint
#   - curl and python3 (for JSON formatting) must be available
#
# What it does:
#   1. Sends the address to POST /debug/eval (returns full trace data)
#   2. Prints HTTP status, response JSON, trace summary
#   3. Highlights the slowest stages and API calls

set -euo pipefail

ADDRESS="${1:?Usage: $0 \"address\" [base_url]}"
BASE_URL="${2:-http://localhost:5001}"
BUILDER_SECRET="${BUILDER_SECRET:-nestcheck-builder-2024}"

echo "=== NestCheck Debug Evaluation ==="
echo "Address:  $ADDRESS"
echo "Server:   $BASE_URL"
echo ""

# Make the request — store HTTP status and body separately
HTTP_RESPONSE=$(curl -s -w "\n%{http_code}" \
  -X POST "$BASE_URL/debug/eval" \
  -H "Content-Type: application/json" \
  -H "Cookie: nc_builder=$BUILDER_SECRET" \
  -d "{\"address\": \"$ADDRESS\"}" \
  --max-time 180)

HTTP_BODY=$(echo "$HTTP_RESPONSE" | sed '$d')
HTTP_STATUS=$(echo "$HTTP_RESPONSE" | tail -n1)

echo "HTTP Status: $HTTP_STATUS"
echo ""

# Pretty-print the full response
echo "=== Full Response JSON ==="
echo "$HTTP_BODY" | python3 -m json.tool 2>/dev/null || echo "$HTTP_BODY"
echo ""

# Extract and display the trace summary
echo "=== Trace Summary ==="
echo "$HTTP_BODY" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    trace = data.get('trace', {})
    print(f\"  trace_id:       {trace.get('trace_id', 'N/A')}\")
    print(f\"  total_elapsed:  {trace.get('total_elapsed_ms', 'N/A')} ms\")
    print(f\"  total_api_calls:{trace.get('total_api_calls', 'N/A')}\")
    print(f\"  stages_completed:{trace.get('stages_completed', 'N/A')}\")
    print(f\"  stages_skipped: {trace.get('stages_skipped', 'N/A')}\")
    print(f\"  final_outcome:  {trace.get('final_outcome', 'N/A')}\")

    stages = trace.get('stages', [])
    if stages:
        print()
        print('=== Top 5 Slowest Stages ===')
        for s in sorted(stages, key=lambda x: x.get('elapsed_ms', 0), reverse=True)[:5]:
            err = f\"  ERR: {s['error']}\" if s.get('error') else ''
            skip = ' [SKIPPED]' if s.get('skipped') else ''
            print(f\"  {s['elapsed_ms']:>6}ms  {s['stage']:<25}  api_calls={s['api_calls']}{skip}{err}\")

    calls = trace.get('api_calls', [])
    if calls:
        print()
        print('=== Top 10 Slowest API Calls ===')
        for c in sorted(calls, key=lambda x: x.get('elapsed_ms', 0), reverse=True)[:10]:
            retry = ' [RETRY]' if c.get('retried') else ''
            print(f\"  {c['elapsed_ms']:>6}ms  {c['service']:<14} {c['endpoint']:<22}  http={c['status_code']}  provider={c.get('provider_status', '')}{retry}  stage={c['stage']}\")

    print()
    print(f\"Find this trace in logs by searching for: trace={trace.get('trace_id', 'N/A')}\")
except Exception as e:
    print(f'Could not parse trace: {e}')
" 2>/dev/null || echo "(Could not parse trace data)"
