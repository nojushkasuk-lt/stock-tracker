#!/usr/bin/env bash
# Deploy the website to Google Cloud Run (free tier: scales to zero, 2M requests/month).
#   deploy/cloudrun.sh            build from source with Cloud Build and deploy
# Needs: gcloud signed in with a project set (gcloud config set project ID), billing on, and in .env:
#   NEON_DATABASE_URL, ANTHROPIC_API_KEY, BRAVE_SEARCH_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
#   OWNER_EMAIL, SMTP_USER, SMTP_APP_PASSWORD and TIINGO_API_KEY (optional). Secret values go straight from .env to Secret
#   Manager through stdin: they are never printed or put on the command line.
set -euo pipefail
cd "$(dirname "$0")/.."

SERVICE=stock-tracker
REGION=${REGION:-europe-west1}
PROJECT=$(gcloud config get-value project 2>/dev/null)
[ -n "$PROJECT" ] || { echo "run: gcloud config set project YOUR_PROJECT_ID"; exit 1; }

envval() { /usr/bin/python3 -I -c 'import sys
for l in open(".env"):
    k, s, v = l.strip().partition("=")
    if s and k.strip() == sys.argv[1]: print(v.strip().strip("\"'"'"'"), end="")' "$1"; }

gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com --quiet

NUMBER=$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')
SA="$NUMBER-compute@developer.gserviceaccount.com"
# Newer projects build with the default compute account, which needs the Cloud Run builder role.
gcloud projects add-iam-policy-binding "$PROJECT" --member="serviceAccount:$SA" --role=roles/run.builder --condition=None --quiet >/dev/null
put_secret() {  # name, value from stdin. Adds a version only when the value changed, and destroys the old one
  # (Secret Manager is free up to 6 active versions).
  local new; new=$(cat)
  if ! gcloud secrets describe "$1" >/dev/null 2>&1; then
    gcloud secrets create "$1" --replication-policy=automatic --quiet >/dev/null
    gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor --quiet >/dev/null
  elif [ "$(gcloud secrets versions access latest --secret "$1" 2>/dev/null)" = "$new" ]; then
    echo "secret $1: unchanged"; return
  fi
  local old; old=$(gcloud secrets versions list "$1" --filter=state=enabled --format='value(name)' 2>/dev/null)
  printf '%s' "$new" | gcloud secrets versions add "$1" --data-file=- --quiet >/dev/null
  for v in $old; do gcloud secrets versions destroy "$v" --secret "$1" --quiet >/dev/null 2>&1; done
  echo "secret $1: updated"
}
[ -n "$(envval NEON_DATABASE_URL)" ] || { echo "add NEON_DATABASE_URL=... to .env first"; exit 1; }
[ -n "$(envval EDGAR_USER_AGENT_EMAIL)" ] || { echo "add EDGAR_USER_AGENT_NAME and EDGAR_USER_AGENT_EMAIL to .env (the SEC requires them)"; exit 1; }
envval NEON_DATABASE_URL | put_secret DATABASE_URL
for k in ANTHROPIC_API_KEY BRAVE_SEARCH_API_KEY GOOGLE_CLIENT_SECRET SMTP_APP_PASSWORD TIINGO_API_KEY; do
  [ -n "$(envval $k)" ] && envval $k | put_secret $k
done
# A separate session key for prod, made once and kept in Secret Manager.
gcloud secrets describe SESSION_SECRET >/dev/null 2>&1 || /usr/bin/python3 -I -c 'import secrets; print(secrets.token_urlsafe(48), end="")' | put_secret SESSION_SECRET

# Cloud Run's stable address: https://SERVICE-PROJECTNUMBER.REGION.run.app (the one the console shows).
URL="https://$SERVICE-$NUMBER.$REGION.run.app"
SECRETS="DATABASE_URL=DATABASE_URL:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,SESSION_SECRET=SESSION_SECRET:latest,GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest"
[ -n "$(envval BRAVE_SEARCH_API_KEY)" ] && SECRETS="$SECRETS,BRAVE_SEARCH_API_KEY=BRAVE_SEARCH_API_KEY:latest"
[ -n "$(envval TIINGO_API_KEY)" ] && SECRETS="$SECRETS,TIINGO_API_KEY=TIINGO_API_KEY:latest"
[ -n "$(envval SMTP_APP_PASSWORD)" ] && SECRETS="$SECRETS,SMTP_APP_PASSWORD=SMTP_APP_PASSWORD:latest"
VARS="^|^APP_ENV=prod|ACCESS_MODE=open|PRICE_DATA_DISPLAY=owner|GOOGLE_CLIENT_ID=$(envval GOOGLE_CLIENT_ID)|OWNER_EMAIL=$(envval OWNER_EMAIL)|SMTP_USER=$(envval SMTP_USER)|EMAIL_PROVIDER=$(envval EMAIL_PROVIDER)|EDGAR_USER_AGENT_NAME=$(envval EDGAR_USER_AGENT_NAME)|EDGAR_USER_AGENT_EMAIL=$(envval EDGAR_USER_AGENT_EMAIL)|BASE_URL=$URL"

gcloud run deploy $SERVICE --source . --region $REGION --allow-unauthenticated \
  --min-instances 0 --max-instances 2 --memory 512Mi --cpu 1 --concurrency 40 --timeout 60 \
  --set-env-vars "$VARS" --set-secrets "$SECRETS" --quiet

# Keep only the two newest builds (Artifact Registry is free up to 0.5 GB).
gcloud artifacts repositories set-cleanup-policies cloud-run-source-deploy --location "$REGION" \
  --policy deploy/cleanup-policy.json --no-dry-run --quiet >/dev/null 2>&1 || true

echo
echo "Live at: $URL   (public demo and Google sign-in)"
echo "Google sign-in: add  $URL/auth/callback  to the OAuth client's Authorized redirect URIs."
