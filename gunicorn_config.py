"""
Gunicorn config. Ensures the evaluation worker thread is started in each
worker process (post_fork). With --workers 2, two processes each run one
worker thread that polls the SQLite job queue.

when_ready hook runs a post-deploy smoke test against localhost once the
server is accepting connections.
"""

import logging
import os
import threading


def when_ready(server):
    """Run smoke test in a background thread once gunicorn is listening."""
    port = os.environ.get("PORT", "8000")
    base_url = f"http://127.0.0.1:{port}"

    def _run_smoke():
        import time
        time.sleep(2)  # brief grace period for workers to finish forking
        logger = logging.getLogger("gunicorn.error")
        try:
            from smoke_test import run_tests
            logger.info("Post-deploy smoke test starting against %s", base_url)
            ok = run_tests(base_url)
            if ok:
                logger.info("Post-deploy smoke test PASSED")
            else:
                logger.error("Post-deploy smoke test FAILED")
        except Exception:
            logger.exception("Post-deploy smoke test crashed")

    t = threading.Thread(target=_run_smoke, daemon=True)
    t.start()


def post_fork(server, worker):
    """Start the async evaluation worker and health monitor in this gunicorn worker process."""
    try:
        from worker import start_worker
        start_worker()
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to start evaluation worker: %s", e)
    try:
        from health_monitor import start_monitor
        start_monitor()
    except Exception as e:
        import logging
        logging.getLogger(__name__).exception("Failed to start health monitor: %s", e)
