#!/usr/bin/env bash
# ============================================================
# Marketing Agent — FULL SETUP IN ONE COMMAND
#
#   bash go.sh
#
# Handles everything including creating a brand-new GCP project.
#
# The ONLY two things that require a browser first:
#   gcloud auth login
#   gcloud auth application-default login
# ============================================================

set -euo pipefail
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; BOLD='\033[1m'; NC='\033[0m'

log()   { echo -e "${BLUE}→${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}⚠${NC}  $*"; }
die()   { echo -e "${RED}✗  ERROR:${NC} $*"; exit 1; }
header(){ echo -e "\n${BOLD}── $* ──${NC}"; }

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   Marketing Agent — Full Setup                   ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ═══════════════════════════════════════════════════════════
# 0. PREREQUISITES
# ═══════════════════════════════════════════════════════════
header "Prerequisites"

command -v gcloud >/dev/null 2>&1 || die "gcloud CLI not found.
  Install it:  brew install google-cloud-sdk   (macOS)
  Or download: https://cloud.google.com/sdk/docs/install
  Then run:
    gcloud auth login
    gcloud auth application-default login
  Then re-run: bash go.sh"

GCLOUD_ACCOUNT=$(gcloud auth list --filter=status:ACTIVE \
  --format="value(account)" 2>/dev/null | head -1)
[ -n "$GCLOUD_ACCOUNT" ] || die "Not authenticated with gcloud.
  Run these two commands (each opens a browser), then re-run:
    gcloud auth login
    gcloud auth application-default login"
ok "Logged in as: $GCLOUD_ACCOUNT"

ADC_FILE="$HOME/.config/gcloud/application_default_credentials.json"
[ -f "$ADC_FILE" ] || die "Application Default Credentials missing.
  Run this command (opens a browser), then re-run:
    gcloud auth application-default login"
ok "Application Default Credentials: present"

PYTHON=$(command -v python3.13 2>/dev/null \
      || command -v python3.12 2>/dev/null \
      || command -v python3.11 2>/dev/null \
      || echo "")
[ -n "$PYTHON" ] || die "Python 3.11+ required.
  Install: brew install python@3.13"
ok "Python: $($PYTHON --version)"

# ═══════════════════════════════════════════════════════════
# 1. GCP PROJECT  (create if it doesn't exist)
# ═══════════════════════════════════════════════════════════
header "GCP Project"

# Resolve the project ID from env / .env, otherwise prompt for it.
PROJECT_ID="${GOOGLE_CLOUD_PROJECT:-}"
if [ -z "$PROJECT_ID" ] && [ -f .env ]; then
  PROJECT_ID=$(grep -E "^GOOGLE_CLOUD_PROJECT=" .env | cut -d= -f2- | tr -d ' ')
fi
if [ -z "$PROJECT_ID" ]; then
  read -rp "  Enter the GCP project ID to use (created if it doesn't exist): " PROJECT_ID
fi
[ -n "$PROJECT_ID" ] || die "A GCP project ID is required."
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-marketing-agent}"

# Check if the project already exists
if gcloud projects describe "$PROJECT_ID" --quiet >/dev/null 2>&1; then
  ok "Project already exists: $PROJECT_ID"
else
  log "Project '$PROJECT_ID' not found — creating it..."
  gcloud projects create "$PROJECT_ID" \
    --name "Marketing Agent" \
    --quiet
  ok "Project created: $PROJECT_ID"
fi

gcloud config set project "$PROJECT_ID" --quiet
ok "Active project: $PROJECT_ID"

# Reset the ADC quota project to this new project
# (application-default login may have picked a different existing project)
gcloud auth application-default set-quota-project "$PROJECT_ID" --quiet 2>/dev/null \
  || true   # non-fatal: ADC still works, billing just falls back
ok "ADC quota project → $PROJECT_ID"

# ─── Link billing account ────────────────────────────────
log "Checking billing..."
CURRENT_BILLING=$(gcloud billing projects describe "$PROJECT_ID" \
  --format="value(billingEnabled)" 2>/dev/null || echo "False")

if [ "$CURRENT_BILLING" = "True" ]; then
  ok "Billing already enabled on this project"
