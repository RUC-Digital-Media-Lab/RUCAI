# Incident Log

Use one file per incident:
- `YYYY-MM-DD-short-title.md`

Required sections:
1. Summary
2. Impact
3. Detection
4. Root Cause
5. Mitigation
6. Corrective Actions
7. Verification

Keep entries short and factual. Link PR/commit/script changes where relevant.

## Emergency Stop for systemd Death Loops
- Stop restart storm: `sudo systemctl stop rucai-api`
- Clear failed state/counter: `sudo systemctl reset-failed rucai-api`
- Inspect rendered unit: `sudo systemctl cat rucai-api`
- Inspect recent logs: `sudo journalctl -u rucai-api -n 100 --no-pager`
- Verify configured runtime user, group, app dir, `.env`, and `.venv/bin/uvicorn` before restarting.
