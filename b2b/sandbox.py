"""Sandbox address mapping and snapshot replay for B2B test keys.

Sandbox keys return pre-computed evaluation snapshots instead of running
real evaluations. Zero API cost, deterministic responses.

TODO: Populate SANDBOX_ADDRESSES with real snapshot IDs after running
evaluations for these test addresses.
"""

# Map of normalized addresses -> snapshot IDs.
# Keys should be lowercase, stripped.
SANDBOX_ADDRESSES: dict[str, str] = {
    # Westchester
    # "10 main street, white plains, ny 10601": "snapshot_id_here",
    # DMV
    # "1600 pennsylvania ave nw, washington, dc 20500": "snapshot_id_here",
}

# Fallback snapshot when no address matches.
DEFAULT_SANDBOX_SNAPSHOT: str | None = None


def get_sandbox_snapshot_id(address: str) -> str | None:
    """Look up a sandbox snapshot for the given address.

    Returns snapshot_id if found, DEFAULT_SANDBOX_SNAPSHOT otherwise.
    """
    normalized = address.strip().lower()
    return SANDBOX_ADDRESSES.get(normalized, DEFAULT_SANDBOX_SNAPSHOT)
