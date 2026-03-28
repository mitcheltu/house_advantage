# House Advantage — Google Cloud Platform Infrastructure Plan

**Date:** March 2026  
**Status:** Planning  
**Scope:** Migrate from Docker Compose (local) → fully managed GCP services

---

## Table of Contents

1. [Current State vs. Target State](#1-current-state-vs-target-state)
2. [GCP Services Overview](#2-gcp-services-overview)
3. [Cloud SQL (Database)](#3-cloud-sql-database)
4. [Cloud Storage (Media & Static Files)](#4-cloud-storage-media--static-files)
5. [Cloud Run (Backend API + Frontend)](#5-cloud-run-backend-api--frontend)
6. [Cloud Run Jobs (Nightly Pipeline)](#6-cloud-run-jobs-nightly-pipeline)
7. [Cloud Scheduler (Automation)](#7-cloud-scheduler-automation)
8. [Artifact Registry (Container Images)](#8-artifact-registry-container-images)
9. [Secret Manager (API Keys & Credentials)](#9-secret-manager-api-keys--credentials)
10. [Cloud CDN + Load Balancer (Media Serving)](#10-cloud-cdn--load-balancer-media-serving)
11. [Cloud Build (CI/CD)](#11-cloud-build-cicd)
12. [Cloud Logging & Monitoring](#12-cloud-logging--monitoring)
13. [Networking & Domain](#13-networking--domain)
14. [Environment Variable Migration](#14-environment-variable-migration)
15. [Code Changes Required](#15-code-changes-required)
16. [Cost Estimate](#16-cost-estimate)
17. [Implementation Phases](#17-implementation-phases)

---

## 1. Current State vs. Target State

### Current (Docker Compose, Local)

```
Docker Compose Stack (local machine)
├── mysql:8.0          → port 3306 (Docker volume: mysql_data)
├── backend (FastAPI)  → port 8000 (uvicorn)
├── scheduler          → APScheduler (runs nightly jobs: 02:00–06:00 UTC)
├── frontend (Next.js) → port 3000
├── nginx              → port 80 (reverse proxy)
└── Volumes
    ├── mysql_data     → /var/lib/mysql
    └── media_data     → /media (video, audio, thumbnails)
```

**Problems:**
- Single machine, no redundancy
- No autoscaling
- Media files served from local disk (no CDN)
- No CI/CD — manual `docker compose up`
- No secret management — env vars in shell / `.env` file
- APScheduler tied to a running container — if container dies, jobs don't run
- MySQL data on Docker volume — no automated backups

### Target (GCP Managed)

```
Google Cloud Platform
├── Cloud SQL (MySQL 8.0)          → Managed database with auto-backups
├── Cloud Run: backend             → FastAPI (autoscaling 0→N)
├── Cloud Run: frontend            → Next.js (autoscaling 0→N)
├── Cloud Run Jobs: pipeline       → Nightly ingest/scoring/media pipeline
├── Cloud Scheduler                → Triggers pipeline jobs on cron
├── Cloud Storage (GCS)            → Media files (videos, audio, citation images)
├── Cloud CDN                      → Fast media delivery globally
├── Artifact Registry              → Docker images for all services
├── Secret Manager                 → All API keys and credentials
├── Cloud Build                    → CI/CD from GitHub
└── Cloud Logging / Monitoring     → Centralized observability
```

---

## 2. GCP Services Overview

| GCP Service | Replaces | Purpose | Pricing Model |
|---|---|---|---|
| **Cloud SQL for MySQL** | Docker MySQL 8.0 | Managed relational database | Per-instance + storage |
| **Cloud Storage (GCS)** | Docker media_data volume | Media file storage (MP4, MP3, PNG) | Per-GB stored + egress |
| **Cloud Run (services)** | Docker backend + frontend + nginx | Serverless containers for API + frontend | Per-request + vCPU-seconds |
| **Cloud Run Jobs** | Docker scheduler container | Nightly pipeline execution | Per-vCPU-second (job duration) |
| **Cloud Scheduler** | APScheduler library | Cron-based job triggers | $0.10/job/month |
| **Artifact Registry** | Local `docker build` | Docker image storage | Per-GB stored |
| **Secret Manager** | `.env` files | Secure API key storage | $0.06/10K accesses |
| **Cloud CDN** | Nginx serving local files | Fast global media delivery | Per-GB egress (discounted) |
| **Cloud Build** | Manual deploy | CI/CD pipelines from GitHub | 120 free min/day |
| **Cloud Logging** | Container stdout | Centralized log aggregation | Free tier: 50 GB/month |
| **Cloud Monitoring** | None | Uptime checks, alerts, dashboards | Free tier generous |

### Google AI APIs (Already in Use — No Change)

These are already Google services accessed via API key. No migration needed:

| API | SDK | Auth Method |
|---|---|---|
| Gemini 2.5 Pro | `google-generativeai` | `GEMINI_API_KEY` |
| Google Cloud TTS | `google-cloud-texttospeech` | Service account (`GOOGLE_APPLICATION_CREDENTIALS`) |
| Veo 3.1 | `google-genai` | `GEMINI_API_KEY` |
| Nano Banana (Imagen) | `google-genai` | `GEMINI_API_KEY` |

---

## 3. Cloud SQL (Database)

### Instance Configuration

| Setting | Value | Reason |
|---|---|---|
| **Database engine** | MySQL 8.0 | Matches current Docker MySQL 8.0 |
| **Instance type** | `db-f1-micro` (dev) / `db-custom-1-3840` (prod) | 1 vCPU, 3.75 GB RAM for prod |
| **Storage** | 20 GB SSD (auto-increase enabled) | Current DB is <5 GB, room to grow |
| **Region** | `us-central1` | Low latency to Cloud Run services |
| **Availability** | Single zone (dev) / High availability (prod) | HA adds automatic failover |
| **Backups** | Automated daily, 7-day retention | Point-in-time recovery |
| **Maintenance window** | Sunday 07:00 UTC | After nightly pipeline completes |
| **Character set** | `utf8mb4` / `utf8mb4_unicode_ci` | Matches current config |
| **Flags** | `max_allowed_packet=64M`, `innodb_buffer_pool_size=256M` | Matches current MySQL args |

### Connection Strategy

Cloud Run → Cloud SQL via **Private IP** (VPC connector) or **Cloud SQL Auth Proxy** (sidecar).

**Recommended: Cloud SQL Auth Proxy** (simpler setup for Cloud Run)
- Cloud Run natively supports Cloud SQL connections via Unix socket
- No public IP exposure — connection is IAM-authenticated
- Add `--add-cloudsql-instances=PROJECT:REGION:INSTANCE` to Cloud Run service

### Connection String Change

```python
# Current (local)
DATABASE_URL = "mysql+pymysql://root:changeme@127.0.0.1:3306/house_advantage"

# Cloud Run (via Cloud SQL Auth Proxy Unix socket)
DATABASE_URL = "mysql+pymysql://root:{password}@/{db}?unix_socket=/cloudsql/{PROJECT}:{REGION}:{INSTANCE}"
```

### Migration Steps

1. Create Cloud SQL instance
2. Run `schema.sql` against Cloud SQL to create tables
3. Export local MySQL: `mysqldump -h 127.0.0.1 -P 3307 -u root -pchangeme house_advantage > dump.sql`
4. Import to Cloud SQL: `gcloud sql import sql INSTANCE gs://BUCKET/dump.sql --database=house_advantage`
5. Update `DATABASE_URL` in Secret Manager
6. Test connection from Cloud Run

### Existing Dump

`house_advantage_dump.sql` already exists in the repo root — can be used for initial Cloud SQL import.

---

## 4. Cloud Storage (Media & Static Files)

### Bucket Structure

```
gs://house-advantage-media/
├── trades/
│   ├── trade_{id}_audio.wav          # TTS narration (per-trade)
│   ├── trade_{id}_video.mp4          # Veo raw video (per-trade)
│   ├── trade_{id}_final.mp4          # Muxed final video (per-trade)
│   └── trade_{id}_citation_{n}.png   # Nano Banana citation images
├── daily/
│   ├── daily_{date}_audio.wav        # TTS daily narration
│   ├── daily_{date}_video.mp4        # Veo daily video
│   └── daily_{date}_final.mp4        # Muxed daily final
└── staging/
    └── (temporary files during pipeline, cleaned up after)
```

### Bucket Configuration

| Setting | Value | Reason |
|---|---|---|
| **Bucket name** | `house-advantage-media` (or project-specific) | Globally unique |
| **Location** | `us-central1` | Co-located with Cloud Run + Cloud SQL |
| **Storage class** | Standard | Frequent reads (media serving) |
| **Public access** | Uniform bucket-level (public read) | Media served to end users |
| **CORS** | Allow `*` origin, `GET` method | Frontend fetches media directly |
| **Lifecycle** | Delete `staging/` objects after 7 days | Cleanup temp files |
| **Object versioning** | Disabled | No need for media file versioning |

### Signed URLs vs. Public Access

**Recommended: Public read access** for the media bucket.
- All media content is public by design (no auth on the platform)
- Simpler frontend integration — direct `https://storage.googleapis.com/BUCKET/path` URLs
- `storage_url` column in `media_assets` table stores the full GCS URL
- Cloud CDN sits in front for caching

### SDK Addition

```
# Add to requirements.txt
google-cloud-storage>=2.18.0
```

---

## 5. Cloud Run (Backend API + Frontend)

### Service: `backend`

| Setting | Value | Reason |
|---|---|---|
| **Image** | `us-central1-docker.pkg.dev/PROJECT/house-advantage/backend:latest` | From Artifact Registry |
| **Port** | 8000 | FastAPI uvicorn |
| **CPU** | 1 vCPU | Sufficient for API serving |
| **Memory** | 512 MB | API is lightweight (no ML inference at request time) |
| **Min instances** | 0 (dev) / 1 (prod) | Cold start ~2s; keep 1 warm in prod |
| **Max instances** | 10 | Autoscale on traffic |
| **Concurrency** | 80 | FastAPI handles concurrent async requests |
| **Cloud SQL connection** | `PROJECT:us-central1:house-advantage-db` | Via Cloud SQL Auth Proxy |
| **Startup probe** | `GET /api/v1/systemic` with 10s timeout | Health check |
| **Ingress** | All traffic | Public API |

### Service: `frontend`

| Setting | Value | Reason |
|---|---|---|
| **Image** | `us-central1-docker.pkg.dev/PROJECT/house-advantage/frontend:latest` | From Artifact Registry |
| **Port** | 3000 | Next.js |
| **CPU** | 1 vCPU | SSR rendering needs some CPU |
| **Memory** | 512 MB | Next.js SSR |
| **Min instances** | 0 (dev) / 1 (prod) | Keep warm for fast first load |
| **Max instances** | 10 | Autoscale |
| **Env vars** | `NEXT_PUBLIC_API_BASE_URL=https://backend-HASH.run.app` | Points to backend Cloud Run URL |

### Nginx Replacement

Cloud Run handles HTTPS termination, load balancing, and routing natively. **Nginx is no longer needed.** The frontend calls the backend directly via its Cloud Run URL.

For a custom domain with unified routing (frontend + `/api/*` → backend), use **Cloud Load Balancer** with URL map (see Section 10).

---

## 6. Cloud Run Jobs (Nightly Pipeline)

The nightly pipeline (currently APScheduler in a Docker container) becomes a **Cloud Run Job** triggered by Cloud Scheduler.

### Job: `nightly-pipeline`

| Setting | Value | Reason |
|---|---|---|
| **Image** | Same backend image | Same Python environment, all pipeline code is in `backend/` |
| **CPU** | 2 vCPU | Heavier workload: ingestion, scoring, media generation |
| **Memory** | 2 GB | pandas DataFrames, ML model inference, media generation |
| **Timeout** | 14400s (4 hours) | Pipeline runs 02:00–06:00 UTC |
| **Max retries** | 1 | Retry once on failure |
| **Cloud SQL connection** | Same as backend service | Reads/writes all tables |
| **Task count** | 1 | Single sequential pipeline |
| **Command** | `python -m backend.gemini.pipeline_runner` | Or a new `run_nightly.py` entry point |

### Pipeline Stages as Separate Jobs (Alternative)

For better observability and independent retries, split into multiple Cloud Run Jobs:

| Job Name | Trigger Time | Command | Timeout |
|---|---|---|---|
| `pipeline-ingest` | 02:00 UTC | `python -m backend.ingest.orchestrator` | 7200s (2h) |
| `pipeline-score` | 04:00 UTC | `python -m backend.scoring.dual_scorer` | 1800s (30m) |
| `pipeline-contextualize` | 04:30 UTC | `python -m backend.gemini.contextualizer` | 1800s (30m) |
| `pipeline-media` | 05:00 UTC | `python -m backend.gemini.pipeline_runner` | 3600s (1h) |
| `pipeline-stats` | 06:00 UTC | `python -c "from backend.scoring.dual_scorer import ..."` | 300s (5m) |

**Recommendation:** Start with a single `nightly-pipeline` job for simplicity. Split later when you need independent retries or parallel execution.

---

## 7. Cloud Scheduler (Automation)

Cloud Scheduler replaces APScheduler. Each schedule triggers a Cloud Run Job execution.

### Schedule Configuration

| Schedule Name | Cron Expression | Target | Description |
|---|---|---|---|
| `nightly-pipeline` | `0 2 * * *` (02:00 UTC) | Cloud Run Job: `nightly-pipeline` | Full nightly pipeline |

If using split jobs:

| Schedule Name | Cron Expression | Target |
|---|---|---|
| `trigger-ingest` | `0 2 * * *` | Job: `pipeline-ingest` |
| `trigger-score` | `0 4 * * *` | Job: `pipeline-score` |
| `trigger-contextualize` | `30 4 * * *` | Job: `pipeline-contextualize` |
| `trigger-media` | `0 5 * * *` | Job: `pipeline-media` |
| `trigger-stats` | `0 6 * * *` | Job: `pipeline-stats` |

### Scheduler Configuration

```bash
gcloud scheduler jobs create http nightly-pipeline \
  --schedule="0 2 * * *" \
  --time-zone="UTC" \
  --uri="https://REGION-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT/jobs/nightly-pipeline:run" \
  --http-method=POST \
  --oauth-service-account-email=SCHEDULER_SA@PROJECT.iam.gserviceaccount.com
```

### Timezone

All schedules use **UTC** to match the current APScheduler config.

---

## 8. Artifact Registry (Container Images)

### Repository Setup

```bash
gcloud artifacts repositories create house-advantage \
  --repository-format=docker \
  --location=us-central1 \
  --description="House Advantage container images"
```

### Images

| Image | Source | Used By |
|---|---|---|
| `house-advantage/backend` | `./backend/Dockerfile` | Cloud Run: backend, Cloud Run Jobs: pipeline |
| `house-advantage/frontend` | `./frontend/Dockerfile` | Cloud Run: frontend |

### Tagging Strategy

```
us-central1-docker.pkg.dev/PROJECT/house-advantage/backend:latest
us-central1-docker.pkg.dev/PROJECT/house-advantage/backend:v1.0.0
us-central1-docker.pkg.dev/PROJECT/house-advantage/backend:git-abc1234
```

### Image Lifecycle

- Keep last 10 tagged versions
- Auto-delete untagged images older than 30 days

---

## 9. Secret Manager (API Keys & Credentials)

All API keys and sensitive credentials move from `.env` files to Secret Manager.

### Secrets Inventory

| Secret Name | Current Source | Used By |
|---|---|---|
| `mysql-root-password` | `MYSQL_ROOT_PASSWORD` env var | Cloud SQL, backend, pipeline |
| `gemini-api-key` | `GEMINI_API_KEY` env var | backend, pipeline (contextualizer, Veo, Nano Banana, scriptwriter) |
| `google-cloud-api-key` | `GOOGLE_CLOUD_API_KEY` env var | pipeline (TTS) |
| `congress-gov-api-key` | `CONGRESS_GOV_API_KEY` env var | pipeline (ingestion) |
| `fec-api-key` | `FEC_API_KEY` env var | pipeline (ingestion) |
| `govinfo-api-key` | `GOVINFO_API_KEY` env var | pipeline (ingestion) |
| `openfigi-api-key` | `OPENFIGI_API_KEY` env var | pipeline (ingestion) |
| `database-url` | `DATABASE_URL` env var | backend, pipeline |

### Cloud Run Integration

Cloud Run mounts secrets as environment variables:

```bash
gcloud run services update backend \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest" \
  --set-secrets="DATABASE_URL=database-url:latest"
```

### Service Account Credentials

For Google Cloud TTS (which uses `GOOGLE_APPLICATION_CREDENTIALS`):
- Cloud Run's **default service account** has IAM roles assigned directly
- No JSON key file needed — Cloud Run automatically provides credentials
- Remove `GOOGLE_APPLICATION_CREDENTIALS` env var
- `google-cloud-texttospeech` SDK auto-discovers credentials via metadata server

---

## 10. Cloud CDN + Load Balancer (Media Serving)

### Option A: Cloud CDN on GCS Bucket (Simple)

Enable Cloud CDN directly on the GCS bucket backend:

```
User → Cloud CDN → GCS Bucket (house-advantage-media)
```

- Caches media files at Google's edge locations globally
- No Load Balancer needed for media-only CDN
- Media URLs: `https://storage.googleapis.com/house-advantage-media/trades/trade_123_final.mp4`

### Option B: Global Load Balancer + Cloud CDN (Full)

For custom domain routing (`houseadvantage.app`):

```
houseadvantage.app
├── /                     → Cloud Run: frontend
├── /api/*                → Cloud Run: backend
└── /media/*              → GCS bucket (CDN-backed)
```

**Setup:**
1. Reserve a global external IP: `gcloud compute addresses create ha-ip --global`
2. Create a URL map with three backend services:
   - Default → frontend Cloud Run NEG
   - `/api/*` → backend Cloud Run NEG
   - `/media/*` → GCS bucket backend
3. Create HTTPS proxy with managed SSL certificate
4. Enable Cloud CDN on the GCS backend

### CDN Cache Configuration

| Content Type | Cache TTL | Reason |
|---|---|---|
| Final videos (`*_final.mp4`) | 24 hours | Immutable once generated |
| Audio files (`*.wav`) | 24 hours | Immutable |
| Citation images (`*.png`) | 24 hours | Immutable |
| API responses | No cache | Dynamic data |

---

## 11. Cloud Build (CI/CD)

### Pipeline Triggers

| Trigger | Event | Actions |
|---|---|---|
| `build-backend` | Push to `main` (changes in `backend/**`) | Build + push backend image → deploy to Cloud Run |
| `build-frontend` | Push to `main` (changes in `frontend/**`) | Build + push frontend image → deploy to Cloud Run |
| `build-pipeline` | Push to `main` (changes in `backend/**`) | Build + push backend image → update Cloud Run Job |

### cloudbuild.yaml (Backend)

```yaml
steps:
  # Build
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'us-central1-docker.pkg.dev/$PROJECT_ID/house-advantage/backend:$COMMIT_SHA', '-f', 'backend/Dockerfile', '.']

  # Push
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'us-central1-docker.pkg.dev/$PROJECT_ID/house-advantage/backend:$COMMIT_SHA']

  # Deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    args:
      - 'run'
      - 'services'
      - 'update'
      - 'backend'
      - '--image=us-central1-docker.pkg.dev/$PROJECT_ID/house-advantage/backend:$COMMIT_SHA'
      - '--region=us-central1'
    entrypoint: gcloud

  # Update Cloud Run Job (pipeline uses same image)
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    args:
      - 'run'
      - 'jobs'
      - 'update'
      - 'nightly-pipeline'
      - '--image=us-central1-docker.pkg.dev/$PROJECT_ID/house-advantage/backend:$COMMIT_SHA'
      - '--region=us-central1'
    entrypoint: gcloud

images:
  - 'us-central1-docker.pkg.dev/$PROJECT_ID/house-advantage/backend:$COMMIT_SHA'
```

### GitHub Integration

```bash
gcloud builds triggers create github \
  --repo-name=house_advantage \
  --repo-owner=mitcheltu \
  --branch-pattern="^main$" \
  --included-files="backend/**" \
  --build-config=cloudbuild-backend.yaml
```

---

## 12. Cloud Logging & Monitoring

### Logging

Cloud Run and Cloud Run Jobs automatically send stdout/stderr to Cloud Logging. No configuration needed.

**Structured logging** — update Python logging to JSON format for better Cloud Logging integration:

```python
import json, logging

class CloudRunHandler(logging.StreamHandler):
    def emit(self, record):
        log_entry = {
            "severity": record.levelname,
            "message": record.getMessage(),
            "module": record.module,
        }
        print(json.dumps(log_entry))
```

### Monitoring & Alerts

| Alert | Condition | Channel |
|---|---|---|
| Pipeline failure | Cloud Run Job `nightly-pipeline` fails | Email notification |
| Backend error rate | >5% 5xx responses over 5 minutes | Email notification |
| Cloud SQL CPU | >80% for 10 minutes | Email notification |
| Cloud SQL storage | >80% capacity | Email notification |
| Media generation failed | `media_assets.generation_status = 'failed'` count > 0 | Custom log-based metric |

### Uptime Checks

| Check | URL | Interval |
|---|---|---|
| Backend health | `https://backend-HASH.run.app/api/v1/systemic` | 5 min |
| Frontend health | `https://houseadvantage.app/` | 5 min |

---

## 13. Networking & Domain

### Custom Domain Setup

1. Register domain (e.g., `houseadvantage.app`)
2. Create managed SSL certificate via Google-managed certificate
3. Map to Load Balancer (see Section 10, Option B)
4. DNS: A record → Load Balancer IP

### VPC Connector (Cloud Run → Cloud SQL)

```bash
gcloud compute networks vpc-access connectors create ha-connector \
  --region=us-central1 \
  --range=10.8.0.0/28
```

Attach to Cloud Run services:

```bash
gcloud run services update backend \
  --vpc-connector=ha-connector \
  --vpc-egress=private-ranges-only
```

### Firewall

- Cloud SQL: No public IP — only accessible via VPC connector or Cloud SQL Auth Proxy
- Cloud Run: HTTPS only (auto-managed TLS)
- GCS bucket: Public read for media, no write access from internet

---

## 14. Environment Variable Migration

### Current → GCP Mapping

| Current Env Var | GCP Source | How Accessed |
|---|---|---|
| `MYSQL_HOST=127.0.0.1` | Cloud SQL instance connection name | Unix socket (auto) |
| `MYSQL_PORT=3306` | N/A (Unix socket) | N/A |
| `MYSQL_USER=root` | Secret Manager | `--set-secrets` |
| `MYSQL_PASSWORD=changeme` | Secret Manager | `--set-secrets` |
| `MYSQL_DATABASE=house_advantage` | Environment variable | `--set-env-vars` |
| `DATABASE_URL` | Secret Manager (constructed URL with Unix socket) | `--set-secrets` |
| `GEMINI_API_KEY` | Secret Manager | `--set-secrets` |
| `GOOGLE_CLOUD_API_KEY` | Secret Manager | `--set-secrets` |
| `CONGRESS_GOV_API_KEY` | Secret Manager | `--set-secrets` |
| `FEC_API_KEY` | Secret Manager | `--set-secrets` |
| `GOVINFO_API_KEY` | Secret Manager | `--set-secrets` |
| `OPENFIGI_API_KEY` | Secret Manager | `--set-secrets` |
| `GOOGLE_APPLICATION_CREDENTIALS` | **Remove** — Cloud Run uses default SA | Metadata server |
| `MEDIA_STAGING_DIR` | `/tmp/media_staging` (Cloud Run ephemeral) | `--set-env-vars` |
| `MEDIA_OUTPUT_DIR` | **Remove** — write directly to GCS | N/A |
| `GCS_BUCKET` | `house-advantage-media` | `--set-env-vars` |
| `NEXT_PUBLIC_API_BASE_URL` | Cloud Run backend URL or custom domain | `--set-env-vars` |
| `ALLOWED_ORIGINS` | Custom domain | `--set-env-vars` |

### New Env Vars (GCP-specific)

| Env Var | Value | Purpose |
|---|---|---|
| `GCP_PROJECT` | `your-project-id` | Project reference |
| `CLOUD_SQL_INSTANCE` | `PROJECT:us-central1:ha-db` | Cloud SQL connection name |
| `GCS_BUCKET` | `house-advantage-media` | Media storage bucket |
| `STORAGE_BACKEND` | `gcs` | Toggle local vs. GCS storage in code |

---

## 15. Code Changes Required

### 15.1 Storage Abstraction Layer

Create a storage abstraction so the code works both locally and with GCS:

**New file: `backend/storage.py`**

```python
import os
from pathlib import Path

STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")  # "local" or "gcs"
GCS_BUCKET = os.getenv("GCS_BUCKET", "")

def upload_file(local_path: str, remote_key: str) -> str:
    """Upload a file and return its public URL."""
    if STORAGE_BACKEND == "gcs" and GCS_BUCKET:
        from google.cloud import storage
        client = storage.Client()
        bucket = client.bucket(GCS_BUCKET)
        blob = bucket.blob(remote_key)
        blob.upload_from_filename(local_path)
        return f"https://storage.googleapis.com/{GCS_BUCKET}/{remote_key}"
    else:
        # Local storage — return local path as URL
        return str(local_path)

def get_public_url(remote_key: str) -> str:
    """Get the public URL for a stored file."""
    if STORAGE_BACKEND == "gcs" and GCS_BUCKET:
        return f"https://storage.googleapis.com/{GCS_BUCKET}/{remote_key}"
    else:
        output_dir = os.getenv("MEDIA_OUTPUT_DIR", "backend/data/media")
        return str(Path(output_dir) / remote_key)
```

### 15.2 Pipeline Runner Changes

Update `pipeline_runner.py` to upload to GCS after media generation:

```python
# After ffmpeg assembly, upload final files to GCS
from backend.storage import upload_file

final_url = upload_file(
    local_path=str(final_path),
    remote_key=f"trades/trade_{trade_id}_final.mp4"
)
# Use final_url when writing to media_assets.storage_url
```

### 15.3 FFmpeg Assembly Changes

Update `write_media_asset()` in `ffmpeg_assembly.py` to store GCS URLs in `storage_url`.

### 15.4 Database Connection

Update `connection.py` to support Cloud SQL Unix socket:

```python
CLOUD_SQL_INSTANCE = os.getenv("CLOUD_SQL_INSTANCE", "")

if CLOUD_SQL_INSTANCE:
    # Cloud Run: connect via Unix socket
    url = f"mysql+pymysql://{user}:{password}@/{db}?unix_socket=/cloudsql/{CLOUD_SQL_INSTANCE}&charset=utf8mb4"
else:
    # Local: connect via TCP
    url = f"mysql+pymysql://{user}:{password}@{host}:{port}/{db}?charset=utf8mb4"
```

### 15.5 Media Serving API

Update `routers/reports.py` (media streaming endpoint) — if `STORAGE_BACKEND=gcs`, redirect to GCS URL instead of streaming from local disk:

```python
if os.getenv("STORAGE_BACKEND") == "gcs":
    return RedirectResponse(url=asset.storage_url)
else:
    return FileResponse(asset.storage_url)
```

### 15.6 Requirements Addition

```
# Add to requirements.txt
google-cloud-storage>=2.18.0
```

### 15.7 Dockerfiles

Ensure `backend/Dockerfile` and `frontend/Dockerfile` exist and are optimized for Cloud Run:

- Multi-stage builds
- Non-root user
- Only production dependencies
- `ffmpeg` installed in backend image (for media assembly)

---

## 16. Cost Estimate

### Monthly Cost (Low Traffic — MVP / Hackathon)

| Service | Spec | Est. Monthly Cost |
|---|---|---|
| **Cloud SQL** | db-f1-micro, 10GB SSD, single zone | ~$8 |
| **Cloud Run: backend** | 1 vCPU, 512MB, min 0 instances | ~$0–5 (pay per request) |
| **Cloud Run: frontend** | 1 vCPU, 512MB, min 0 instances | ~$0–5 (pay per request) |
| **Cloud Run Jobs** | 2 vCPU, 2GB, ~4h/day nightly | ~$7 |
| **Cloud Scheduler** | 5 cron jobs | ~$0.50 |
| **Cloud Storage** | ~5 GB media files | ~$0.10 |
| **Artifact Registry** | ~2 GB images | ~$0.20 |
| **Secret Manager** | 8 secrets, ~1K accesses/month | ~$0.01 |
| **Cloud CDN** | Minimal egress at MVP | ~$0–2 |
| **Cloud Build** | <120 min/day (free tier) | **$0** |
| **Cloud Logging** | <50 GB/month (free tier) | **$0** |
| **Managed SSL** | Included | **$0** |
| **TOTAL** | | **~$20–30/month** |

### Scaling Cost (Moderate Traffic)

| Scenario | Additional Cost |
|---|---|
| 10K daily users | Cloud Run scales up: +$10–20/month |
| 100K daily users | Cloud SQL upgrade + CDN egress: +$50–100/month |
| 50GB media files | GCS storage: ~$1/month |
| Cloud SQL HA (prod) | Doubles DB cost: +$8/month |

### Free Tier Benefits

- Cloud Run: 2M requests/month free, 360K vCPU-seconds free
- Cloud Build: 120 build-minutes/day free
- Cloud Logging: 50 GB/month free
- Cloud Storage: 5 GB/month free (Standard in us regions)
- Secret Manager: 6 active secret versions free

---

## 17. Implementation Phases

### Phase 1: Foundation (Day 1)

**Goal:** GCP project setup, Cloud SQL, Artifact Registry

- [ ] Create GCP project (or use existing)
- [ ] Enable APIs: Cloud Run, Cloud SQL, Cloud Storage, Cloud Build, Secret Manager, Cloud Scheduler, Artifact Registry
- [ ] Create Artifact Registry repository
- [ ] Create Cloud SQL instance (MySQL 8.0)
- [ ] Import `house_advantage_dump.sql` into Cloud SQL
- [ ] Store all API keys in Secret Manager
- [ ] Verify DB connection from local machine via Cloud SQL Auth Proxy

### Phase 2: Storage (Day 1–2)

**Goal:** GCS bucket, storage abstraction layer

- [ ] Create GCS bucket `house-advantage-media`
- [ ] Configure public read access + CORS
- [ ] Add `google-cloud-storage` to `requirements.txt`
- [ ] Create `backend/storage.py` abstraction layer
- [ ] Update `pipeline_runner.py` to upload to GCS
- [ ] Update `ffmpeg_assembly.py` to store GCS URLs
- [ ] Update media streaming endpoint to redirect to GCS
- [ ] Test: run pipeline locally, verify files land in GCS

### Phase 3: Containers (Day 2)

**Goal:** Dockerfiles optimized for Cloud Run, images pushed

- [ ] Create/update `backend/Dockerfile` (multi-stage, ffmpeg, non-root)
- [ ] Create/update `frontend/Dockerfile` (multi-stage, non-root)
- [ ] Build and push images to Artifact Registry
- [ ] Test images locally with `docker run`

### Phase 4: Deploy Services (Day 2–3)

**Goal:** Backend + Frontend live on Cloud Run

- [ ] Deploy backend to Cloud Run with Cloud SQL connection + secrets
- [ ] Deploy frontend to Cloud Run with API URL env var
- [ ] Test all API endpoints against Cloud Run backend
- [ ] Test frontend renders correctly with Cloud Run backend

### Phase 5: Automation (Day 3)

**Goal:** Nightly pipeline running automatically

- [ ] Create Cloud Run Job `nightly-pipeline`
- [ ] Update `connection.py` for Cloud SQL Unix socket support
- [ ] Set `STORAGE_BACKEND=gcs` in job env
- [ ] Create Cloud Scheduler cron trigger(s)
- [ ] Run job manually via `gcloud run jobs execute` — verify full pipeline
- [ ] Monitor via Cloud Logging

### Phase 6: Production Hardening (Day 4+)

**Goal:** Domain, CDN, monitoring, CI/CD

- [ ] Set up Cloud Build triggers from GitHub `main` branch
- [ ] Configure Cloud CDN on GCS bucket
- [ ] Set up Global Load Balancer (if using custom domain)
- [ ] Configure managed SSL certificate
- [ ] Map custom domain DNS
- [ ] Set up Cloud Monitoring alerts (pipeline failure, error rate, DB health)
- [ ] Set up uptime checks
- [ ] Test end-to-end: push to `main` → auto-build → auto-deploy → scheduler runs → media in GCS → frontend serves

---

## Architecture Diagram (Target State)

```
                    ┌─────────────────────┐
                    │   Cloud Scheduler    │
                    │   (0 2 * * * UTC)    │
                    └──────────┬──────────┘
                               │ triggers
                               ▼
                    ┌─────────────────────┐
                    │  Cloud Run Job      │
                    │  nightly-pipeline   │
                    │  ┌───────────────┐  │
                    │  │ Ingest        │  │──→ Congress.gov, SEC, yfinance
                    │  │ Score         │  │
                    │  │ Contextualize │  │──→ Gemini 2.5 Pro API
                    │  │ TTS           │  │──→ Google Cloud TTS API
                    │  │ Veo + Nano    │  │──→ Veo 3.1 / Nano Banana API
                    │  │ ffmpeg        │  │
                    │  └───────────────┘  │
                    └───┬─────────┬───────┘
                        │         │
               writes   │         │ uploads
                        ▼         ▼
              ┌──────────┐  ┌──────────────┐
              │ Cloud SQL│  │ Cloud Storage │
              │ MySQL 8.0│  │ (GCS Bucket)  │
              │          │  │ MP4/WAV/PNG   │
              └────┬─────┘  └──────┬───────┘
                   │               │
              reads│               │ CDN-cached
                   ▼               ▼
              ┌──────────────────────────────┐
              │  Cloud Run: backend (FastAPI) │
              │  /api/v1/*                    │
              └──────────────┬───────────────┘
                             │ JSON API
                             ▼
              ┌──────────────────────────────┐
              │  Cloud Run: frontend (Next.js)│
              │  houseadvantage.app           │
              └──────────────────────────────┘
                             │
                     ┌───────┴───────┐
                     │ Cloud CDN +   │
                     │ Load Balancer │
                     │ (HTTPS)       │
                     └───────┬───────┘
                             │
                             ▼
                          Users
```

---

## Quick Reference: gcloud Commands

```bash
# === PROJECT SETUP ===
gcloud config set project YOUR_PROJECT_ID
gcloud services enable \
  run.googleapis.com \
  sqladmin.googleapis.com \
  storage.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  cloudscheduler.googleapis.com \
  artifactregistry.googleapis.com \
  compute.googleapis.com

# === ARTIFACT REGISTRY ===
gcloud artifacts repositories create house-advantage \
  --repository-format=docker --location=us-central1

# === CLOUD SQL ===
gcloud sql instances create ha-db \
  --database-version=MYSQL_8_0 \
  --tier=db-f1-micro \
  --region=us-central1 \
  --storage-size=20GB \
  --storage-auto-increase

gcloud sql databases create house_advantage --instance=ha-db
gcloud sql users set-password root --instance=ha-db --password=YOUR_PASSWORD

# === CLOUD STORAGE ===
gcloud storage buckets create gs://house-advantage-media \
  --location=us-central1 --uniform-bucket-level-access
gcloud storage buckets add-iam-policy-binding gs://house-advantage-media \
  --member=allUsers --role=roles/storage.objectViewer

# === SECRET MANAGER ===
echo -n "YOUR_KEY" | gcloud secrets create gemini-api-key --data-file=-
echo -n "YOUR_KEY" | gcloud secrets create congress-gov-api-key --data-file=-
# ... repeat for each secret

# === CLOUD RUN: BACKEND ===
gcloud run deploy backend \
  --image=us-central1-docker.pkg.dev/PROJECT/house-advantage/backend:latest \
  --region=us-central1 \
  --port=8000 \
  --memory=512Mi \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest,DATABASE_URL=database-url:latest" \
  --set-env-vars="GCS_BUCKET=house-advantage-media,STORAGE_BACKEND=gcs" \
  --add-cloudsql-instances=PROJECT:us-central1:ha-db \
  --allow-unauthenticated

# === CLOUD RUN: FRONTEND ===
gcloud run deploy frontend \
  --image=us-central1-docker.pkg.dev/PROJECT/house-advantage/frontend:latest \
  --region=us-central1 \
  --port=3000 \
  --memory=512Mi \
  --set-env-vars="NEXT_PUBLIC_API_BASE_URL=https://backend-HASH.run.app" \
  --allow-unauthenticated

# === CLOUD RUN JOB: PIPELINE ===
gcloud run jobs create nightly-pipeline \
  --image=us-central1-docker.pkg.dev/PROJECT/house-advantage/backend:latest \
  --region=us-central1 \
  --cpu=2 --memory=2Gi --task-timeout=14400s \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest,DATABASE_URL=database-url:latest,CONGRESS_GOV_API_KEY=congress-gov-api-key:latest,FEC_API_KEY=fec-api-key:latest,GOVINFO_API_KEY=govinfo-api-key:latest" \
  --set-env-vars="GCS_BUCKET=house-advantage-media,STORAGE_BACKEND=gcs" \
  --add-cloudsql-instances=PROJECT:us-central1:ha-db

# === CLOUD SCHEDULER ===
gcloud scheduler jobs create http trigger-nightly-pipeline \
  --schedule="0 2 * * *" --time-zone="UTC" \
  --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT/jobs/nightly-pipeline:run" \
  --http-method=POST \
  --oauth-service-account-email=PROJECT_NUMBER-compute@developer.gserviceaccount.com

# === MANUAL TEST ===
gcloud run jobs execute nightly-pipeline --region=us-central1
```
