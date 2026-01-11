import os
import subprocess
import json
from flask import Flask, request, render_template

# Set your Google Maps API key for the evaluator
os.environ["GOOGLE_MAPS_API_KEY"] = "AIzaSyDFTggXPncXzwKNLyROAgiaQ7XEtzUG48I"

app = Flask(__name__)

def clean(value):
    if not value:
        return None
    return value.replace(",", "").replace("$", "").strip()

@app.route("/", methods=["GET", "POST"])
def index():
    result = None
    error = None

    if request.method == "POST":
        try:
            address = request.form["address"]

            rent = clean(request.form.get("rent"))
            sqft = clean(request.form.get("sqft"))
            bedrooms = clean(request.form.get("bedrooms"))

            cmd = ["python", "property_evaluator.py", address, "--json"]

            if rent:
                cmd += ["--rent", rent]
            if sqft:
                cmd += ["--sqft", sqft]
            if bedrooms:
                cmd += ["--bedrooms", bedrooms]

            output = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
            result = json.loads(output)

        except subprocess.CalledProcessError as e:
            error = e.output
        except Exception as e:
            error = str(e)

    return render_template("index.html", result=result, error=error)

if __name__ == "__main__":
    app.run(debug=True)
