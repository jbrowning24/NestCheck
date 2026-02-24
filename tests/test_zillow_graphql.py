#!/usr/bin/env python3
"""
Test script to verify Zillow GraphQL integration
Usage: python test_zillow_graphql.py "https://www.zillow.com/homedetails/..."
"""

import sys
import os

# Add the current directory to the path so we can import from app.py
sys.path.insert(0, os.path.dirname(__file__))

from app import extract_zpid_from_url, scrape_zillow

def test_zpid_extraction():
    """Test zpid extraction from various URL formats"""
    test_urls = [
        "https://www.zillow.com/homedetails/123-Main-St/31492816_zpid/",
        "https://www.zillow.com/homedetails/456-Oak-Ave-Scarsdale-NY-10583/12345678_zpid/",
        "https://www.zillow.com/homes/31492816_zpid/",
    ]

    print("Testing zpid extraction:")
    print("=" * 70)
    for url in test_urls:
        zpid = extract_zpid_from_url(url)
        print(f"URL: {url}")
        print(f"zpid: {zpid}\n")


def test_zillow_scraping(url):
    """Test full Zillow scraping for a given URL"""
    print("\n" + "=" * 70)
    print("Testing Zillow GraphQL scraping:")
    print("=" * 70)
    print(f"URL: {url}\n")

    result = scrape_zillow(url)

    if result:
        print("\n✓ Successfully scraped Zillow data:")
        print(f"  Address: {result.get('address', 'N/A')}")
        print(f"  Rent: ${result.get('rent', 'N/A'):,}" if result.get('rent') else "  Rent: N/A")
        print(f"  Square Feet: {result.get('sqft', 'N/A'):,}" if result.get('sqft') else "  Square Feet: N/A")
        print(f"  Bedrooms: {result.get('bedrooms', 'N/A')}")
    else:
        print("\n✗ Failed to scrape Zillow data")


if __name__ == "__main__":
    # Test zpid extraction
    test_zpid_extraction()

    # Test scraping if URL provided
    if len(sys.argv) > 1:
        test_zillow_scraping(sys.argv[1])
    else:
        print("\nTo test scraping, provide a Zillow URL:")
        print("  python test_zillow_graphql.py \"https://www.zillow.com/homedetails/...\"")
