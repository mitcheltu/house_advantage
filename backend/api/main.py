import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.api.routers import audit, health, jobs, politicians, prices, reports, systemic


app = FastAPI(
    title="House Advantage API",
    version="0.1.0",
    description="DB-first API for anomaly scoring, audits, and systemic stats.",
)

allowed_origins = os.getenv("ALLOWED_ORIGINS", "*").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in allowed_origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router)
app.include_router(systemic.router)
app.include_router(politicians.router)
app.include_router(audit.router)
app.include_router(jobs.router)
app.include_router(reports.router)
app.include_router(prices.router)
