"""Paths and settings for Datapoint Studio (Phase 0)."""
from __future__ import annotations

import os
from pathlib import Path

# studio/backend/app/config.py -> studio/backend -> studio -> boe_xbrl_gen -> ClaudeLearning
BACKEND_DIR = Path(__file__).resolve().parent.parent
STUDIO_DIR = BACKEND_DIR.parent
ENGINE_DIR = STUDIO_DIR.parent           # boe_xbrl_gen
ROOT = ENGINE_DIR.parent                 # ClaudeLearning

# Prebuilt DPM model (counts shown in Phase 0 summary; per-package build is deferred).
MODEL_JSON = ENGINE_DIR / "model" / "dpm_model.json"

# Where uploaded packages are extracted, keyed by SHA-256 of the zip.
CACHE_DIR = Path(os.environ.get("STUDIO_CACHE", BACKEND_DIR / ".cache" / "packages"))

# CORS origins for the local Vite dev server.
DEV_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
]

CACHE_DIR.mkdir(parents=True, exist_ok=True)
