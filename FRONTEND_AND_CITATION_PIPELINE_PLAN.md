# House Advantage — Frontend + Nano Banana Citation Image Pipeline Plan

**Date:** March 27, 2026
**Status:** Draft

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State](#2-current-state)
3. [Citation Image Pipeline — Full Flow](#3-citation-image-pipeline--full-flow)
4. [How Nano Banana Images Get Inside Veo Videos](#4-how-nano-banana-images-get-inside-veo-videos)
5. [Backend Changes](#5-backend-changes)
6. [Frontend Implementation Plan](#6-frontend-implementation-plan)
7. [API Additions](#7-api-additions)
8. [Implementation Phases](#8-implementation-phases)

---

## 1. Executive Summary

Two new capabilities layered onto the existing pipeline:

1. **Bill data flows into the contextualizer** — actual bill metadata (title, policy area, action date, URL) is fetched and sent to Gemini, not just numeric feature scores.
2. **Nano Banana generates bill citation card images** — one per relevant bill (up to 3). These images are **fed into Veo 3.1 as reference images**, so Veo natively incorporates the citation visuals into the generated video. No manual compositing needed.

The frontend displays the combined result: a single video that visually features the citation cards alongside abstract investigative visuals, plus standalone citation images in the trade detail page for sharing.

---

## 2. Current State

### Pipeline (working)
```
Contextualizer → Daily Scriptwriter → TTS (Gemini/GCP) → Veo 3.1 → FFmpeg mux → final MP4
```

### Gap: No bill data
- `_fetch_trade_context()` queries trades + anomaly_scores + politicians only
- Gemini sees numeric features (`feat_bill_proximity`, `feat_committee_relevance`) but never bill titles, text, or URLs
- `bill_excerpt` in audit_reports is always null

### Frontend (minimal)
- Single page `/` with stat cards + leaderboard table
- `lib/api.js` with `fetchSystemic()` and `fetchLeaderboard()`
- No other pages, components, or routes exist
- `FRONTEND_UI_UX_PROMPT.md` describes the full target UI (7 pages, 14 components) but nothing is built yet

---

## 3. Citation Image Pipeline — Full Flow

### End-to-End Pipeline (New)

```
                    ┌─────────────────────────────────────┐
                    │  Stage 0: Data Ingestion (nightly)   │
                    │  Orchestrator fetches bills from      │
                    │  Congress.gov + GovInfo               │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  Stage 1: Contextualizer (CHANGED)   │
                    │                                      │
                    │  1a. Fetch trade + scores + politician│
                    │  1b. NEW: Fetch top 3 sector-matched │
                    │      bills within ±90 days            │
                    │  1c. Build Gemini prompt WITH bills   │
                    │  1d. Gemini returns:                  │
                    │      - headline, narrative            │
                    │      - bill_excerpt (now populated!)  │
                    │      - video_prompt (updated to       │
                    │        reference citation visuals)    │
                    │      - narration_script (names bills) │
                    │      - NEW: citation_image_prompts[]  │
                    │        (one prompt per relevant bill) │
                    │  1e. Upsert audit_reports             │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  Stage 1.5: Citation Image Gen (NEW)  │
                    │                                      │
                    │  For each citation_image_prompt:      │
                    │  ├─ Nano Banana 2 generates image    │
                    │  │  (gemini-3.1-flash-image-preview) │
                    │  │  Aspect: 16:9, Resolution: 2K     │
                    │  │  Content: bill title, key excerpt, │
                    │  │  trade context, data-viz style    │
                    │  ├─ Save PNG to disk                  │
                    │  ├─ Register in media_assets          │
                    │  │  (asset_type='citation_image')     │
                    │  └─ Store file references for Veo     │
                    │                                      │
                    │  Output: Up to 3 citation PNGs/trade  │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  Stage 2: Daily Scriptwriter          │
                    │  (unchanged — uses audit_reports)     │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  Stage 3: Per-Trade Media Gen (CHANGED)│
                    │                                      │
                    │  3a. TTS: narration_script → WAV     │
                    │      (unchanged)                     │
                    │                                      │
                    │  3b. Veo 3.1: video_prompt → MP4     │
                    │      NEW: Pass citation images as     │
                    │      reference_images to Veo 3.1     │
                    │      ┌───────────────────────────┐   │
                    │      │ reference_images=[         │   │
                    │      │   citation_1.png (asset),  │   │
                    │      │   citation_2.png (asset),  │   │
                    │      │   citation_3.png (asset)   │   │
                    │      │ ]                          │   │
                    │      └───────────────────────────┘   │
                    │      Veo incorporates the citation   │
                    │      card visuals into the video     │
                    │      natively — they appear as       │
                    │      on-screen documents, data cards,│
                    │      or news-style lower thirds      │
                    │                                      │
                    │  3c. FFmpeg: mux audio + video → MP4 │
                    │      (unchanged)                     │
                    │                                      │
                    │  3d. Register all assets              │
                    └──────────────┬──────────────────────┘
                                   │
                    ┌──────────────▼──────────────────────┐
                    │  Stage 4: Daily Report Media          │
                    │  (unchanged)                         │
                    └──────────────────────────────────────┘
```

### Per-Trade Asset Tree (After Pipeline)

```
trade_12345/
├── audio/
│   └── trade_12345_audio.wav          (TTS narration)
├── citation_images/
│   ├── trade_12345_citation_0.png     (H.R. 1234 — Defense Appropriations)
│   ├── trade_12345_citation_1.png     (S. 567 — Military Readiness Act)
│   └── trade_12345_citation_2.png     (H.R. 890 — Pentagon Budget Review)
├── video/
│   └── trade_12345_video.mp4          (Veo raw — citations baked in)
└── final/
    └── trade_12345_final.mp4          (FFmpeg muxed — audio + video)
```

---

## 4. How Nano Banana Images Get Inside Veo Videos

### Mechanism: Veo 3.1 Reference Images

Veo 3.1 supports passing **up to 3 reference images** via the `reference_images` parameter with `reference_type="asset"`. Veo preserves the subject's appearance from the reference images in the generated video. This is the native, API-supported way to embed visual assets.

### How It Looks in Practice

The `video_prompt` (authored by Gemini in Stage 1) is updated to explicitly direct Veo to incorporate the citation cards:

```
"An investigative newsroom-style video report on a flagged congressional trade.
The video opens on a data visualization screen showing anomaly scores, then
transitions to display the bill citation cards as on-screen documents—each
appearing briefly like evidence being reviewed on a news desk. The camera slowly
zooms through abstract data streams and legislative symbols. Dark civic tone,
9:16 portrait, no real faces. The citation card images should appear clearly
as key evidence documents within the report."
```

### API Call

```python
from google import genai
from google.genai import types

# citation images generated by Nano Banana earlier
citation_refs = [
    types.VideoGenerationReferenceImage(
        image=citation_image_1,  # PIL Image or file reference
        reference_type="asset"
    ),
    types.VideoGenerationReferenceImage(
        image=citation_image_2,
        reference_type="asset"
    ),
]

operation = client.models.generate_videos(
    model="veo-3.1-generate-preview",
    prompt=video_prompt,  # Gemini-authored, references the citation visuals
    config=types.GenerateVideosConfig(
        aspect_ratio="9:16",
        reference_images=citation_refs,
        person_generation="dont_allow",
        duration_seconds="8",
    ),
)
```

### Constraints

| Constraint | Value | Impact |
|---|---|---|
| Max reference images | 3 per Veo call | Matches our top-3 bills limit |
| Duration with references | Must be 8 seconds | Acceptable — extensions add more time |
| Reference image type | `"asset"` | Preserves visual fidelity of citation card |
| Person generation | `"allow_adult"` only with references | We use `dont_allow` — **verify compatibility, may need to omit `person_generation` when using references** |

### Fallback: FFmpeg Overlay

If Veo reference images don't produce satisfactory results (citation cards not visible enough, or API constraints block it), fall back to **ffmpeg overlay compositing**:

```
ffmpeg -i veo_video.mp4 -i citation_1.png -i citation_2.png \
  -filter_complex "
    [1]scale=400:-1[c1];
    [0][c1]overlay=x=20:y=100:enable='between(t,2,5)'[tmp];
    [2]scale=400:-1[c2];
    [tmp][c2]overlay=x=20:y=100:enable='between(t,6,9)'
  " \
  -codec:a copy output.mp4
```

This inserts citation images as picture-in-picture overlays at timed intervals during narration.

---

## 5. Backend Changes

### 5.1 Contextualizer — Bill Data Integration

**File:** `backend/gemini/contextualizer.py`

| Change | Details |
|---|---|
| New function `_fetch_nearby_bills()` | Query `bills` table matching trade sector via `BILL_SECTOR_MAP`, `latest_action_date` within ±90 days of `trade_date`. Return top 3 by proximity. |
| Update `_fetch_trade_context()` | Call `_fetch_nearby_bills()` and attach to trade context dict as `nearby_bills` list |
| Update `build_initial_message()` | Add "Relevant Bills" section with bill title, policy_area, latest_action_date, URL |
| Update output schema | Add `citation_image_prompts: ["string"]` — one per relevant bill. Gemini authors the image generation prompt. |
| Update `_upsert_audit_report()` | Persist `citation_image_prompts` as JSON in new column |

### 5.2 Citation Image Generation

**File:** `backend/gemini/media_generation.py` (new function)

```python
def generate_citation_image(
    prompt: str,
    output_path: str,
    aspect_ratio: str = "16:9",
    resolution: str = "2K",
) -> dict[str, Any]:
    """Generate a bill citation card image using Nano Banana 2."""
```

- Model: `gemini-3.1-flash-image-preview` (Nano Banana 2)
- Config: `response_modalities=['IMAGE']`, configurable aspect_ratio + resolution
- Saves PNG to disk, returns `{path, file_size_bytes, resolution, provider}`
- Env: `IMAGE_GEN_PROVIDER` (`nano-banana` | `disabled`), `IMAGE_GEN_MODEL`, reuses `GEMINI_API_KEY`

### 5.3 Veo Integration Update

**File:** `backend/gemini/media_generation.py` (modify `generate_video_from_prompt`)

- New optional param: `reference_image_paths: list[str] | None`
- If provided, load images and pass as `reference_images` to Veo 3.1
- Force `duration_seconds="8"` when references are used (API requirement)

### 5.4 Pipeline Runner Update

**File:** `backend/gemini/pipeline_runner.py`

- After Stage 1 (contextualizer), add Stage 1.5:
  - For each SEVERE trade with `citation_image_prompts`:
    - Generate up to 3 citation images via `generate_citation_image()`
    - Register each in `media_assets` as `asset_type='citation_image'`
    - Collect paths for Veo reference input
- In Stage 3 (`_generate_trade_media_for_severe`):
  - Fetch citation image paths from `media_assets` for each trade
  - Pass to `generate_video_from_prompt()` as `reference_image_paths`

### 5.5 Database Migration

**File:** `backend/db/migrate_citation_images.py` (new)

```sql
ALTER TABLE audit_reports
  ADD COLUMN citation_image_prompts JSON DEFAULT NULL;
```

No schema change needed for `media_assets` — existing `asset_type` ENUM already supports extensibility. Add `'citation_image'` to the ENUM:

```sql
ALTER TABLE media_assets
  MODIFY COLUMN asset_type ENUM('audio','video','thumbnail','citation_image') NOT NULL;
```

---

## 6. Frontend Implementation Plan

### 6.0 Prerequisites

The existing `FRONTEND_UI_UX_PROMPT.md` defines the full target UI. This plan layers citation images and video integration on top of those specs. The frontend is currently minimal (home page only).

### 6.1 Page Updates for Citation Images

#### Page 1: News Feed — `/`

No citation-specific changes. Existing spec stands.

#### Page 2: Daily Report — `/daily/[date]`

| # | Addition | Description |
|---|----------|-------------|
| 2.3a | **Video player** | Unchanged — daily video may not include per-bill citations. |
| 2.5a | **Citation previews per covered trade** | Each trade card in the "Trades Covered" list (2.5) shows a small citation image thumbnail strip if citation images exist. Clicking opens the trade detail. |

#### Page 6: Trade Detail — `/trade/[id]` (Primary Changes)

This is where citation images are most visible.

| # | Section | Description |
|---|---------|-------------|
| 6.5 | **Media section** (updated) | **Video:** The Veo video now natively contains citation card visuals as reference images. Player is unchanged — the video itself is richer. |
| 6.5c | **Citation Image Gallery** (NEW) | Below the video/audio players: a horizontal scrollable gallery of citation card images (up to 3). Each card shows: bill title, policy area, action date, relationship to trade. Click to expand full-size in a modal. Long-press/right-click to download. |
| 6.7a | **Bill Citations Section** (NEW) | Within the Contextualizer Report section (6.7), after the narrative: a "Related Bills" subsection. Each bill is a card: title (linked to congress.gov URL), policy_area badge, latest_action_date, excerpt from audit_report.bill_excerpt. The corresponding citation image is inlined next to each bill card. |
| 6.6a | **Share options** (updated) | "Share Citation" button per individual citation image. Opens Twitter/X intent with the citation image as an attachment URL. Uses OG meta from A12. |

**Layout mockup for section 6.5c + 6.7a:**

```
┌─────────────────────────────────────────────────────────┐
│ 📹 Video Player (Veo video — citations baked in)        │
│ ┌─────────────────────────────────────────────────────┐ │
│ │                                                     │ │
│ │              9:16 Video with Citation               │ │
│ │              Cards Visible Inside                   │ │
│ │                                                     │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ 🔊 Audio Player                                         │
│ ────────────────●──────────────── 0:23 / 0:45           │
│                                                         │
│ ═══════════════════════════════════════════════════════  │
│                                                         │
│ 📄 Bill Citations                                       │
│                                                         │
│ ┌──────────┐  ┌──────────┐  ┌──────────┐               │
│ │ H.R.1234 │  │ S.567    │  │ H.R.890  │               │
│ │ Defense  │  │ Military │  │ Pentagon │               │
│ │ Approps  │  │ Readiness│  │ Budget   │               │
│ │ [image]  │  │ [image]  │  │ [image]  │               │
│ │ Mar 12   │  │ Mar 8    │  │ Feb 28   │               │
│ └──────────┘  └──────────┘  └──────────┘               │
│           ← scroll →                                    │
│                                                         │
│ ═══════════════════════════════════════════════════════  │
│                                                         │
│ 📝 Contextualizer Report                                │
│                                                         │
│ ▍ "Rep. Smith purchased Lockheed Martin stock 3 days    │
│ ▍  before H.R. 1234 advanced through committee..."      │
│                                                         │
│ 📜 Bill Excerpt                                         │
│ ┌─────────────────────────────────────────────────────┐ │
│ │ "Section 302(a): Authorizes $500M for advanced      │ │
│ │  missile defense systems..." — H.R. 1234            │ │
│ └─────────────────────────────────────────────────────┘ │
│                                                         │
│ ⚠️ Disclaimer                                           │
└─────────────────────────────────────────────────────────┘
```

#### Page 7: About — `/about`

| # | Addition | Description |
|---|----------|-------------|
| 7.6a | **Citation Images explanation** | Add paragraph: "Bill citation images are generated using Google's Nano Banana image model to visually summarize the legislative context of each flagged trade. These images are embedded into trade videos as reference visuals." |

### 6.2 New Components

| # | Component | Used On | Description |
|---|-----------|---------|-------------|
| C15 | `CitationImageGallery` | Page 6 | Horizontal scroll of up to 3 citation card images. Props: `images[]` (URL, bill_title, policy_area, action_date). Click → modal expand. Responsive: stack vertically on mobile. |
| C16 | `CitationCard` | Pages 2, 6 | Single citation card: thumbnail image, bill title, policy area badge, date. Compact variant for lists, expanded variant for detail page. |
| C17 | `BillExcerpt` | Page 6 | Blockquote component for bill text excerpts with source attribution link. |
| C18 | `ImageModal` | Page 6 | Full-screen image viewer. Props: `imageUrl, title, description`. Close on click-outside or Esc. Download button. |

### 6.3 OG Meta for Citation Images

The `/api/v1/share/{trade_id}` endpoint should return citation images as `og:image` candidates. For trades with citation images, use the first citation image as the OG image — it's a designed, data-rich visual that previews well on social media.

```html
<meta property="og:image" content="{first_citation_image_url}" />
<meta property="og:image:width" content="1376" />
<meta property="og:image:height" content="768" />
<meta property="og:image:alt" content="Bill citation: {bill_title}" />
```

### 6.4 Citation Image Design Language

The Nano Banana prompt for each citation image (authored by Gemini in the contextualizer) should produce images following this visual language:

- **Style:** Dark civic-tech infographic card matching the app theme (`#090d14` bg, `#e5ebf5` text)
- **Layout:** Bill title large at top, policy area badge, key excerpt or data points, trade context (politician name, ticker, date), source URL at bottom
- **Typography:** Clean sans-serif, high legibility at small sizes
- **Visual accent:** Severity quadrant color stripe (red for SEVERE)
- **Aspect ratio:** 16:9 (optimal for social share previews and horizontal scroll galleries)
- **Resolution:** 2K (1376×768)
- **Watermark:** "AI-Generated — House Advantage" small text in corner

---

## 7. API Additions

### Modified Endpoints

| Endpoint | Change |
|---|---|
| `GET /api/v1/audit/{trade_id}` | `media_assets` array now includes `asset_type='citation_image'` items. Each has `storage_url`, `generation_status`. No code change needed — existing query already returns all media_assets for the trade. |

### New Endpoints

| Method | Route | Returns | Notes |
|---|---|---|---|
| `GET` | `/api/v1/media/citation/{asset_id}` | Streams citation PNG image | Could share the existing `/api/v1/media/{asset_id}` endpoint with content-type detection |
| `GET` | `/api/v1/trade/{trade_id}/citations` | `{ trade_id, bills: [{ bill_id, title, policy_area, action_date, url, citation_image_url }] }` | Convenience endpoint for frontend citation gallery. **Needs backend.** |

### Frontend API Stubs (`lib/api.js`)

```javascript
// Add to existing api.js
export async function fetchTradeCitations(tradeId) {
  // Falls back gracefully if endpoint not yet implemented
  try {
    const res = await fetch(`${API_BASE}/api/v1/trade/${tradeId}/citations`);
    if (!res.ok) return { trade_id: tradeId, bills: [] };
    return res.json();
  } catch {
    return { trade_id: tradeId, bills: [] };
  }
}
```

---

## 8. Implementation Phases

### Phase 1: Bill Data Integration (Backend Only)

| # | Task | File(s) | Dependencies |
|---|------|---------|--------------|
| 1.1 | Add `_fetch_nearby_bills()` to contextualizer | `contextualizer.py` | None |
| 1.2 | Update `build_initial_message()` with bill section | `contextualizer.py` | 1.1 |
| 1.3 | Add `citation_image_prompts` to output schema + upsert | `contextualizer.py` | 1.2 |
| 1.4 | DB migration: `citation_image_prompts` column + `citation_image` ENUM value | `migrate_citation_images.py` | None (parallel) |

### Phase 2: Nano Banana Image Generation (Backend Only)

| # | Task | File(s) | Dependencies |
|---|------|---------|--------------|
| 2.1 | Add `generate_citation_image()` function | `media_generation.py` | 1.4 |
| 2.2 | Add env config (`IMAGE_GEN_PROVIDER`, `IMAGE_GEN_MODEL`) | `media_generation.py` | None (parallel) |
| 2.3 | Integrate Stage 1.5 into pipeline_runner | `pipeline_runner.py` | 2.1, 1.3 |
| 2.4 | Test: generate citation images for a SEVERE trade | Manual | 2.3 |

### Phase 3: Veo Reference Image Integration (Backend Only)

| # | Task | File(s) | Dependencies |
|---|------|---------|--------------|
| 3.1 | Update `generate_video_from_prompt()` to accept `reference_image_paths` | `media_generation.py` | 2.1 |
| 3.2 | Update `_generate_trade_media_for_severe()` to fetch + pass citation images to Veo | `pipeline_runner.py` | 3.1, 2.3 |
| 3.3 | Add FFmpeg overlay fallback if Veo references fail | `ffmpeg_assembly.py` | 3.2 |
| 3.4 | End-to-end test: full pipeline produces video with visible citation cards | Manual | 3.2 |

### Phase 4: Core Frontend (No Citations Yet)

Build the base pages per `FRONTEND_UI_UX_PROMPT.md`:

| # | Task | Priority |
|---|------|----------|
| 4.1 | `/` refactor: NavBar, TradeCards, SystemicBanner, clickable rows | High |
| 4.2 | `/politician/[id]` profile + trade table | High |
| 4.3 | `/trade/[id]` detail with audit report + media players | High |
| 4.4 | `/politicians` index, `/trades` filterable index | Medium |
| 4.5 | `/daily/[date]` daily report page | Medium |
| 4.6 | `/about` static page | Low |

### Phase 5: Citation Image Frontend

| # | Task | File(s) | Dependencies |
|---|------|---------|--------------|
| 5.1 | Build `CitationCard` component | `app/components/CitationCard.js` | 4.3 |
| 5.2 | Build `CitationImageGallery` component | `app/components/CitationImageGallery.js` | 5.1 |
| 5.3 | Build `ImageModal` component | `app/components/ImageModal.js` | 5.2 |
| 5.4 | Build `BillExcerpt` component | `app/components/BillExcerpt.js` | 4.3 |
| 5.5 | Integrate citation gallery into `/trade/[id]` page (section 6.5c) | `app/trade/[id]/page.js` | 5.2, 5.3 |
| 5.6 | Integrate bill citations into contextualizer report (section 6.7a) | `app/trade/[id]/page.js` | 5.1, 5.4 |
| 5.7 | Add `fetchTradeCitations()` to `lib/api.js` | `lib/api.js` | None (parallel) |
| 5.8 | OG meta with citation images | `app/trade/[id]/page.js` | 5.5 |
| 5.9 | Update `/about` with citation explanation | `app/about/page.js` | 4.6 |

### Phase 6: Polish & Testing

| # | Task |
|---|------|
| 6.1 | Unit tests: `_fetch_nearby_bills()`, `generate_citation_image()` |
| 6.2 | Integration test: full pipeline → video contains visible citations |
| 6.3 | Frontend: responsive testing (mobile citation gallery, video player) |
| 6.4 | Social share testing: OG meta with citation images on Twitter/X, Discord |
| 6.5 | Performance: ensure citation image gen doesn't bottleneck the nightly pipeline |

---

## Decisions Log

| Decision | Choice | Rationale |
|---|---|---|
| How images enter video | Veo 3.1 `reference_images` (native) | API-supported, no manual compositing. Veo preserves reference image visuals. Up to 3 images aligns with top-3 bills limit. |
| Fallback if references fail | FFmpeg picture-in-picture overlay | Deterministic, proven. Citation images appear as timed overlays during narration. |
| Image model | Nano Banana 2 (`gemini-3.1-flash-image-preview`) | Speed/cost optimized for high-volume. Citation cards are data-driven, not artistically complex. |
| Image aspect ratio | 16:9 landscape | Optimal for OG social previews and horizontal gallery scroll. Readable at thumbnail size. |
| Citation count per trade | Up to 3 | Matches Veo 3.1's reference image limit. Top 3 most proximate sector-matched bills. |
| Image prompt authoring | Gemini (in contextualizer) | Gemini tailors each prompt to the specific bill + trade context, matching how `video_prompt` is already authored. |
| Standalone display | Yes — gallery on trade page + OG meta | Citations are independently valuable for social sharing even without the video. |
| `person_generation` with references | Requires `"allow_adult"` per Veo docs | Our V3 spec says `dont_allow` — need to verify if this blocks reference images. If so, omit the param and rely on Gemini's prompt to exclude faces. |
| Duration with references | Fixed at 8 seconds | Veo API requires `"8"` when using references. Extensions add length. |
| Bill data scope | Metadata only (title, policy_area, action_date, URL) | Full bill text (50k-200k tokens) is a future enhancement. Metadata satisfies citation and prompt needs. |
