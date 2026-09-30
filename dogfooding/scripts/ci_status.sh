#!/usr/bin/env bash
# 查看 ProjectTool 最近一次 CI 结果（公开仓库，匿名 API，无需 gh / token）。
#   用法: ./dogfooding/scripts/ci_status.sh [次数]
set -euo pipefail
REPO_SLUG="snsnnd/ProjectTool"
N="${1:-3}"

curl -sf "https://api.github.com/repos/${REPO_SLUG}/actions/runs?per_page=${N}" \
  | python3 -c "
import json, sys
runs = json.load(sys.stdin).get('workflow_runs', [])
if not runs:
    print('no workflow runs found'); raise SystemExit
for r in runs:
    mark = {'success': 'PASS', 'failure': 'FAIL', 'cancelled': 'CANC'}.get(r['conclusion'], '?')
    print(f\"{mark}  {r['head_sha'][:8]}  {r['status']:<10} {str(r['conclusion']):<8} {r['created_at']}\")
    print(f\"      {r['html_url']}\")
"
