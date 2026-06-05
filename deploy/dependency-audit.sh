#!/usr/bin/env bash
# ==============================================================
# OBD-Cortex Dependency Security Audit Script
# ==============================================================
# Scans all three subprojects for known CVEs in dependencies.
# Requires: pip-audit (Python), npm (Node.js)
#
# Usage:
#   chmod +x deploy/dependency-audit.sh
#   ./deploy/dependency-audit.sh
# ==============================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

# Terminal glyph indicators
PASS="[*]"
FAIL="[!]"
INFO="[>]"
DIVIDER="=============================================================="

echo "$DIVIDER"
echo " OBD-Cortex Dependency Security Audit"
echo " $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
echo "$DIVIDER"
echo ""

EXIT_CODE=0

# ----------------------------------------------------------
# 1. PYTHON AUDIT -- Hybrid-Automotive-RAG
# ----------------------------------------------------------
echo "$INFO Auditing: Hybrid-Automotive-RAG (Python)"
echo "$DIVIDER"

RAG_DIR="$PROJECT_ROOT/Hybrid-Automotive-RAG"
RAG_REQ="$RAG_DIR/requirements.txt"

if [ -f "$RAG_REQ" ]; then
    if command -v pip-audit &> /dev/null; then
        if pip-audit -r "$RAG_REQ" --desc 2>&1; then
            echo "$PASS RAG Python dependencies: No known vulnerabilities."
        else
            echo "$FAIL RAG Python dependencies: Vulnerabilities found (see above)."
            EXIT_CODE=1
        fi
    else
        echo "$FAIL pip-audit is not installed. Install with: pip install pip-audit"
        EXIT_CODE=1
    fi
else
    echo "$FAIL requirements.txt not found at $RAG_REQ"
fi

echo ""

# ----------------------------------------------------------
# 2. PYTHON AUDIT -- Embedded-Automotive-Edge
# ----------------------------------------------------------
echo "$INFO Auditing: Embedded-Automotive-Edge (Python)"
echo "$DIVIDER"

EDGE_DIR="$PROJECT_ROOT/Embedded-Automotive-Edge"
EDGE_REQ="$EDGE_DIR/requirements.txt"

if [ -f "$EDGE_REQ" ]; then
    if command -v pip-audit &> /dev/null; then
        if pip-audit -r "$EDGE_REQ" --desc 2>&1; then
            echo "$PASS Edge Python dependencies: No known vulnerabilities."
        else
            echo "$FAIL Edge Python dependencies: Vulnerabilities found (see above)."
            EXIT_CODE=1
        fi
    else
        echo "$FAIL pip-audit is not installed."
    fi
else
    echo "$FAIL requirements.txt not found at $EDGE_REQ"
fi

echo ""

# ----------------------------------------------------------
# 3. NODE.JS AUDIT -- Device-Identity-Mapper
# ----------------------------------------------------------
echo "$INFO Auditing: Device-Identity-Mapper (Node.js)"
echo "$DIVIDER"

MAPPER_DIR="$PROJECT_ROOT/Device-Identity-Mapper"

if [ -d "$MAPPER_DIR/node_modules" ] || [ -f "$MAPPER_DIR/package-lock.json" ]; then
    if command -v npm &> /dev/null; then
        cd "$MAPPER_DIR"
        if npm audit --production 2>&1; then
            echo "$PASS Mapper Node.js dependencies: No known vulnerabilities."
        else
            echo "$FAIL Mapper Node.js dependencies: Vulnerabilities found (see above)."
            EXIT_CODE=1
        fi
        cd "$PROJECT_ROOT"
    else
        echo "$FAIL npm is not installed."
        EXIT_CODE=1
    fi
else
    echo "$FAIL node_modules or package-lock.json not found at $MAPPER_DIR"
    echo "     Run 'npm install' in the Device-Identity-Mapper directory first."
fi

echo ""
echo "$DIVIDER"
if [ $EXIT_CODE -eq 0 ]; then
    echo "$PASS All dependency audits passed."
else
    echo "$FAIL One or more audits found issues. Review output above."
fi
echo "$DIVIDER"

exit $EXIT_CODE
