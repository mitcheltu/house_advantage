# Deploy: GCS Media + Cloud Scheduler (Google Cloud)

This document covers step 1 (GCS storage for media) and step 2 (Scheduler to run the pipeline).

## 1) Create GCS bucket

Bucket:
- name: `house-advantage`
- location: `US` (multi‑region)
- storage class: Standard
- public access: Not public
- protection: Soft Delete

CLI (optional):
```
gcloud storage buckets create gs://house-advantage --location=US --default-storage-class=STANDARD
```

## 2) Service account for Cloud Run + Scheduler

Create a service account for the backend:
```
gcloud iam service-accounts create house-advantage-runner
```

Grant permissions:
```
# read/write GCS

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:house-advantage-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"

# invoke Cloud Run

gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
  --member="serviceAccount:house-advantage-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"
```

## 3) Deploy backend (Cloud Run)

Build + deploy (example):
```
gcloud run deploy house-advantage-api \
  --source . \
  --region us-central1 \
  --allow-unauthenticated=false \
  --service-account house-advantage-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com
```

Set env vars in Cloud Run:
- `GCS_BUCKET=house-advantage`
- `GCS_PUBLIC=false`
- `GCS_SIGNED_URL_TTL_SECONDS=3600`
- Veo + TTS keys/paths as needed

## 4) Create Cloud Scheduler job

Create Scheduler job to call:
```
POST https://YOUR_CLOUD_RUN_URL/api/v1/jobs/run-daily-evidence
```

Example:
```
gcloud scheduler jobs create http house-advantage-daily \
  --schedule="0 10 * * *" \
  --uri="https://YOUR_CLOUD_RUN_URL/api/v1/jobs/run-daily-evidence" \
  --http-method=POST \
  --oidc-service-account-email=house-advantage-runner@YOUR_PROJECT_ID.iam.gserviceaccount.com \
  --message-body='{"report_date": "$(date -u +%F)", "contextualize_limit": 100, "severe_media_limit": 20}'
```

Note: Cloud Scheduler uses OIDC to authenticate to Cloud Run.

## 5) Verify

- Run once manually:
  - Call the endpoint directly
- Check `daily_reports` for gs:// URLs
- `GET /api/v1/daily-report/latest` should return signed HTTPS URLs
