#!/usr/bin/env bash
# Deploy Precedent to Cloud Run. Requires gcloud auth and a billed project.
# Estimated first-run cost: well under $50 with min instances = 0.
set -euo pipefail

PROJECT="${GOOGLE_CLOUD_PROJECT:?set GOOGLE_CLOUD_PROJECT}"
REGION="${GOOGLE_CLOUD_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-precedent}"

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

# Firestore native (ignore if it already exists)
gcloud firestore databases create --location="${FIRESTORE_LOCATION:-nam5}" --type=firestore-native || true

# Optional: store Gemini key in Secret Manager
if [[ -n "${GEMINI_API_KEY:-}" ]]; then
  echo -n "$GEMINI_API_KEY" | gcloud secrets create gemini-api-key --data-file=- 2>/dev/null \
    || echo -n "$GEMINI_API_KEY" | gcloud secrets versions add gemini-api-key --data-file=-
  SECRET_FLAG="--set-secrets=GEMINI_API_KEY=gemini-api-key:latest"
else
  SECRET_FLAG=""
fi

gcloud run deploy "$SERVICE" \
  --source . \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances 0 \
  --max-instances 2 \
  --memory 512Mi \
  --cpu 1 \
  --timeout 120 \
  --set-env-vars "GOOGLE_CLOUD_PROJECT=${PROJECT},PRECEDENT_VERTEX=true,DAILY_BUDGET_USD=10,HARD_BUDGET_USD=40" \
  $SECRET_FLAG

gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'
