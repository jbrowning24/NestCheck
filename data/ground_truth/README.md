# Ground Truth Files

Deterministic ground-truth datasets for scoring calibration. Each file contains synthetic test points generated from real spatial data (spatial.db) at controlled distances from known facilities/segments.

## Files

| File | Dimension | Generator | Test points |
|------|-----------|-----------|-------------|
| `ust.json` | UST proximity (gas stations/tanks) | `scripts/generate_ground_truth_ust.py` | 150 (3 per facility × 50 facilities) |
| `hpms.json` | HPMS high-traffic roads | `scripts/generate_ground_truth_hpms.py` | 100 (3 per high-traffic + 1 per low-traffic × 25 each) |

## How they were generated

```bash
python scripts/generate_ground_truth_ust.py --count 50 --seed 42 --output data/ground_truth/ust.json
python scripts/generate_ground_truth_hpms.py --count 25 --seed 42 --output data/ground_truth/hpms.json
```

Seed 42 ensures deterministic output. The files only change when explicitly re-generated.

## When to regenerate

- After changing buffer distances or threshold constants in `property_evaluator.py`
- After adding new data sources to spatial.db (new facilities shift nearest-neighbor results)
- After expanding geographic coverage (new states, wider bounding boxes)
- After fixing bugs in the generator scripts themselves

Re-generate with the same seed to maintain reproducibility, or choose a new seed if you want a different sample.

## How to validate

Run all validators at once:

```bash
python scripts/validate_all_ground_truth.py
python scripts/validate_all_ground_truth.py --verbose
python scripts/validate_all_ground_truth.py --dimension ust
```

Or run individual validators:

```bash
python scripts/validate_ground_truth_ust.py --input data/ground_truth/ust.json
python scripts/validate_ground_truth_hpms.py --input data/ground_truth/hpms.json
```

Exit code 0 = all tests match. Exit code 1 = mismatches or errors.
