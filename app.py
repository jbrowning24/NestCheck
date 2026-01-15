import os
import subprocess
import json
from flask import Flask, request, render_template
from dotenv import load_dotenv

load_dotenv()

# Set your Google Maps API key for the evaluator
os.environ["GOOGLE_MAPS_API_KEY"] = "AIzaSyDFTggXPncXzwKNLyROAgiaQ7XEtzUG48I"

app = Flask(__name__)

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        try:
            # Get manual form input
            address = request.form.get("address", "").strip()

            # Validate that we have at least an address
            if not address:
                error = "Address is required. Please enter a property address."
                return render_template("index.html", result=result, error=error)

            # Build command for property evaluator
            cmd = ["python", "property_evaluator.py", address, "--json"]

            # Run the property evaluator
            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            result = json.loads(output)

        except subprocess.CalledProcessError as e:
            error = e.output
        except Exception as e:
            error = str(e)

    return render_template("index.html", result=result, error=error)

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 5001))   # use 5001 instead of 5000
    app.run(host="0.0.0.0", port=port, debug=True)
