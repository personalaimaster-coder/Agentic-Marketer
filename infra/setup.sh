#!/usr/bin/env bash
# ============================================================
# Marketing Agent — one-time GCP infra setup
# Run this once from your local machine (with gcloud authed).
# Takes ~3 minutes.
# ============================================================

set -euo pipefail

# ---- Load .env ----
if [ ! -f .env ]; then
  echo "ERROR: .env not found. Copy .env.example → .env and fill in values."
  exit 1
fi
source .env

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT in .env}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-marketing-agent}"
BUCKET="${GCS_BUCKET:-${PROJECT}-post-images}"
SERVICE_ACCOUNT="${SERVICE}@${PROJECT}.iam.gserviceaccount.com"

echo ""
echo "=== Marketing Agent infra setup ==="
echo "  Project : $PROJECT"
echo "  Region  : $REGION"
echo "  Bucket  : $BUCKET"
echo ""

# ---- Point gcloud at your project ----
gcloud config set project "$PROJECT" --quiet

# ---- Enable required APIs ----
echo "→ Enabling APIs (takes ~60 s on first run)..."
gcloud services enable \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT" --quiet

# ---- Create service account (used by Cloud Run) ----
echo "→ Creating service account..."
gcloud iam service-accounts create "$SERVICE" \
  --display-name "Marketing Agent" \
  --project "$PROJECT" 2>/dev/null || echo "   (already exists — skipping)"

# Grant the service account the roles it needs.
for ROLE in \
  roles/aiplatform.user \
  roles/datastore.user \
  roles/storage.objectAdmin \
  roles/secretmanager.secretAccessor; do
  gcloud projects add-iam-policy-binding "$PROJECT" \
    --member "serviceAccount:${SERVICE_ACCOUNT}" \
    --role "$ROLE" --quiet
done

# ---- Firestore: create (native mode) database ----
echo "→ Creating Firestore database (native mode)..."
gcloud firestore databases create \
  --location="$REGION" \
  --project "$PROJECT" 2>/dev/null || echo "   (already exists — skipping)"

# Create the composite index needed for due-post queries.
# Firestore will build it in the background (usually < 5 min).
echo "→ Creating Firestore composite index for the post queue..."
gcloud firestore indexes composite create \
  --collection-group=posts \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=publish_timestamp,order=ASCENDING \
  --project "$PROJECT" 2>/dev/null || echo "   (already exists — skipping)"

# ---- Cloud Storage bucket (public read for post images) ----
echo "→ Creating GCS bucket: gs://${BUCKET}..."
gsutil mb -p "$PROJECT" -l "$REGION" "gs://${BUCKET}" 2>/dev/null || echo "   (already exists — skipping)"
gsutil iam ch allUsers:objectViewer "gs://${BUCKET}"
gsutil cors set infra/cors.json "gs://${BUCKET}"

# ---- Cloud Scheduler jobs ----
echo "→ Creating Cloud Scheduler jobs..."
# We use a placeholder URL here; deploy.sh updates it after Cloud Run deployment.
PLACEHOLDER="https://placeholder.run.app"

gcloud scheduler jobs create http "${SERVICE}-daily-pipeline" \
  --location "$REGION" \
  --schedule "0 1 * * *" \
  --uri "${PLACEHOLDER}/run/pipeline" \
  --http-method POST \
  --time-zone "UTC" \
  --attempt-deadline 600s \
  --project "$PROJECT" 2>/dev/null || echo "   (daily pipeline job already exists)"

gcloud scheduler jobs create http "${SERVICE}-hourly-publish" \
  --location "$REGION" \
  --schedule "0 * * * *" \
  --uri "${PLACEHOLDER}/run/publish" \
  --http-method POST \
  --time-zone "UTC" \
  --project "$PROJECT" 2>/dev/null || echo "   (hourly publish job already exists)"

# Phase 2 Performance Monitor: durable publish-retry poll (every 5 min).
gcloud scheduler jobs create http "${SERVICE}-retry-poll" \
  --location "$REGION" \
  --schedule "*/5 * * * *" \
  --uri "${PLACEHOLDER}/run/retry" \
  --http-method POST \
  --time-zone "UTC" \
  --project "$PROJECT" 2>/dev/null || echo "   (retry poll job already exists)"

# Phase 2 Performance Monitor: daily outcome digest.
gcloud scheduler jobs create http "${SERVICE}-daily-monitor" \
  --location "$REGION" \
  --schedule "0 17 * * *" \
  --uri "${PLACEHOLDER}/run/monitor" \
  --http-method POST \
  --time-zone "UTC" \
  --project "$PROJECT" 2>/dev/null || echo "   (daily monitor job already exists)"

echo ""
echo "✅ Infra setup complete."
echo "   Next: run  bash deploy.sh  to build + deploy the agent to Cloud Run."
echo "   Then: bash infra/register_telegram_webhook.sh"
