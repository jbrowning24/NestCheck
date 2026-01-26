#!/usr/bin/env python3
"""
Start NestCheck with a public URL for mobile testing.

SETUP (one-time):
    1. Sign up for free at: https://dashboard.ngrok.com/signup
    2. Get your authtoken from: https://dashboard.ngrok.com/get-started/your-authtoken
    3. Set it as an environment variable:
       export NGROK_AUTHTOKEN="your-token-here"

    Or add it to your .env file:
       NGROK_AUTHTOKEN=your-token-here

USAGE:
    python start_mobile_test.py

Your URL will be permanent and shown in the ngrok dashboard.
"""

import subprocess
import sys
import os
import time
import signal
import atexit

# Configuration
PORT = 5001

flask_process = None
ngrok_tunnel = None


def check_authtoken():
    """Check that ngrok authtoken is configured."""
    # Try loading from .env file first
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    token = os.environ.get("NGROK_AUTHTOKEN")
    if not token:
        print("=" * 60)
        print("NGROK SETUP REQUIRED")
        print("=" * 60)
        print("\n1. Sign up for FREE at:")
        print("   https://dashboard.ngrok.com/signup")
        print("\n2. Get your authtoken from:")
        print("   https://dashboard.ngrok.com/get-started/your-authtoken")
        print("\n3. Set it as an environment variable:")
        print('   export NGROK_AUTHTOKEN="your-token-here"')
        print("\n   Or add to your .env file:")
        print("   NGROK_AUTHTOKEN=your-token-here")
        print("\n" + "=" * 60)
        sys.exit(1)

    return token


def install_pyngrok():
    """Install pyngrok if not present."""
    try:
        import pyngrok
        return True
    except ImportError:
        print("Installing pyngrok...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyngrok", "-q"])
        return True


def start_flask():
    """Start the Flask server."""
    global flask_process
    print(f"Starting NestCheck on port {PORT}...")
    flask_process = subprocess.Popen(
        [sys.executable, "app.py"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )
    time.sleep(2)
    print("Flask server started.\n")
    return flask_process


def start_ngrok(authtoken):
    """Start ngrok tunnel."""
    global ngrok_tunnel

    from pyngrok import ngrok, conf

    # Kill any existing ngrok processes first
    ngrok.kill()

    # Set authtoken
    conf.get_default().auth_token = authtoken

    print(f"Creating ngrok tunnel to port {PORT}...")

    # Open HTTP tunnel - explicitly bind to localhost:PORT
    ngrok_tunnel = ngrok.connect(
        addr=f"http://localhost:{PORT}",
        proto="http",
        bind_tls=True
    )

    public_url = ngrok_tunnel.public_url

    print("\n" + "=" * 60)
    print("YOUR MOBILE TESTING URL:")
    print(f"\n    {public_url}\n")
    print("Open this URL on your iPhone to test NestCheck!")
    print("\nThis URL is stable for this session.")
    print("View all your URLs at: https://dashboard.ngrok.com/endpoints")
    print("=" * 60 + "\n")
    print("Press Ctrl+C to stop the server.\n")

    return ngrok_tunnel


def cleanup(signum=None, frame=None):
    """Clean up processes on exit."""
    print("\nShutting down...")

    # Close ngrok tunnel
    if ngrok_tunnel:
        try:
            from pyngrok import ngrok
            ngrok.disconnect(ngrok_tunnel.public_url)
            ngrok.kill()
        except:
            pass

    # Stop Flask
    if flask_process:
        flask_process.terminate()
        try:
            flask_process.wait(timeout=5)
        except:
            flask_process.kill()

    print("Goodbye!")
    sys.exit(0)


def main():
    # Set up signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)
    atexit.register(cleanup)

    print("=" * 60)
    print("NestCheck Mobile Testing Server")
    print("=" * 60 + "\n")

    # Check for authtoken
    authtoken = check_authtoken()

    # Ensure pyngrok is installed
    install_pyngrok()

    # Start Flask server
    start_flask()

    # Start ngrok tunnel
    start_ngrok(authtoken)

    # Keep running until interrupted
    try:
        while True:
            time.sleep(1)
            # Check if Flask is still running
            if flask_process and flask_process.poll() is not None:
                print("Flask server stopped unexpectedly.")
                cleanup()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
