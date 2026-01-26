#!/usr/bin/env python3
"""
Start NestCheck with a public URL for mobile testing.

Usage:
    python start_mobile_test.py

This script starts the Flask server and creates a public tunnel
so you can access NestCheck from your iPhone or any device.
"""

import subprocess
import sys
import time
import threading
import signal
import os

# Configuration
PORT = 5001
TUNNEL_SERVICE = "localhost.run"  # Free, no account needed

flask_process = None
tunnel_process = None


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
    return flask_process


def start_tunnel():
    """Start SSH tunnel to localhost.run for public URL."""
    global tunnel_process
    print("\nCreating public tunnel via localhost.run...")
    print("(This may take a few seconds)\n")

    tunnel_process = subprocess.Popen(
        ["ssh", "-o", "StrictHostKeyChecking=no", "-R", f"80:localhost:{PORT}", "nokey@localhost.run"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Read output to find the public URL
    for line in iter(tunnel_process.stdout.readline, ''):
        print(line.strip())
        if "tunneled" in line.lower() or "https://" in line.lower():
            # Extract and highlight the URL
            if "https://" in line:
                url_start = line.find("https://")
                url_end = line.find(" ", url_start) if " " in line[url_start:] else len(line)
                url = line[url_start:url_end].strip()
                print("\n" + "=" * 60)
                print("YOUR MOBILE TESTING URL:")
                print(f"\n    {url}\n")
                print("Open this URL on your iPhone to test NestCheck!")
                print("=" * 60 + "\n")
                print("Press Ctrl+C to stop the server.\n")

    return tunnel_process


def cleanup(signum=None, frame=None):
    """Clean up processes on exit."""
    print("\nShutting down...")
    if tunnel_process:
        tunnel_process.terminate()
    if flask_process:
        flask_process.terminate()
    sys.exit(0)


def main():
    # Set up signal handlers
    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    print("=" * 60)
    print("NestCheck Mobile Testing Server")
    print("=" * 60 + "\n")

    # Check for SSH
    try:
        subprocess.run(["ssh", "-V"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: SSH is required for tunneling.")
        print("Please ensure SSH is installed on your system.")
        sys.exit(1)

    # Start Flask server
    start_flask()

    # Start tunnel in main thread (to show output)
    try:
        start_tunnel()
    except KeyboardInterrupt:
        cleanup()


if __name__ == "__main__":
    main()