else
  # List available billing accounts
  BILLING_ACCOUNTS=$(gcloud billing accounts list \
    --filter="open=true" \
    --format="value(name,displayName)" 2>/dev/null)

  if [ -z "$BILLING_ACCOUNTS" ]; then
    die "No open billing accounts found on this Google account.
  You need to set up billing at: https://console.cloud.google.com/billing
  Then re-run: bash go.sh"
  fi

  # Count accounts
  ACCOUNT_COUNT=$(echo "$BILLING_ACCOUNTS" | wc -l | tr -d ' ')

  if [ "$ACCOUNT_COUNT" -eq 1 ]; then
    BILLING_ID=$(echo "$BILLING_ACCOUNTS" | awk '{print $1}')
    BILLING_NAME=$(echo "$BILLING_ACCOUNTS" | awk '{$1=""; print $0}' | xargs)
  else
    # Multiple accounts — show them and ask
    echo ""
    echo "  Multiple billing accounts found:"
    echo "$BILLING_ACCOUNTS" | nl -w2 -s". "
    echo ""
    read -rp "  Enter the number of the account to use: " ACCT_NUM
    BILLING_ID=$(echo "$BILLING_ACCOUNTS" | sed -n "${ACCT_NUM}p" | awk '{print $1}')
    BILLING_NAME=$(echo "$BILLING_ACCOUNTS" | sed -n "${ACCT_NUM}p" | awk '{$1=""; print $0}' | xargs)
  fi

  log "Linking billing account: $BILLING_NAME"
  gcloud billing projects link "$PROJECT_ID" \
    --billing-account "$BILLING_ID" \
    --quiet
  ok "Billing enabled: $BILLING_NAME"
fi

# ═══════════════════════════════════════════════════════════
# 2. WRITE .env
# ═══════════════════════════════════════════════════════════
header ".env file"

[ -f .env ] || cp .env.example .env && ok "Created .env from .env.example"

# Patch project + region
sed -i '' "s|^GOOGLE_CLOUD_PROJECT=.*|GOOGLE_CLOUD_PROJECT=${PROJECT_ID}|" .env
sed -i '' "s|^GOOGLE_CLOUD_LOCATION=.*|GOOGLE_CLOUD_LOCATION=${REGION}|" .env

# GCS bucket name
BUCKET="${PROJECT_ID}-post-images"
sed -i '' "s|^GCS_BUCKET=.*|GCS_BUCKET=${BUCKET}|" .env

# Auto-generate SCHEDULER_SECRET if blank
CURRENT_SECRET=$(grep "^SCHEDULER_SECRET=" .env | cut -d= -f2 | tr -d ' ')
if [ -z "$CURRENT_SECRET" ]; then
  SECRET=$($PYTHON -c "import secrets; print(secrets.token_hex(32))")
  sed -i '' "s|^SCHEDULER_SECRET=.*|SCHEDULER_SECRET=${SECRET}|" .env
  ok "SCHEDULER_SECRET generated"
else
  SECRET="$CURRENT_SECRET"
  ok "SCHEDULER_SECRET already set"
fi

# Load everything into this shell session
set -a; source .env; set +a
ok ".env ready"

# ═══════════════════════════════════════════════════════════
# 3. ENABLE APIs
# ═══════════════════════════════════════════════════════════
header "Enabling Google Cloud APIs"
log "This takes ~60 s on first run..."
gcloud services enable \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  storage.googleapis.com \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  --project "$PROJECT_ID" --quiet
ok "All APIs enabled"

# ═══════════════════════════════════════════════════════════
# 4. SERVICE ACCOUNT + IAM
# ═══════════════════════════════════════════════════════════
header "Service Account & IAM"

SERVICE="$SERVICE_NAME"
SA="${SERVICE}@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create "$SERVICE" \
  --display-name "Marketing Agent" \
  --project "$PROJECT_ID" 2>/dev/null \
  || ok "Service account already exists"

for ROLE in \
  roles/aiplatform.user \
  roles/datastore.user \
  roles/storage.objectAdmin \
  roles/secretmanager.secretAccessor \
  roles/run.invoker; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${SA}" \
    --role "$ROLE" \
    --quiet --no-user-output-enabled 2>/dev/null || true
done
ok "IAM roles granted to $SA"

# ═══════════════════════════════════════════════════════════
# 5. FIRESTORE
# ═══════════════════════════════════════════════════════════
header "Firestore"

gcloud firestore databases create \
  --location="${REGION}" \
  --project "$PROJECT_ID" 2>/dev/null \
  || ok "Firestore database already exists"

# Composite index for the hourly "due posts" query
gcloud firestore indexes composite create \
  --collection-group=posts \
  --field-config field-path=status,order=ASCENDING \
  --field-config field-path=publish_timestamp,order=ASCENDING \
  --project "$PROJECT_ID" 2>/dev/null \
  || ok "Composite index already exists (or pending build)"
ok "Firestore ready"

# ═══════════════════════════════════════════════════════════
# 6. CLOUD STORAGE BUCKET
# ═══════════════════════════════════════════════════════════
header "Cloud Storage"

gsutil mb -p "$PROJECT_ID" -l "$REGION" "gs://${BUCKET}" 2>/dev/null \
  || ok "Bucket already exists"
