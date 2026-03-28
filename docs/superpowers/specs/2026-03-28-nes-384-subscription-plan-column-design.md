# NES-384: Add plan column to subscriptions table

## Summary

Add a `plan` TEXT column to the `subscriptions` table to track subscription tier. Populate from Stripe webhook data by mapping the subscription's price ID to a plan name via a config dict.

## Design

### Schema

Add `plan TEXT` (nullable) to `subscriptions`. Migration via `PRAGMA table_info` + `ALTER TABLE ADD COLUMN` guard.

### Plan resolution

`_STRIPE_PLAN_MAP` in `app.py` maps price IDs to plan names (`{STRIPE_SUBSCRIPTION_PRICE_ID: "30d"}`). Extracted from `sub_obj["items"]["data"][0]["price"]["id"]` in the webhook. Unknown IDs resolve to `None`.

### Model changes

- `create_subscription()`: add `plan: str | None = None`, wire into INSERT
- `update_subscription_status()`: add optional `plan` param for price-change events

### Webhook changes

`_handle_subscription_event()`: extract plan on "created" and "updated" events.

### Tests

Add `plan` to post-migration assertions in `test_schema_migration.py`.

## Not in scope

UI, access control, pricing page, backfill, multi-tier pricing.
