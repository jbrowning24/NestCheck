# NES-105 Phase 2: Road Noise Integration Plan

**Overall Progress:** `100%`

## TLDR

Wire `road_noise.py` into the evaluation pipeline as a 6th Tier 2 scored dimension. One new Overpass query per evaluation (cached 7 days). Zero new Google Maps API calls.

## Critical Decisions

- Decision 1: Subtractive scoring — higher dBA → lower score, via piecewise curve calibrated to FHWA/WHO thresholds
- Decision 2: `None` fallback score of 7/10 when Overpass unavailable — benefit of the doubt
- Decision 3: Tier 2 max increases from 50 to 60 — normalization auto-adjusts, each dimension's influence drops from 20% to 16.7%
- Decision 4: Severity maps to existing CSS proximity classes — no new CSS needed

## Tasks

- [x] 🟩 **1. Add `road_noise_assessment` field to `EvaluationResult`** · _property_evaluator.py_
  - [x] 🟩 1.1 Add import for `road_noise` module
  - [x] 🟩 1.2 Add `road_noise_assessment: Optional[RoadNoiseAssessment] = None` field

- [x] 🟩 **2. Add parallel data-collection stage** · _property_evaluator.py_
  - [x] 🟩 2.1 Add `road_noise` future in ThreadPoolExecutor block
  - [x] 🟩 2.2 Add result handler in futures collection loop
  - [x] 🟩 2.3 Bump max_workers from 7 to 8

- [x] 🟩 **3. Add scoring function `score_road_noise()`** · _property_evaluator.py_
  - [x] 🟩 3.1 Implement function with piecewise curve evaluation

- [x] 🟩 **4. Add `road_noise` DimensionConfig to ScoringModel** · _scoring_config.py_
  - [x] 🟩 4.1 Add `road_noise` field to ScoringModel dataclass
  - [x] 🟩 4.2 Add knots and config to SCORING_MODEL instance
  - [x] 🟩 4.3 Bump model version to 1.2.0

- [x] 🟩 **5. Wire scoring into Tier 2 sequence** · _property_evaluator.py_
  - [x] 🟩 5.1 Add `score_road_noise` call in evaluate_property()

- [x] 🟩 **6. Serialize road noise into snapshots** · _app.py_
  - [x] 🟩 6.1 Add `_serialize_road_noise()` helper and wire into `result_to_dict()`
  - [x] 🟩 6.2 Backward compat: `getattr` fallback + `is defined` template guard

- [x] 🟩 **7. Presentation card in Proximity & Environment** · _templates/_result_sections.html_
  - [x] 🟩 7.1 Add road noise card with severity-based styling
  - [x] 🟩 7.2 Add expandable methodology footnote

- [x] 🟩 **8. Update "How We Score" text** · _templates/_result_sections.html_
  - [x] 🟩 8.1 Update factor count from five to six
  - [x] 🟩 8.2 Update proximity disclaimer to reflect road noise scoring
