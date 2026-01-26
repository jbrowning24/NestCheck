#!/usr/bin/env python3
"""
Start NestCheck with a public URL for mobile testing.

Usage:
    python start_mobile_test.py

This script starts the Flask server and creates a public tunnel
so you can access NestCheck from your iPhone or any device.

Your URL will be: https://nestcheck.loca.lt
"""

import subprocess
import sys
import time
import signal
import shutil

# Configuration
PORT = 5001
SUBDOMAIN = "nestcheck"  # Will give us https://nestcheck.loca.lt

flask_process = None
tunnel_process = None


def check_requirements():
    """Check that required tools are installed."""
    # Check for npx (comes with Node.js)
    if not shutil.which("npx"):
        print("ERROR: Node.js is required for localtunnel.")
        print("\nInstall Node.js from: https://nodejs.org/")
        print("Or via your package manager:")
        print("  - macOS: brew install node")
        print("  - Ubuntu: sudo apt install nodejs npm")
        sys.exit(1)
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
    # Give Flask a moment to start
    time.sleep(2)
    print("Flask server started.\n")
    return flask_process


def start_tunnel():
    """Start localtunnel with custom subdomain."""
    global tunnel_process

    print("Creating public tunnel via localtunnel...")
    print(f"Requesting subdomain: {SUBDOMAIN}\n")

    # Use npx to run localtunnel without global install
    tunnel_process = subprocess.Popen(
        ["npx", "localtunnel", "--port", str(PORT), "--subdomain", SUBDOMAIN],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Read output to find the public URL
    for line in iter(tunnel_process.stdout.readline, ''):
        line = line.strip()
        if line:
            print(line)

        if "your url is:" in line.lower() or "loca.lt" in line.lower():
            # Extract the URL
            if "https://" in line:
                url_start = line.find("https://")
                url = line[url_start:].strip()

                print("\n" + "=" * 60)
                print("YOUR MOBILE TESTING URL:")
                print(f"\n    {url}\n")
                print("Open this URL on your iPhone to test NestCheck!")
                print("\nNote: First visit may show a reminder page -")
                print("just click through to access your app.")
                print("=" * 60 + "\n")
                print("Press Ctrl+C to stop the server.\n")

    return tunnel_process


def cleanup(signum=None, frame=None):
    """Clean up processes on exit."""
    print("\nShutting down...")
    if tunnel_process:
        tunnel_process.terminate()
        tunnel_process.wait()
    if flask_process:
        flask_process.terminate()
        flask_process.wait()
    print("Goodbye!")
    sys.exit(0)


def main():
    # Set up signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("=" * 60)
    print("NestCheck Mobile Testing Server")
    print("=" * 60 + "\n")

    # Check requirements
    check_requirements()

    # Start Flask server
    start_flask()

    # Start tunnel
    try:
        start_tunnel()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
