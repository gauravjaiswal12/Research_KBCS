from flask import Flask, render_template, jsonify
import pandas as pd
import os

app = Flask(__name__)

# Absolute fallback path for robust execution
CSV_FILE = os.path.join(os.path.dirname(__file__), 'results', 'karma_log.csv')

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    if not os.path.exists(CSV_FILE):
        return jsonify({"error": "No data yet. Waiting for traffic test to start...", "data": []})
    
    try:
        df = pd.read_csv(CSV_FILE)
        # Convert to dictionary format suitable for Chart.js
        data = {
            "time": df['time_sec'].tolist(),
            "cubic": df['cubic_karma'].tolist(),
            "bbr": df['bbr_karma'].tolist()
        }
        return jsonify({"data": data})
    except Exception as e:
        return jsonify({"error": str(e), "data": []})

if __name__ == '__main__':
    # Run on all interfaces so the user can access it from Windows host (e.g., http://localhost:5000)
    app.run(host='0.0.0.0', port=5000, debug=True)
