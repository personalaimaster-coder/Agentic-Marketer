#!/usr/bin/env bash
# Register the Telegram webhook after Cloud Run deployment.
# Run this once (or re-run if the Cloud Run URL changes).

set -euo pipefail

if [ ! -f .env ]; then echo "ERROR: .env not found."; exit 1; fi
source .env

TOKEN="${TELEGRAM_BOT_TOKEN:?set TELEGRAM_BOT_TOKEN in .env}"
PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT in .env}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-marketing-agent}"

# Fetch the deployed Cloud Run URL
SERVICE_URL=$(gcloud run services describe "$SERVICE" \
  --region "$REGION" --project "$PROJECT" \
  --format "value(status.url)" 2>/dev/null)

if [ -z "$SERVICE_URL" ]; then
  echo "ERROR: Cloud Run service '$SERVICE' not found. Deploy first."
  exit 1
fi

WEBHOOK_URL="${SERVICE_URL}/telegram"
echo "Registering Telegram webhook → $WEBHOOK_URL"

RESPONSE=$(curl -s "https://api.telegram.org/bot${TOKEN}/setWebhook?url=${WEBHOOK_URL}")
echo "$RESPONSE"

if echo "$RESPONSE" | grep -q '"ok":true'; then
  echo "✅ Webhook registered successfully."
else
  echo "⚠️  Webhook registration may have failed. Check the response above."
fi
