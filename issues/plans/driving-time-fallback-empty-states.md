# Driving Time Fallback + Context-Aware Empty States

## Phase 1: Add driving times to existing far results (walk_time > 20 min)
- [x] ✅ 1. `score_third_place_access()` — add driving times for far coffee places
- [x] ✅ 2. `score_provisioning_access()` — add driving times for far grocery places
- [x] ✅ 3. `score_fitness_access()` — add driving times for far fitness places
- [x] ✅ 4. `get_pharmacy_proximity()` — add driving times for far pharmacies
- [x] ✅ 5. Template — conditional walk/drive display (≤20 walk, 21-40 both, >40 drive only)

## Phase 2: Wider-radius search for empty categories
- [x] ✅ 6. `score_third_place_access()` — expanded 15km search when empty
- [x] ✅ 7. `score_provisioning_access()` — expanded 15km search when empty
- [x] ✅ 8. `score_fitness_access()` — expanded 15km search when empty
- [x] ✅ 9. Template — "Nearest by car" display for expanded results
- [x] ✅ 10. Template — "No [category] found within ~10 miles" for still-empty

**Progress: 100%**
