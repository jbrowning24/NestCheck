"""Pre-flight checks before gunicorn starts.

Run spatial data ingestion in the master process BEFORE forking
workers. This avoids macOS fork-safety crashes (NSCFConstantString)
that occur when HTTP requests are made in forked child processes.
"""

import logging
import os
import sys

# Ensure project root is on the Python path so we can import
# startup_ingest and scripts.ingest_* modules.
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)


def main() -> int:
    try:
        from startup_ingest import ensure_spatial_data

        ensure_spatial_data()
        return 0
    except Exception as e:
        logging.getLogger("nestcheck.preflight").error(
            "Preflight spatial ingestion failed: %s", e
        )
        return 0


if __name__ == "__main__":
    sys.exit(main())
