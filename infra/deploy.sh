#!/usr/bin/env bash
# Deploy Ikigai to Cloud Run. Requires gcloud auth and a billed project.
# Build globally, then deploy the image. Avoids gcloud WaitException when
# regional Cloud Build sits in QUEUED (gcloud run deploy --source).
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-ikigai}"
REPO="${ARTIFACT_REPO:-cloud-run-source-deploy}"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:$(date -u +%Y%m%d%H%M%S)"

gcloud config set project "$PROJECT"
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  secretmanager.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  logging.googleapis.com

# Firestore already exists on this project; do not recreate.

# Optional: store Gemini key in Secret Manager
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  echo -n "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=- 2>/dev/null \
    || echo -n "$GEMINI_API_KEY" | gcloud secrets versions add gemini-api-key --data-file=-
  SECRET_FLAG="--set-secrets=GEMINI_API_KEY=gemini-api-key:latest"
else
  SECRET_FLAG=""
fi

ENV_VARS="GOOGLE_CLOUD_PROJECT=${PROJECT},IKIGAI_VERTEX=true,DAILY_BUDGET_USD=10,HARD_BUDGET_USD=40"
if [[ -n "${IKIGAI_API_TOKEN:-}" ]]; then
  ENV_VARS="${ENV_VARS},IKIGAI_API_TOKEN=${IKIGAI_API_TOKEN}"
fi

gcloud artifacts repositories describe "$REPO" --location="$REGION" >/dev/null 2>&1 \
  || gcloud artifacts repositories create "$REPO" \
    --repository-format=docker \
    --location="$REGION" \
    --description="Ikigai Cloud Run images"

# Stuck QUEUED regional builds block the next --source deploy; cancel them.
while read -r bid; do
  [[ -z "${bid}" ]] && continue
  echo "Cancelling stuck regional build ${bid}"
  gcloud builds cancel "$bid" --region="$REGION" --quiet || true
done < <(gcloud builds list --region="$REGION" \
  --filter="status=QUEUED OR status=WORKING" \
  --limit=20 \
  --format='value(id)' 2>/dev/null || true)

echo "Building ${IMAGE}"
gcloud builds submit . \
  --project "$PROJECT" \
  --tag "$IMAGE" \
  --timeout=1200s

# Slack slash commands fail with "internal error" if the container is cold
# (3s timeout) or if CPU freezes after the ACK. Keep one warm instance and
# leave CPU on so /ikigai login can finish the briefing after the ACK.
gcloud run deploy "$SERVICE" \
  --image "$IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 1 \
  --max-instances 2 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 120 \
  --cpu-boost \
  --no-cpu-throttling \
  --update-env-vars "$ENV_VARS" \
  $SECRET_FLAG

gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'
