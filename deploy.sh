#!/usr/bin/env bash
# ============================================================
# Re-deploy to Cloud Run after code changes.
# Run this any time you update the agent code.
# ============================================================

set -euo pipefail

if [ ! -f .env ]; then echo "ERROR: .env not found. Run bash go.sh first."; exit 1; fi
source .env

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT in .env}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-marketing-agent}"
SA="${SERVICE}@${PROJECT}.iam.gserviceaccount.com"

echo "=== Re-deploying $SERVICE ==="
echo "  Project: $PROJECT  |  Region: $REGION"
echo ""

# Build env-vars string from .env
ENV_VARS=$(grep -v '^#' .env | grep -v '^$' | grep '=' | \
  while IFS='=' read -r key rest; do
    printf '%s=%s,' "$key" "$rest"
  done | sed 's/,$//')

echo "→ Building and deploying (--source .)..."
gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --platform managed \
  --service-account "$SA" \
  --allow-unauthenticated \
  --set-env-vars "$ENV_VARS" \
  --memory 1Gi \
  --cpu 1 \
  --timeout 600 \
  --max-instances 3 \
  --project "$PROJECT" \
  --quiet

SERVICE_URL=$(gcloud run services describe "$SERVICE" \
  --region "$REGION" --project "$PROJECT" \
  --format "value(status.url)")

echo "✅ Deployed: $SERVICE_URL"

echo ""
echo "→ Updating Cloud Scheduler URLs..."
for JOB_PATH in "${SERVICE}-daily-pipeline:/run/pipeline" "${SERVICE}-hourly-publish:/run/publish" "${SERVICE}-retry-poll:/run/retry" "${SERVICE}-daily-monitor:/run/monitor"; do
  JOB="${JOB_PATH%%:*}"
  PATH_PART="${JOB_PATH##*:}"
  gcloud scheduler jobs update http "$JOB" \
    --location "$REGION" \
    --uri "${SERVICE_URL}${PATH_PART}" \
    --update-headers "X-Scheduler-Token=${SCHEDULER_SECRET}" \
    --project "$PROJECT" --quiet 2>/dev/null \
    && echo "✓ Updated: $JOB" || echo "⚠ Skipped: $JOB (run go.sh first to create)"
done

echo ""
echo "→ Re-registering Telegram webhook..."
bash infra/register_telegram_webhook.sh

echo ""
echo "=== Done. ==="
echo "  Service : $SERVICE_URL"
echo "  Trigger : curl -s -X POST ${SERVICE_URL}/run/pipeline \\"
echo "                 -H 'X-Scheduler-Token: ${SCHEDULER_SECRET}'"
