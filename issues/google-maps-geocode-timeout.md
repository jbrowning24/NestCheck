# Google Maps geocode calls time out intermittently

**Type:** bug  
**Priority:** normal  
**Effort:** medium  

---

## TL;DR

Geocode requests to the Google Maps API sometimes hang or time out with no timeout or retry, causing evaluation runs to stall or fail intermittently.

---

## Current state

- Geocode (and other `GoogleMapsClient` calls) use `self.session.get(url, params=params)` with **no timeout**.
- When the Maps API is slow or unresponsive, the request can hang indefinitely.
- Failures are intermittent, so runs sometimes complete and sometimes stall.

## Expected outcome

- Geocode (and related Maps API) calls complete or fail in a predictable time.
- Optional: retry with backoff on transient timeouts so runs are more resilient.

---

## Relevant files

- `property_evaluator.py` — `GoogleMapsClient` (e.g. `geocode()` ~L300, `places_nearby`, `place_details`, etc.): add `timeout` to all `session.get()` calls; consider retries for 5xx/timeouts.

---

## Notes / risk

- Other `session.get()` usages in this client (Places, Distance Matrix, etc.) also have no timeout; fix consistently.
- Adding a single timeout (e.g. 15–30s) is low risk; retries need care to avoid rate limits (consider exponential backoff and max attempts).
- If the key has strict quotas, timeouts might be quota-related; document that in a comment or README.

---

## Linear

**Add to Linear:** [Open in Linear (linear.new)](https://linear.new?title=Google+Maps+geocode+calls+time+out+intermittently&description=**Type:**+bug+%7C+**Priority:**+normal+%7C+**Effort:**+medium%0A%0A**TL;DR**%0AGeocode+requests+to+the+Google+Maps+API+sometimes+hang+or+time+out+with+no+timeout+or+retry%2C+causing+evaluation+runs+to+stall+or+fail+intermittently.%0A%0A**Current+state**%0A-+Geocode+%28and+other+GoogleMapsClient+calls%29+use+session.get%28%29+with+no+timeout.%0A-+When+the+Maps+API+is+slow%2C+requests+can+hang+indefinitely.%0A-+Failures+are+intermittent.%0A%0A**Expected**%0A-+Geocode+%2F+Maps+API+calls+complete+or+fail+in+predictable+time.%0A-+Optional%3A+retry+with+backoff+on+transient+timeouts.%0A%0A**Relevant+files**%0A-+property_evaluator.py+%E2%80%94+GoogleMapsClient%3A+add+timeout+to+all+session.get%28%29%3B+consider+retries+for+5xx%2Ftimeouts.%0A%0A**Notes**%0A-+Fix+all+Maps+session.get+calls+consistently.+Retries%3A+exponential+backoff%2C+max+attempts.+Document+if+quota-related.&priority=medium)
