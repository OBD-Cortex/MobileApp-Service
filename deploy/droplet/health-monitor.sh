#!/usr/bin/env bash
# ==============================================================
# Health Monitor Script -- OBD-Cortex RAG
# ==============================================================
# Cron script (e.g., run every 5 minutes) to monitor system health
# and the OBD-Cortex services.

set -euo pipefail

# Replace this with your actual Discord/Slack webhook URL if desired
WEBHOOK_URL=""

TIMESTAMP=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
ISSUES=0
ALERT_MSG="[*] OBD-Cortex Health Alert - $TIMESTAMP\n"

# Helper function to append to alert message
log_issue() {
    local msg=$1
    echo "[!] $msg"
    ALERT_MSG="${ALERT_MSG}\n[!] $msg"
    ISSUES=$((ISSUES + 1))
}

echo "Running OBD-Cortex Health Check at $TIMESTAMP"

# 1. Check if uvicorn/obd-cortex-rag service is active
if systemctl is-active --quiet obd-cortex-rag.service; then
    echo "[✓] obd-cortex-rag.service is active"
else
    log_issue "obd-cortex-rag.service is DOWN or FAILED"
fi

# 2. Check if nginx is running and responding
if systemctl is-active --quiet nginx.service; then
    echo "[✓] nginx.service is active"
else
    log_issue "nginx.service is DOWN"
fi

if curl --output /dev/null --silent --head --fail "http://127.0.0.1"; then
    echo "[✓] Nginx is responding on loopback"
else
    log_issue "Nginx is NOT responding on loopback (127.0.0.1)"
fi

# 3. Check MongoDB connectivity via API health endpoint
# Assuming Nginx proxies this appropriately
HEALTH_JSON=$(curl -s "http://127.0.0.1/api/health" || echo '{"status": "error"}')
if echo "$HEALTH_JSON" | grep -q '"database": "connected"'; then
    echo "[✓] MongoDB Atlas connection is healthy"
else
    log_issue "MongoDB Atlas connection is DEGRADED or DOWN. API Response: $HEALTH_JSON"
fi

# 4. Check Disk Usage (Threshold: 85%)
DISK_USAGE=$(df -h / | awk 'NR==2 {print $5}' | sed 's/%//')
if [ -n "$DISK_USAGE" ] && [ "$DISK_USAGE" -gt 85 ]; then
    log_issue "Root disk usage is critical: ${DISK_USAGE}%"
else
    echo "[✓] Root disk usage is ok (${DISK_USAGE}%)"
fi

# 5. Check Memory Usage (Threshold: 90%)
MEM_USAGE=$(free | grep Mem | awk '{print int($3/$2 * 100.0)}')
if [ -n "$MEM_USAGE" ] && [ "$MEM_USAGE" -gt 90 ]; then
    log_issue "Memory usage is critical: ${MEM_USAGE}%"
else
    echo "[✓] Memory usage is ok (${MEM_USAGE}%)"
fi

# Dispatch Webhook Alert if issues were found
if [ $ISSUES -gt 0 ]; then
    echo "======================================"
    echo "Alert triggered. Issues found: $ISSUES"
    
    if [ -n "$WEBHOOK_URL" ]; then
        # Format for generic Discord-compatible webhook
        JSON_PAYLOAD=$(cat <<EOF
{
  "content": "$ALERT_MSG"
}
EOF
)
        curl -H "Content-Type: application/json" -X POST -d "$JSON_PAYLOAD" "$WEBHOOK_URL"
        echo "[*] Webhook notification sent."
    fi
else
    echo "======================================"
    echo "Health check passed. No issues found."
fi
