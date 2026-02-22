#!/usr/bin/env python3
"""Verify SpatiaLite is available in this environment."""

import sqlite3
import sys


def check():
    conn = sqlite3.connect(":memory:")
    conn.enable_load_extension(True)

    for lib_name in ["mod_spatialite", "libspatialite"]:
        try:
            conn.load_extension(lib_name)
            version = conn.execute("SELECT spatialite_version()").fetchone()[0]
            print(f"OK: SpatiaLite {version} loaded via '{lib_name}'")
            conn.close()
            return True
        except Exception as e:
            print(f"SKIP: '{lib_name}' — {e}")

    print("\nFAIL: SpatiaLite not found.")
    print("Install with:")
    print("  Ubuntu/Debian: apt-get install libspatialite-dev")
    print("  macOS:         brew install spatialite-tools libspatialite")
    print("  Alpine:        apk add spatialite")
    conn.close()
    return False


if __name__ == "__main__":
    success = check()
    sys.exit(0 if success else 1)
