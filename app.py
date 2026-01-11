import os
import subprocess
import json
import re
import requests
from flask import Flask, request, render_template

# Set your Google Maps API key for the evaluator
os.environ["GOOGLE_MAPS_API_KEY"] = "AIzaSyDFTggXPncXzwKNLyROAgiaQ7XEtzUG48I"

app = Flask(__name__)

def clean(value):
    if not value:
        return None
    return value.replace(",", "").replace("$", "").strip()

def extract_zpid_from_url(url):
    """
    Extract the Zillow Property ID (zpid) from a Zillow URL.
    Examples:
    - https://www.zillow.com/homedetails/123-Main-St/31492816_zpid/ -> 31492816
    - https://www.zillow.com/homedetails/456-Oak-Ave-Scarsdale-NY-10583/12345678_zpid/ -> 12345678
    """
    # Look for pattern: digits followed by _zpid
    match = re.search(r'/(\d+)_zpid', url)
    if match:
        return match.group(1)

    # Alternative: zpid might be in query params
    match = re.search(r'zpid=(\d+)', url)
    if match:
        return match.group(1)

    return None


def scrape_zillow(url):
    """
    Fetch property details from Zillow using their GraphQL API.
    Extracts address, rent, sqft, and bedrooms from API response.
    Returns a dict with extracted values or None if fetching fails.
    """
    try:
        # Extract zpid from URL
        zpid = extract_zpid_from_url(url)
        if not zpid:
            print(f"Failed to extract zpid from URL: {url}")
            return None

        print(f"Extracted zpid: {zpid}")

        # Call Zillow's GraphQL API
        graphql_url = "https://www.zillow.com/graphql/"

        # GraphQL query for property details
        query = """
        query ForSalePropertyQuery($zpid: ID!) {
          property(zpid: $zpid) {
            zpid
            streetAddress
            city
            state
            zipcode
            bedrooms
            bathrooms
            price
            livingArea
            homeType
            rentZestimate
          }
        }
        """

        payload = {
            "query": query,
            "variables": {
                "zpid": zpid
            }
        }

        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
        }

        print(f"Calling Zillow GraphQL API for zpid {zpid}...")
        response = requests.post(graphql_url, json=payload, headers=headers, timeout=15)
        print(f"GraphQL Response status: {response.status_code}")

        if response.status_code != 200:
            print(f"GraphQL request failed with status {response.status_code}")
            print(f"Response: {response.text[:500]}")
            return None

        data = response.json()

        # Extract property data from GraphQL response
        if 'data' in data and 'property' in data['data']:
            property_data = data['data']['property']
            print(f"Received property data: {property_data}")

            result = {}

            # Extract address
            street = property_data.get('streetAddress', '')
            city = property_data.get('city', '')
            state = property_data.get('state', '')
            zipcode = property_data.get('zipcode', '')
            if street:
                result['address'] = f"{street}, {city}, {state} {zipcode}".strip(', ')

            # Extract rent/price
            # For rental properties, use rentZestimate, otherwise use price
            rent = property_data.get('rentZestimate') or property_data.get('price')
            if rent:
                result['rent'] = int(rent)

            # Extract square feet
            living_area = property_data.get('livingArea')
            if living_area:
                result['sqft'] = int(living_area)

            # Extract bedrooms
            bedrooms = property_data.get('bedrooms')
            if bedrooms:
                result['bedrooms'] = int(bedrooms)

            print(f"Extracted result: {result}")
            return result if result else None
        else:
            print(f"No property data in GraphQL response: {data}")
            return None

    except Exception as e:
        print(f"Error fetching Zillow data via GraphQL: {str(e)}")
        import traceback
        traceback.print_exc()
        return None

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        try:
            # Check if Zillow URL is provided
            zillow_url = request.form.get("zillow_url", "").strip()
            zillow_data = None

            if zillow_url:
                # Try to scrape Zillow
                zillow_data = scrape_zillow(zillow_url)
                # Only show error if we got no data at all (not even an address)
                if not zillow_data or not zillow_data.get('address'):
                    error = "Could not extract data from Zillow URL. Please enter property details manually."
                # If we got at least an address, we can work with partial data

            # Get form values (these will be overridden by Zillow data if available)
            address = request.form.get("address", "").strip()
            rent = clean(request.form.get("rent"))
            sqft = clean(request.form.get("sqft"))
            bedrooms = clean(request.form.get("bedrooms"))

            # Override with Zillow data if available
            if zillow_data:
                if zillow_data.get('address'):
                    address = zillow_data['address']
                if zillow_data.get('rent'):
                    rent = str(zillow_data['rent'])
                if zillow_data.get('sqft'):
                    sqft = str(zillow_data['sqft'])
                if zillow_data.get('bedrooms'):
                    bedrooms = str(zillow_data['bedrooms'])

            # Validate we have an address
            if not address:
                error = "Address is required"
                return render_template("index.html", result=result, error=error)

            # Build command for property evaluator
            cmd = ["python", "property_evaluator.py", address, "--json"]

            if rent:
                cmd += ["--rent", rent]
            if sqft:
                cmd += ["--sqft", sqft]
            if bedrooms:
                cmd += ["--bedrooms", bedrooms]

            # Run the property evaluator
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            result = json.loads(output)

        except subprocess.CalledProcessError as e:
            error = e.output
        except Exception as e:
            error = str(e)

    return render_template("index.html", result=result, error=error)

if __name__ == "__main__":
    app.run(debug=True)
