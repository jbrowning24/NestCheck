web: echo "PWD=$PWD" && ls -la gunicorn_config.py 2>&1 && gunicorn app:app -c gunicorn_config.py --bind 0.0.0.0:$PORT
