"""从 stdin 读取 pjt --json 输出，格式化任务/对象列表（dogfooding 辅助）。"""

import json
import sys

payload = json.load(sys.stdin)
data = payload.get("result", payload)
rows = data if isinstance(data, list) else [data]
for row in rows:
    if "title" in row and "status" in row:
        print(
            f"{row['id'][:16]:<16} status={row['status']:<7} "
            f"blocked={str(row.get('computed_blocked', '-')):<5} {row['title'][:40]}"
        )
    elif "summary" in row:
        print(f"{row['id'][:16]:<16} {row.get('summary', '')[:60]}")
    else:
        print(f"{row.get('id', '?')[:16]:<16} {row.get('event_type', '')} {row.get('payload', {})}")
