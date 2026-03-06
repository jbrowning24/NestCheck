# NestCheck Ground Truth Audit
Generated: 2026-03-01 15:53

## Files Read (Pipeline Understanding)
- property_evaluator.py — evaluate_property(), present_checks(), Tier 1 checks
- green_space.py — Green Escape scoring engine
- urban_access.py — Urban Access / transit scoring
- app.py — /evaluate flow, result_to_dict, debug_eval
- models.py — snapshot structure

## Method Used
Direct function call: evaluate_property() + result_to_dict() with TraceContext

## Evaluations Summary
- Completed: 4/4
- Failed: None

---
## Address: 620 W 143rd Street, New York, NY 10031

**Geocode result:** [40.8256138, -73.95284970000002]
**Evaluation time:** 102.14 seconds
**Any errors or exceptions:** None

### Tier 1 Safety Checks
- **Gas station:** PASS
  - Details: No gas stations within 500 feet
- **High-traffic road:** WARNING
  - Details: 100503011: 147,226 vehicles/day, 504 ft away
  - Raw value: {'aadt': 147226, 'distance_ft': 504, 'road_name': '100503011', 'radius_m': 153.7}
- **Power lines:** PASS
  - Details: No high-voltage transmission lines detected within 200 ft
- **Electrical substation:** WARNING
  - Details: Electrical substation detected within 185 ft. Substations concentrate electromagnetic fields from the surrounding transmission network.
  - Raw value: 185
- **Cell tower:** PASS
  - Details: No cell towers detected within 500 ft
- **Industrial zone:** PASS
  - Details: No industrial-zoned land detected within 500 ft
- **Flood zone:** UNKNOWN
  - Details: Flood zone data not available for this area
- **Superfund (NPL):** UNKNOWN
  - Details: Superfund site data not available for this area
- **W/D in unit:** UNKNOWN
  - Details: Not specified - verify manually
- **Central air:** UNKNOWN
  - Details: Not specified - verify manually
- **Size:** UNKNOWN
  - Details: Square footage not specified
- **Bedrooms:** UNKNOWN
  - Details: Bedroom count not specified
- **Cost:** UNKNOWN
  - Details: Monthly cost not specified

### Tier 2 Scores
- **Primary Green Escape:** 9/10 — Riverbank State Park (4.6★, 4412 reviews) — 7 min walk — Daily Value 8.8/10 [PASS]
- **Third Place:** 10/10 — Matto Espresso (4.6★, 446 reviews) — 2 min walk
- **Provisioning:** 7/10 — Foodtown of St. Nicholas Ave (4.1★, 1229 reviews) — 16 min walk
- **Fitness access:** 10/10 — UpDog Studios (4.8★) — 8 min walk
- **Cost:** 0/10 — Monthly cost not specified
- **Urban access:** 10/10 — 145 St — 4 min walk | Service: High frequency | Hub: Grand Central Terminal — 28 min

### Tier 3 Bonuses
- (None)

### Insight Layer
- (Insights not populated in result_dict)

### API Call Summary
- google_maps: 316
- overpass: 7
- spatial: 1
- Total API calls: 324


---
## Address: 152 W 128TH ST, NEW YORK, NY 10027

**Geocode result:** [40.8103264, -73.94605270000001]
**Evaluation time:** 93.01 seconds
**Any errors or exceptions:** None

### Tier 1 Safety Checks
- **Gas station:** PASS
  - Details: No gas stations within 500 feet
- **High-traffic road:** PASS
  - Details: No high-traffic roads within 1,000 ft
- **Power lines:** UNKNOWN
  - Details: Unable to query environmental data
- **Electrical substation:** UNKNOWN
  - Details: Unable to query environmental data
- **Cell tower:** UNKNOWN
  - Details: Unable to query environmental data
- **Industrial zone:** UNKNOWN
  - Details: Unable to query environmental data
- **Flood zone:** UNKNOWN
  - Details: Flood zone data not available for this area
- **Superfund (NPL):** UNKNOWN
  - Details: Superfund site data not available for this area
- **W/D in unit:** UNKNOWN
  - Details: Not specified - verify manually
- **Central air:** UNKNOWN
  - Details: Not specified - verify manually
- **Size:** UNKNOWN
  - Details: Square footage not specified
- **Bedrooms:** UNKNOWN
  - Details: Bedroom count not specified
- **Cost:** UNKNOWN
  - Details: Monthly cost not specified

