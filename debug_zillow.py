#!/usr/bin/env python3
"""
Debug script to inspect Zillow page structure and test data extraction
Usage: python debug_zillow.py "https://www.zillow.com/homedetails/..."
"""

import sys
import json
import re
import requests
from bs4 import BeautifulSoup


def fetch_and_analyze_zillow(url):
    """Fetch Zillow page and show what data structures are available"""

    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
        'Accept-Encoding': 'gzip, deflate, br',
        'DNT': '1',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
    }

    print(f"Fetching: {url}\n")

    try:
        response = requests.get(url, headers=headers, timeout=15)
        print(f"Status Code: {response.status_code}\n")

        if response.status_code != 200:
            print(f"Failed to fetch page: {response.status_code}")
            return

        soup = BeautifulSoup(response.text, 'html.parser')

        # Look for __NEXT_DATA__
        print("=" * 70)
        print("Looking for __NEXT_DATA__ script tag...")
        print("=" * 70)
        next_data_script = soup.find('script', {'id': '__NEXT_DATA__'})
        if next_data_script:
            print("✓ Found __NEXT_DATA__ script tag")
            try:
                data = json.loads(next_data_script.string)
                print("\nTop-level keys:")
                print(json.dumps(list(data.keys()), indent=2))

                if 'props' in data:
                    print("\nprops keys:")
                    print(json.dumps(list(data['props'].keys()), indent=2))

                    if 'pageProps' in data['props']:
                        print("\npageProps keys:")
                        print(json.dumps(list(data['props']['pageProps'].keys()), indent=2))

                        # Save full structure to file for inspection
                        with open('zillow_next_data.json', 'w') as f:
                            json.dump(data, f, indent=2)
                        print("\n✓ Saved full __NEXT_DATA__ to zillow_next_data.json")

                        # Try to find property data
                        page_props = data['props']['pageProps']

                        # Check for common locations
                        if 'componentProps' in page_props:
                            print("\n✓ Found componentProps")
                            print("componentProps keys:", list(page_props['componentProps'].keys())[:10])

                        if 'gdpClientCache' in page_props:
                            print("\n✓ Found gdpClientCache")
                            cache_keys = list(page_props['gdpClientCache'].keys())
                            print(f"gdpClientCache has {len(cache_keys)} keys")
                            if cache_keys:
                                first_key = cache_keys[0]
                                print(f"First key: {first_key}")
                                print("Data under first key:", list(page_props['gdpClientCache'][first_key].keys())[:10])

                        if 'initialReduxState' in page_props:
                            print("\n✓ Found initialReduxState")
                            print("initialReduxState keys:", list(page_props['initialReduxState'].keys())[:10])

            except json.JSONDecodeError as e:
                print(f"✗ Failed to parse __NEXT_DATA__ JSON: {e}")
        else:
            print("✗ No __NEXT_DATA__ script tag found")

        # Look for other script tags with JSON
        print("\n" + "=" * 70)
        print("Looking for other JSON-containing scripts...")
        print("=" * 70)

        all_scripts = soup.find_all('script')
        print(f"Found {len(all_scripts)} script tags total")

        json_scripts = 0
        for i, script in enumerate(all_scripts):
            if script.string and len(script.string.strip()) > 50:
                # Check if it looks like JSON
                stripped = script.string.strip()
                if stripped.startswith('{') or 'var ' in stripped[:100] or 'window.' in stripped[:100]:
                    json_scripts += 1
                    if json_scripts <= 5:  # Show first 5
                        print(f"\nScript {i}: {stripped[:200]}...")

        print(f"\nFound {json_scripts} scripts with potential JSON data")

        # Save HTML for manual inspection
        with open('zillow_page.html', 'w', encoding='utf-8') as f:
            f.write(response.text)
        print("\n✓ Saved full HTML to zillow_page.html")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python debug_zillow.py \"https://www.zillow.com/homedetails/...\"")
        sys.exit(1)

    fetch_and_analyze_zillow(sys.argv[1])
