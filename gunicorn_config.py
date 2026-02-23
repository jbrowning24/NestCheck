"""
Gunicorn config. Ensures the evaluation worker thread is started in each
worker process (post_fork). With --workers 2, two processes each run one
worker thread that polls the SQLite job queue.
"""

import os


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