### Tier 2 Scores
- **Primary Green Escape:** 8/10 — Morningside Park (4.5★, 4458 reviews) — 23 min walk — Daily Value 8.2/10 [PASS]
- **Third Place:** 10/10 — PROOF Coffee Roasters (4.6★, 300 reviews) — 8 min walk
- **Provisioning:** 10/10 — Whole Foods Market (4.2★, 4708 reviews) — 6 min walk
- **Fitness access:** 10/10 — Harlem Holistic Center (5★) — 3 min walk
- **Cost:** 0/10 — Monthly cost not specified
- **Urban access:** 10/10 — 125 St — 5 min walk | Service: High frequency | Hub: Grand Central Terminal — 17 min

### Tier 3 Bonuses
- (None)

### Insight Layer
- (Insights not populated in result_dict)

### API Call Summary
- google_maps: 339
- overpass: 5
- spatial: 1
- Total API calls: 345


---
## Address: 315 W 91st Street, New York, NY 10024

**Geocode result:** [40.7926537, -73.9764319]
**Evaluation time:** 94.1 seconds
**Any errors or exceptions:** None

### Tier 1 Safety Checks
- **Gas station:** PASS
  - Details: Nearest: Mobil (1,335 ft)
  - Raw value: 1335
- **High-traffic road:** WARNING
  - Details: 100503011: 130,871 vehicles/day, 809 ft away
  - Raw value: {'aadt': 130871, 'distance_ft': 809, 'road_name': '100503011', 'radius_m': 246.7}
- **Power lines:** PASS
  - Details: No high-voltage transmission lines detected within 200 ft
- **Electrical substation:** PASS
  - Details: No electrical substations detected within 300 ft
- **Cell tower:** PASS
  - Details: No cell towers detected within 500 ft
- **Industrial zone:** PASS
  - Details: No industrial-zoned land detected within 500 ft
- **Flood zone:** UNKNOWN
  - Details: Flood zone data not available for this area
- **Superfund (NPL):** UNKNOWN
  - Details: Superfund site data not available for this area
- **W/D in unit:** UNKNOWN
  - Details: Not specified - verify manually
- **Central air:** UNKNOWN
  - Details: Not specified - verify manually
- **Size:** UNKNOWN
  - Details: Square footage not specified
- **Bedrooms:** UNKNOWN
  - Details: Bedroom count not specified
- **Cost:** UNKNOWN
  - Details: Monthly cost not specified

### Tier 2 Scores
- **Primary Green Escape:** 9/10 — Hudson River Waterfront Greenway (4.8★, 169 reviews) — 10 min walk — Daily Value 9.0/10 [PASS]
- **Third Place:** 10/10 — French Roast (4.7★, 3954 reviews) — 10 min walk
- **Provisioning:** 7/10 — Whole Foods Market (4.2★, 2913 reviews) — 17 min walk
- **Fitness access:** 10/10 — Mind Over Matter Health & Fitness (5★) — 14 min walk
- **Cost:** 0/10 — Monthly cost not specified
- **Urban access:** 10/10 — 96 St — 8 min walk | Service: High frequency | Hub: Grand Central Terminal — 17 min

### Tier 3 Bonuses
- (None)

### Insight Layer
- (Insights not populated in result_dict)

### API Call Summary
- google_maps: 388
- overpass: 6
- spatial: 1
- Total API calls: 395


---
## Address: 35565 Vicksburg, Farmington Hills, MI 48331

**Geocode result:** [42.5011531, -83.4003601]
**Evaluation time:** 83.36 seconds
**Any errors or exceptions:** None

### Tier 1 Safety Checks
- **Gas station:** PASS
  - Details: No gas stations within 500 feet
- **High-traffic road:** PASS
  - Details: No high-traffic roads within 1,000 ft
- **Power lines:** PASS
  - Details: No high-voltage transmission lines detected within 200 ft
- **Electrical substation:** PASS
  - Details: No electrical substations detected within 300 ft
- **Cell tower:** PASS
  - Details: No cell towers detected within 500 ft
- **Industrial zone:** PASS
  - Details: No industrial-zoned land detected within 500 ft
- **Flood zone:** UNKNOWN
  - Details: Flood zone data not available for this area
- **Superfund (NPL):** UNKNOWN
  - Details: Superfund site data not available for this area
- **W/D in unit:** UNKNOWN
  - Details: Not specified - verify manually
- **Central air:** UNKNOWN
  - Details: Not specified - verify manually
- **Size:** UNKNOWN
  - Details: Square footage not specified
- **Bedrooms:** UNKNOWN
  - Details: Bedroom count not specified
- **Cost:** UNKNOWN
  - Details: Monthly cost not specified