gsutil iam ch allUsers:objectViewer "gs://${BUCKET}"
gsutil cors set infra/cors.json "gs://${BUCKET}"
ok "Bucket ready: gs://${BUCKET} (public read)"

# ═══════════════════════════════════════════════════════════
# 7. PYTHON ENVIRONMENT
# ═══════════════════════════════════════════════════════════
header "Python Environment"

[ -d .venv ] || "$PYTHON" -m venv .venv
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet
ok "Dependencies installed ($($PYTHON --version))"

# ═══════════════════════════════════════════════════════════
# 8. BUILD + DEPLOY TO CLOUD RUN  (source deploy — one command)
# ═══════════════════════════════════════════════════════════
header "Cloud Run Deployment"

# Build a comma-separated KEY=VALUE string from .env
# (skip blank lines, comments, and values that contain commas which would break the flag)
ENV_VARS=$(grep -v '^#' .env | grep -v '^$' | grep '=' | \
  while IFS='=' read -r key rest; do
    printf '%s=%s,' "$key" "$rest"
  done | sed 's/,$//')

log "Building and deploying (this takes ~3-5 min on first run)..."

# --source . uses Cloud Build internally but handles log streaming correctly
# and combines build + deploy into a single idempotent command.
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
  --project "$PROJECT_ID" \
  --quiet

SERVICE_URL=$(gcloud run services describe "$SERVICE" \
  --region "$REGION" \
  --project "$PROJECT_ID" \
  --format "value(status.url)")
ok "Deployed: $SERVICE_URL"

# ═══════════════════════════════════════════════════════════
# 9. CLOUD SCHEDULER
# ═══════════════════════════════════════════════════════════
header "Cloud Scheduler"

_upsert_job() {
  local NAME=$1 CRON=$2 ENDPOINT=$3
  local URI="${SERVICE_URL}${ENDPOINT}"
  if gcloud scheduler jobs create http "$NAME" \
    --location "$REGION" \
    --schedule "$CRON" \
    --uri "$URI" \
    --http-method POST \
    --headers "X-Scheduler-Token=${SECRET}" \
    --time-zone "${LOCAL_TZ:-UTC}" \
    --attempt-deadline 600s \
    --project "$PROJECT_ID" --quiet 2>/dev/null; then
    ok "Created: $NAME"
  else
    gcloud scheduler jobs update http "$NAME" \
      --location "$REGION" \
      --uri "$URI" \
      --update-headers "X-Scheduler-Token=${SECRET}" \
      --project "$PROJECT_ID" --quiet
    ok "Updated: $NAME"
  fi
}

_upsert_job "${SERVICE}-daily-pipeline" "0 7 * * *"   "/run/pipeline"
_upsert_job "${SERVICE}-hourly-publish" "0 * * * *"   "/run/publish"
# Phase 2 Performance Monitor: durable publish-retry poll + daily outcome digest.
_upsert_job "${SERVICE}-retry-poll"     "*/5 * * * *" "/run/retry"
_upsert_job "${SERVICE}-daily-monitor"  "30 22 * * *" "/run/monitor"

# ═══════════════════════════════════════════════════════════
# 10. TELEGRAM WEBHOOK
# ═══════════════════════════════════════════════════════════
header "Telegram Webhook"

WEBHOOK_URL="${SERVICE_URL}/telegram"
RESPONSE=$(curl -s \
  "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/setWebhook?url=${WEBHOOK_URL}")

if echo "$RESPONSE" | grep -q '"ok":true'; then
  ok "Webhook registered → $WEBHOOK_URL"
else
  warn "Unexpected response from Telegram: $RESPONSE"
fi

# ═══════════════════════════════════════════════════════════
# DONE
# ═══════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║   ✅  Everything is set up and running                      ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo "  GCP Project : $PROJECT_ID"
echo "  Service URL : $SERVICE_URL"
echo ""
echo "  ── Test it right now ──────────────────────────────────────"
echo "  Trigger the pipeline manually:"
echo "    curl -s -X POST ${SERVICE_URL}/run/pipeline \\"
echo "         -H 'X-Scheduler-Token: ${SECRET}'"
echo ""
echo "  Within ~2 min you'll get Telegram approval cards."
echo ""
echo "  ── Watch live logs ────────────────────────────────────────"
echo "    gcloud run logs tail ${SERVICE} --region ${REGION}"
echo ""
echo "  ── Automatic schedule ─────────────────────────────────────"
echo "  Daily 7 AM (${LOCAL_TZ:-UTC}) → generates posts → Telegram cards"
echo "  Every hour              → publishes approved posts to social media"
echo ""
