# House Advantage — Product, Implementation Status, and Launch Plan

## 1) Application Idea (What you are building)

House Advantage is a public-interest oversight platform that:

1. Ingests congressional trading + related political/public data.
2. Scores trades using anomaly models (baseline + cohort/contextual).
3. Assigns severity bands (including SEVERE/SYSTEMIC).
4. Generates explainable audit context for flagged trades.
5. Produces short, broadcast-style daily media outputs (audio + video) for transparent public reporting.
6. Serves API + web dashboard views for systemic risk and leaderboard visibility.

Core goal: highlight statistically unusual trading activity for review (not legal conclusions), with traceable evidence and media summaries.

---

## 2) What is Implemented

### Backend/API
- FastAPI service with routers for:
  - health
  - jobs
  - politicians/leaderboard
  - systemic metrics
  - audit retrieval
  - daily report retrieval
- MySQL-backed schema and setup scripts.
- DB-first read APIs working for seeded/demo records.

### Pipeline
- End-to-end runner exists for daily flow:
  1. contextualize flagged trades
  2. generate daily script
  3. generate severe trade media
  4. generate daily report media
- Trade and daily media assembly uses ffmpeg muxing.
- Fallback behavior exists when model providers fail.

### Frontend
- Next.js app fetching backend APIs.
- Home screen shows systemic data, leaderboard, audit preview, and daily media snapshot.

### Developer Setup
- Local Docker MySQL path works.
- Python venv path works.
- ffmpeg installed and detected.

---

## 3) What is Not Fully Implemented / Not Yet Production-Ready

1. True production data quality and canonical ETL governance (friend is actively fixing backend data correctness).
2. Guaranteed real Veo generation in all environments (depends on provider quota/access and key/project entitlements).
3. Production security hardening (secret management, key rotation policy, stricter CORS, auth/rate-limit strategy).
4. Formal observability stack (structured logs/alerts/dashboards/SLOs).
5. Full CI/CD deployment pipeline + infra-as-code + production runbooks.
6. Compliance/legal review text and disclaimers for public release.

---

## 4) Current Blocking Issues (as of now)

1. Video generation is blocked by Google API quota/entitlement behavior for the current key/project.
2. Dataset correctness is in-progress; wrong backend data can degrade audit/script quality and trustworthiness.
3. Existing exposed keys must be rotated before launch.

---

## 5) Does wrong backend data affect current issue?

- Yes for content quality (scores, scripts, audits, credibility).
- No for the immediate Veo call failure itself.
  - Veo failure is provider access/quota/endpoint entitlement related.

---

## 6) What Needs To Be Done Next (Priority Order)

### P0 — Launch blockers
1. Acquire production-capable video key/project (billing-enabled and quota-approved for chosen Veo model/method).
2. Rotate all previously exposed API keys immediately.
3. Finish data correctness fixes and validate against known-good fixtures.

### P1 — Reliability + quality
4. Run full backfill and scoring with corrected data.
5. Validate pipeline output quality for at least 7 consecutive daily runs.
6. Add regression checks for schema + scoring + report generation.

### P2 — Production hardening
7. Move secrets from local env files to managed secret store.
8. Add auth boundaries and abuse controls for public endpoints.
9. Add monitoring/alerting for pipeline and API health.
10. Add deployment docs and rollback runbook.

---

## 7) Recommended Launch Checklist

- [ ] Billing-enabled Veo access confirmed
- [ ] Video generation status turns `ready` for daily report
- [ ] Corrected data loaded and verified
- [ ] Keys rotated and stored securely
- [ ] Frontend displays valid non-demo records
- [ ] End-to-end smoke test passes
- [ ] Incident/rollback plan documented

---

## 8) Key Files To Review

- Pipeline entry: [backend/gemini/run_pipeline.py](backend/gemini/run_pipeline.py)
- Pipeline orchestration: [backend/gemini/pipeline_runner.py](backend/gemini/pipeline_runner.py)
- Media generation: [backend/gemini/media_generation.py](backend/gemini/media_generation.py)
- API app wiring: [backend/api/main.py](backend/api/main.py)
- Jobs endpoint: [backend/api/routers/jobs.py](backend/api/routers/jobs.py)
- Frontend API client: [frontend/lib/api.js](frontend/lib/api.js)
- Environment config: [.env](.env)

---

## 9) Practical Note for Your Immediate Question

If you are moving to a new account/project for Veo tokens, waiting is reasonable. The fastest safe path is:

1. Create billing-enabled project.
2. Enable the required API/model access.
3. Generate new key.
4. Update env + rerun pipeline.
5. Confirm daily media status is `ready`.