### Tier 2 Scores
- **Primary Green Escape:** 5/10 — De Orr Island (5.0★, 2 reviews) — 29 min walk — Daily Value 5.2/10 [PASS]
- **Third Place:** 0/10 — No high-quality third places within walking distance
- **Provisioning:** 2/10 — Al-Haramain International Foods (4.3★, 1176 reviews) — 33 min walk
- **Fitness access:** 3/10 — Anytime Fitness (4.8★) — 29 min walk
- **Cost:** 0/10 — Monthly cost not specified
- **Urban access:** 0/10 — No rail transit stations found within reach

### Tier 3 Bonuses
- (None)

### Insight Layer
- (Insights not populated in result_dict)

### API Call Summary
- google_maps: 137
- overpass: 8
- spatial: 1
- Total API calls: 146


---
## Summary Table

| Check / Dimension | 620 W 143rd | 152 W 128th | 315 W 91st | 35565 Vicksburg |
|-------------------|-------------|-------------|------------|------------------|
| Bedrooms | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Cell tower | PASS | UNKNOWN | PASS | PASS |
| Central air | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Cost | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Electrical substation | WARNING | UNKNOWN | PASS | PASS |
| Flood zone | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Gas station | PASS | PASS | PASS | PASS |
| High-traffic road | WARNING | PASS | WARNING | PASS |
| Industrial zone | PASS | UNKNOWN | PASS | PASS |
| Power lines | PASS | UNKNOWN | PASS | PASS |
| Size | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Superfund (NPL) | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| W/D in unit | UNKNOWN | UNKNOWN | UNKNOWN | UNKNOWN |
| Cost | 0/10 | 0/10 | 0/10 | 0/10 |
| Fitness access | 10/10 | 10/10 | 10/10 | 3/10 |
| Primary Green Escape | 9/10 | 8/10 | 9/10 | 5/10 |
| Provisioning | 7/10 | 10/10 | 7/10 | 2/10 |
| Third Place | 10/10 | 10/10 | 10/10 | 0/10 |
| Urban access | 10/10 | 10/10 | 10/10 | 0/10 |
| Total API Calls | 324 | 345 | 395 | 146 |
| Eval Time (sec) | 102.14 | 93.01 | 94.1 | 83.36 |

---
## Suspicious Items / Flags

### Observed During Audit

1. **EJScreen table missing:** `Spatial query failed for ejscreen: no such table: facilities_ejscreen` — affects all 4 addresses. EJScreen block group indicators return UNKNOWN; Superfund NPL and Flood zone checks also UNKNOWN for these areas (may be data coverage, not just missing table).

2. **Overpass rate limiting:** Rate limit hit during green_escape batch enrichment (audit-1: chunk 3; audit-4: multiple 429s with retries). Some park OSM enrichment skipped for 5 places at 620 W 143rd. Farmington Hills had several Overpass 429s before success.

3. **Environmental hazard UNKNOWN at 152 W 128th:** Power lines, substations, cell towers, industrial zone all UNKNOWN with "Unable to query environmental data" — suggests Overpass or HIFLD query failed for this specific location while other Manhattan addresses returned PASS.

4. **High-traffic road ID 100503011:** Same road segment ID appears for both 620 W 143rd (504 ft, 147K AADT) and 315 W 91st (809 ft, 130K AADT). Likely Henry Hudson Parkway / West Side Highway. Distance bands (WARNING vs WARNING) seem reasonable; 504 ft is within 150–300m elevated-risk zone.

5. **Electrical substation WARNING at 620 W 143rd:** 185 ft from a substation. Verdict: plausible — Harlem has Con Ed infrastructure; worth manual verification via satellite.

6. **35565 Vicksburg — "De Orr Island" as best park:** 5.0★ with only 2 reviews, 29 min walk. May be a misclassified or tiny/non-park place; low review count makes quality proxy unreliable.

7. **API call variance:** 324–395 calls for Manhattan addresses vs 146 for Farmington Hills — reflects fewer transit nodes, fewer green spaces, and less Overpass data in suburban context. Not necessarily redundant.

### Manual Review Recommendations

- Gas station flags in residential areas with no visible gas station
- Missing highway/high-traffic flags near known major roads
- Manhattan addresses scoring low on transit (none observed — all 10/10)
- Suburban addresses scoring high on walkability (none observed — Farmington Hills correctly low)
- Dimensions returning None or empty data (Cost 0/10 for all — expected when no listing data)
- Redundant or excessive API calls

---
## STATUS REPORT

- **Files read:** property_evaluator.py, green_space.py, urban_access.py, app.py, models.py
- **Method used to run evaluations:** Direct function call — `evaluate_property()` + `result_to_dict()` with TraceContext (via `scripts/run_ground_truth_audit.py`)
- **Evaluations completed:** 4/4
- **Evaluations failed:** None
- **Output file:** `ground_truth_audit_20260301.md` (project root)
