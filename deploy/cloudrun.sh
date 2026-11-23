#!/usr/bin/env bash
# Deploy the website to Google Cloud Run (free tier: scales to zero, 2M requests/month).
#   deploy/cloudrun.sh            build from source with Cloud Build and deploy
# Needs: gcloud signed in with a project set (gcloud config set project ID), billing on, and in .env:
#   NEON_DATABASE_URL, ANTHROPIC_API_KEY, BRAVE_SEARCH_API_KEY, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET,
#   OWNER_EMAIL, SMTP_USER, SMTP_APP_PASSWORD (optional). Secret values go straight from .env to Secret
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

SA="$(gcloud projects describe "$PROJECT" --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
put_secret() {  # name, value from stdin
  gcloud secrets describe "$1" >/dev/null 2>&1 || gcloud secrets create "$1" --replication-policy=automatic --quiet >/dev/null
  gcloud secrets versions add "$1" --data-file=- --quiet >/dev/null
  gcloud secrets add-iam-policy-binding "$1" --member="serviceAccount:$SA" --role=roles/secretmanager.secretAccessor --quiet >/dev/null
  echo "secret $1: updated"
}
[ -n "$(envval NEON_DATABASE_URL)" ] || { echo "add NEON_DATABASE_URL=... to .env first"; exit 1; }
envval NEON_DATABASE_URL | put_secret DATABASE_URL
for k in ANTHROPIC_API_KEY BRAVE_SEARCH_API_KEY GOOGLE_CLIENT_SECRET SMTP_APP_PASSWORD; do
  [ -n "$(envval $k)" ] && envval $k | put_secret $k
done
# A separate session key for prod, made once and kept in Secret Manager.
gcloud secrets describe SESSION_SECRET >/dev/null 2>&1 || /usr/bin/python3 -I -c 'import secrets; print(secrets.token_urlsafe(48), end="")' | put_secret SESSION_SECRET

URL=$(gcloud run services describe $SERVICE --region $REGION --format='value(status.url)' 2>/dev/null || true)
SECRETS="DATABASE_URL=DATABASE_URL:latest,ANTHROPIC_API_KEY=ANTHROPIC_API_KEY:latest,SESSION_SECRET=SESSION_SECRET:latest,GOOGLE_CLIENT_SECRET=GOOGLE_CLIENT_SECRET:latest"
[ -n "$(envval BRAVE_SEARCH_API_KEY)" ] && SECRETS="$SECRETS,BRAVE_SEARCH_API_KEY=BRAVE_SEARCH_API_KEY:latest"
[ -n "$(envval SMTP_APP_PASSWORD)" ] && SECRETS="$SECRETS,SMTP_APP_PASSWORD=SMTP_APP_PASSWORD:latest"
VARS="^|^APP_ENV=prod|ACCESS_MODE=link|GOOGLE_CLIENT_ID=$(envval GOOGLE_CLIENT_ID)|OWNER_EMAIL=$(envval OWNER_EMAIL)|SMTP_USER=$(envval SMTP_USER)|BASE_URL=${URL:-https://pending}"

gcloud run deploy $SERVICE --source . --region $REGION --allow-unauthenticated \
  --min-instances 0 --max-instances 2 --memory 512Mi --cpu 1 --concurrency 40 --timeout 60 \
  --set-env-vars "$VARS" --set-secrets "$SECRETS" --quiet

NEW=$(gcloud run services describe $SERVICE --region $REGION --format='value(status.url)')
if [ "$NEW" != "$URL" ]; then  # first deploy: now we know the address
  gcloud run services update $SERVICE --region $REGION --update-env-vars "BASE_URL=$NEW" --quiet >/dev/null
fi
echo
echo "Live at: $NEW   (private: only you and holders of a shared link get in)"
echo "Google sign-in: add  $NEW/auth/callback  to the OAuth client's Authorized redirect URIs."
