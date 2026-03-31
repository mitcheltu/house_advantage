# House Advantage

**A Civic News Platform for Congressional Trade Accountability**

House Advantage automatically detects, investigates, and broadcasts statistically anomalous congressional stock trades. It combines a dual machine learning model with a Gemini-powered contextualizer and Google's genMedia APIs (Veo 3.1, TTS) to produce daily video news reports — fully automated, zero human editing.

> Built for the Google GenMedia Hackathon · March 2026

**Live frontend:** https://house-advantage-frontend-115145734496.us-west1.run.app

---

## Table of Contents

- [The Problem](#the-problem)
- [Live Deployment](#live-deployment)
- [How It Works](#how-it-works)
- [Dual-Model Architecture](#dual-model-architecture)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [Getting Started](#getting-started)
- [Environment Variables](#environment-variables)
- [Running the Application](#running-the-application)
- [API Endpoints](#api-endpoints)
- [GenMedia Pipeline](#genmedia-pipeline)
- [Data Ingestion](#data-ingestion)
- [ML Scoring Engine](#ml-scoring-engine)
- [Frontend](#frontend)
- [Testing](#testing)
- [Deployment](#deployment)
- [Legal & Ethical Safeguards](#legal--ethical-safeguards)

---

## The Problem

The STOCK Act requires members of Congress to publicly disclose stock trades. That data sits in raw government databases that most people will never read. Existing tools surface numbers — they don't explain them. A constituent seeing that their senator bought $250,000 of Lockheed Martin stock has no way of knowing whether that's suspicious without hours of cross-referencing voting records, committee assignments, and campaign finance disclosures.

House Advantage closes that gap with two distinct layers of insight:

- **Individual accusation:** *"This specific trade is unusual even by congressional standards"*
- **Systemic accusation:** *"Congressional trading as a whole is unusual compared to normal investors"*

---

## Live Deployment

- Frontend: https://house-advantage-frontend-115145734496.us-west1.run.app
- Backend API base: https://house-advantage-api-115145734496.us-west1.run.app

---

## How It Works

```
Public STOCK Act Disclosures
        ↓
Model 1 (Cohort Model): Is this unusual within Congress?
Model 2 (Baseline Model): Is this unusual vs. normal investors?
        ↓
Combined Dual Score → Severity Quadrant
        ↓
Gemini Contextualizer investigates SEVERE + SYSTEMIC trades
  → Function-calls DB tools, reads bill text, cross-references evidence
  → Stores sourced context analysis in audit_reports table
        ↓
Daily Video Scriptwriter (Gemini) reviews the day's flagged trades
  → Writes ~30s narration script + Veo video prompt
        ↓
TTS generates narration audio → Veo 3.1 generates video
  → ffmpeg muxes audio + video → Daily video report published
        ↓
Users browse news feed, explore politician index, view trade timelines
```

---

## Dual-Model Architecture

House Advantage uses **two separate anomaly detection models** that produce a two-dimensional signal neither model alone can provide.

| Model | Training Data | Purpose |
|---|---|---|
| **Model 1 — Cohort Model** | Congressional trades (9 features) | Identifies trades unusual *within Congress* |
| **Model 2 — Baseline Model** | SEC 13-F institutional fund trades | Establishes what normal market participation looks like |

### Severity Quadrants

Every trade is placed into one of four quadrants based on its two anomaly scores:

| Cohort Score | Baseline Score | Quadrant | Meaning |
|---|---|---|---|
| 🔴 High | 🔴 High | **SEVERE** | Unusual even by congressional standards AND unlike normal investors |
| 🟠 Low | 🔴 High | **SYSTEMIC** | Normal within Congress but highly abnormal vs. the public |
| 🟡 High | 🟢 Low | **OUTLIER** | Statistical oddity within Congress but trades like a normal investor |
| 🟢 Low | 🟢 Low | **UNREMARKABLE** | Normal on both measures |

### V2 Scoring Features (9 Features)

1. **trade_size_usd** — Dollar value of the trade
2. **disclosure_lag** — Days between trade execution and public disclosure
3. **sector_concentration** — How concentrated the politician's portfolio is in one sector
4. **committee_relevance** — Whether the politician sits on a committee overseeing the traded company's sector
5. **bill_proximity** — Temporal proximity to relevant legislation
6. **trade_frequency** — Trading activity rate
7. **party_alignment** — Party-level trading pattern correlation
8. **market_timing** — Relationship between trade timing and subsequent price movements
9. **cohort_index** / **baseline_index** — Cross-model anomaly scores

### Current Stats

| Metric | Value |
|---|---|
| Congressional trades scored | 9,720 |
| SEVERE trades | 14 (0.1%) |
| SYSTEMIC trades | 379 (3.9%) |

---

## Tech Stack

### Backend
- **Python 3.13** — Core runtime
- **FastAPI** — REST API framework
- **MySQL 8.0** — Primary database (SQLAlchemy ORM)
- **scikit-learn** — Anomaly detection models (Isolation Forest)
- **Gemini 2.5 Pro** — Function-calling contextualizer, bill text analysis, script writing
- **Gemini TTS / Google Cloud TTS** — Narration audio generation (provider-configurable)
- **Veo 3.1** — Video generation with scene extensions
- **ffmpeg** — Audio/video muxing and assembly

### Frontend
- **Next.js 16** — React-based App Router
- **React 18** — UI rendering

### Infrastructure
- **Docker / Docker Compose** — Local development (MySQL)
- **Google Cloud Platform** — Production target (Cloud Run, Cloud SQL, GCS, Cloud Scheduler)

---

## Project Structure

```
House_Advantage/
├── backend/
│   ├── api/                    # FastAPI application
│   │   ├── main.py             # App entry point
│   │   └── routers/            # Route handlers
│   │       ├── audit.py        # Audit report endpoints
│   │       ├── health.py       # Health check
│   │       ├── jobs.py         # Pipeline job triggers
│   │       ├── politicians.py  # Politician profiles & search
│   │       ├── prices.py       # Stock price data
│   │       ├── reports.py      # Daily report retrieval
│   │       └── systemic.py     # Systemic metrics & leaderboard
│   ├── db/
│   │   ├── connection.py       # SQLAlchemy engine
│   │   ├── schema.sql          # Full database schema
│   │   ├── setup_db.py         # DB initialization
│   │   └── migrate_*.py        # Schema migrations
│   ├── gemini/
│   │   ├── contextualizer.py   # Gemini function-calling investigator
│   │   ├── daily_scriptwriter.py # Daily video script generation
│   │   ├── ffmpeg_assembly.py  # Audio/video muxing
│   │   ├── gcs_storage.py      # Google Cloud Storage integration
│   │   ├── media_generation.py # TTS + Veo orchestration
│   │   └── pipeline_runner.py  # End-to-end media pipeline
│   ├── ingest/
│   │   ├── orchestrator.py     # 12-step data collection orchestrator
│   │   └── collectors/         # Individual data source collectors
│   │       ├── collect_congress_gov.py
│   │       ├── collect_house_disclosures.py
│   │       ├── collect_senate_disclosures.py
│   │       ├── collect_sec_13f.py
│   │       ├── collect_prices.py
│   │       ├── collect_openfec.py
│   │       └── ...
│   └── scoring/
│       ├── dual_scorer.py      # V2 dual-model scoring engine
│       └── dual_scorer_v1.py   # V1 fallback scorer
├── frontend/
│   ├── app/
│   │   ├── page.js             # Home page (daily report + severe cases)
│   │   ├── layout.js           # Root layout
│   │   ├── daily/              # Daily report pages
│   │   └── politicians/        # Politician index & profiles
│   └── lib/                    # API client utilities
├── training/
│   ├── collect/                # Training data collection scripts
│   ├── model1/                 # Cohort Model training pipeline
│   └── model2/                 # Baseline Model training pipeline
├── model/                      # Trained model metadata & artifacts
├── scripts/                    # Automation & utility scripts
├── tests/                      # Test suite
├── data/                       # Raw, cleaned, and feature data
├── docker-compose.yml          # Local MySQL setup
├── Dockerfile                  # Production container image
├── Procfile                    # Cloud Run / Heroku entry point
└── requirements.txt            # Python dependencies
```

---

## Getting Started

### Prerequisites

- **Python 3.13+**
- **Node.js 18+** (for frontend)
- **Docker & Docker Compose** (for local MySQL)
- **ffmpeg** (for media pipeline)
- **Google Cloud SDK** (for GCP deployment)

### 1. Clone the Repository

```bash
git clone https://github.com/mitcheltu/house_advantage.git
cd house_advantage
```

### 2. Set Up Python Environment

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 3. Start MySQL (Docker)

```bash
docker compose up -d mysql
```

This starts a MySQL 8.0 instance on port 3306 and automatically runs `backend/db/schema.sql` for initial schema setup.

### 4. Initialize the Database

```bash
python -m backend.db.setup_db
```

### 5. Set Up Frontend

```bash
cd frontend
npm install
cd ..
```

---

## Environment Variables

Create a `.env` file in the project root:

```env
# Database
MYSQL_HOST=127.0.0.1
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=changeme
MYSQL_DATABASE=house_advantage

# Google AI
GEMINI_API_KEY=your_gemini_api_key
GOOGLE_CLOUD_PROJECT=your_gcp_project_id

# Google Cloud (media pipeline)
GOOGLE_APPLICATION_CREDENTIALS=path/to/service-account.json
GCS_BUCKET_NAME=your_gcs_bucket

# Data Sources
CONGRESS_GOV_API_KEY=your_congress_api_key
OPENFEC_API_KEY=your_openfec_api_key

# Frontend
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
```

---

## Running the Application

### Backend API

```bash
uvicorn backend.api.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm run dev
```

The frontend runs on `http://localhost:3000` and connects to the backend API.

### Daily Media Pipeline

```bash
python -m scripts.generate_daily_video --date 2026-03-28
```

This runs the full pipeline: contextualize flagged trades → generate scripts → TTS narration → Veo video → ffmpeg assembly.

### Data Ingestion

```bash
python -m backend.ingest.orchestrator
```

Runs the 12-step data collection pipeline across all configured sources.

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/v1/systemic` | Systemic metrics and aggregate stats |
| `GET` | `/api/v1/leaderboard` | Ranked scored trades (supports `quadrant`) |
| `GET` | `/api/v1/politicians` | Politician index with search |
| `GET` | `/api/v1/politician/{id}` | Individual politician profile & trades |
| `GET` | `/api/v1/daily-report/latest` | Latest daily video report metadata |
| `GET` | `/api/v1/daily-report/{date}` | Specific daily report |
| `GET` | `/api/v1/audit/{trade_id}` | Audit report for a specific trade |
| `GET` | `/api/v1/prices` | Historical ticker prices |
| `POST` | `/api/v1/jobs/run-daily-evidence` | Trigger the daily evidence/media pipeline |

---

## GenMedia Pipeline

House Advantage chains three Google AI models in a non-trivial intelligence pipeline:

| Step | Google Model | Role |
|---|---|---|
| 1 | **Gemini 2.5 Pro** (tool use) | Autonomously investigates SEVERE + SYSTEMIC trades by function-calling DB tools, reading bill text (50K–200K+ tokens), and cross-referencing evidence |
| 2 | **Gemini 2.5 Pro** (structured output) | Reviews the day's flagged trades and writes narration scripts for TTS and visual prompts for Veo |
| 3 | **Gemini TTS** (default) / **Google Cloud TTS** (fallback) | Converts narration scripts into natural-sounding audio |
| 4 | **Veo 3.1** | Generates ~30s news report videos using scene extensions (7s segments chained for continuity) |
| 5 | **ffmpeg** | Muxes narration audio + generated video into final reports |

Gemini writes the instructions for both TTS and Veo after investigating the trades — each daily report is the product of an autonomous AI investigation, not a template.

---

## Data Ingestion

The orchestrator collects data from 12 sources:

| Collector | Source | Data |
|---|---|---|
| `collect_congress_gov` | Congress.gov API | Bill metadata, sponsors, actions |
| `collect_house_disclosures` | House Clerk | House member trade disclosures |
| `collect_senate_disclosures` | Senate EFDS | Senate member trade disclosures |
| `collect_senate_votes` | Senate.gov | Voting records |
| `collect_committee_memberships` | Congress.gov | Committee assignments |
| `collect_openfec` | OpenFEC API | Campaign finance data |
| `collect_sec_13f` | SEC EDGAR | Institutional fund 13-F filings (baseline data) |
| `collect_prices` | Yahoo Finance | Historical stock prices |
| `collect_quiverquant` | QuiverQuant | Congressional trading data |
| `collect_openfigi` | OpenFIGI | Financial instrument identifiers |
| `collect_govinfo` | GovInfo API | Full bill text for Gemini analysis |
| `merge_trades` | Internal | Deduplicates and merges across sources |

---

## ML Scoring Engine

### Model 1 — Cohort Model

- **Algorithm:** Isolation Forest
- **Training data:** Congressional trades
- **Features:** 9 V2 features (trade size, disclosure lag, sector concentration, committee relevance, bill proximity, trade frequency, party alignment, market timing, cross-model index)
- **Purpose:** Flags trades that are unusual *within Congress*

### Model 2 — Baseline Model

- **Algorithm:** Isolation Forest
- **Training data:** SEC 13-F institutional fund manager filings
- **Features:** Comparable feature set normalized to institutional baselines
- **Purpose:** Flags trades that are unusual compared to *normal investors*

### Training

```bash
# Model 1 (Cohort)
python -m training.model1.train

# Model 2 (Baseline)
python -m training.model2.train
```

Model artifacts and metadata are stored in the `model/` directory.

---

## Frontend

The Next.js frontend has two main sections:

### Daily Report (`/`)
- AI-generated daily video report (main player)
- Severe Case Focus grid — paginated tiles for each SEVERE-flagged trade
- Sources & Context panel with Gemini contextualizer output, factor tags, bill references, and hyperlinked citations

### Politicians (`/politicians`)
- Searchable politician index with debounced search
- Politician cards showing name, party, state, chamber
- Expanded profile view with aggregate stats (total trades, SEVERE count, SYSTEMIC count, average anomaly scores)
- Interactive trade timeline

---

## Testing

```bash
# Run all tests
pytest

# Skip slow tests
pytest -m "not slow"

# Smoke test
python -m tests.smoke_test
```

Test coverage includes pipeline validation, model scoring, cross-model validation, and data integrity checks.

---

## Deployment

### Docker (Local)

```bash
docker compose up -d
```

### Google Cloud Platform (Production Target)

The GCP deployment plan targets fully managed services:

| Component | GCP Service |
|---|---|
| Database | Cloud SQL for MySQL 8.0 |
| Backend API | Cloud Run (autoscaling 0→N) |
| Frontend | Cloud Run |
| Nightly Pipeline | Cloud Run Jobs |
| Scheduling | Cloud Scheduler |
| Media Storage | Cloud Storage (GCS) + Cloud CDN |
| Container Registry | Artifact Registry |
| Secrets | Secret Manager |
| CI/CD | Cloud Build (from GitHub) |
| Observability | Cloud Logging & Monitoring |

### Build & Push

```bash
# Build container
docker build -t house-advantage .

# Tag and push to Artifact Registry
docker tag house-advantage gcr.io/$PROJECT_ID/house-advantage
docker push gcr.io/$PROJECT_ID/house-advantage
```

---

## Legal & Ethical Safeguards

- All data is sourced from **public government disclosures** (STOCK Act filings, Congress.gov, SEC EDGAR, OpenFEC)
- Anomaly scores are **statistical observations**, not accusations of wrongdoing
- Every contextualizer report includes a **disclaimer** that findings represent anomaly detection, not legal determinations
- All claims in generated reports are **linked to primary sources** with verifiable citations
- The platform surfaces patterns for public review — it does not make legal conclusions

---

## Target Audience

| Tier | Audience | Primary Feature |
|---|---|---|
| **General Public** | Social/civic audience | Daily ~30s AI-generated video news reports |
| **Journalists & Media** | Reporters, news outlets | Searchable trade database, contextualizer reports |
| **Watchdog Orgs** | Transparency advocates, researchers | Politician rankings, interactive timelines, filterable trade index |

---

## License

This project was built for the Google GenMedia Hackathon (March 2026).
