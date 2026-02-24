# NES-119: Atomic Payment Redemption + Job Creation

**Overall Progress:** `100%`

## TLDR
Payment redemption and job creation happened in two separate DB calls with no transaction wrapping them. If the server crashed between `redeem_payment()` and `create_job()`, the user's payment was consumed but no evaluation job existed. Fixed by creating the job first, then redeeming the payment with the job_id in one atomic step.

## Critical Decisions
- **Create job first, then redeem with job_id:** This is the safer ordering — a job with no payment is harmless (worker runs it anyway), but a redeemed payment with no job is a lost credit. By creating the job first and passing the job_id into `redeem_payment()`, the payment row always has its job_id set atomically at redemption time.
- **Remove `update_payment_job_id()` call from app.py:** The separate `update_payment_job_id()` became unnecessary since `redeem_payment()` already sets `job_id` atomically.
- **Fail orphaned job on redemption failure:** If `redeem_payment()` returns False (double-redeem), the already-created job is marked as failed so the worker doesn't run a free evaluation.

## Tasks:

- [x] 🟩 **Step 1: Reorder operations in `app.py` POST handler**
  - [x] 🟩 Moved `create_job()` call to before `redeem_payment()`
  - [x] 🟩 Pass the `job_id` into `redeem_payment(payment["id"], job_id=job_id)`
  - [x] 🟩 Removed the separate `update_payment_job_id()` call
  - [x] 🟩 Added `fail_job` to imports, removed unused `update_payment_job_id` import

- [x] 🟩 **Step 2: Handle orphaned job on redemption failure**
  - [x] 🟩 After `redeem_payment()` returns False, call `fail_job(job_id, "payment_already_used")` to prevent free evaluation

- [x] 🟩 **Step 3: Verify and test**
  - [x] 🟩 All 37 payment tests pass
