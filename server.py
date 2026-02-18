import threading
import os
from flask import Flask, jsonify
from monitor import SheinMonitor

app = Flask(__name__)

# Global monitor instance
monitor = SheinMonitor()

@app.route('/')
def health_check():
    return "Monitor is running", 200

@app.route('/status')
def status():
    return jsonify({
        "running": monitor.running,
        "monitored_genders": ["Men", "Women"]
    })

def start_monitor():
    """Starts the monitor in a background thread."""
    if not monitor.running:
        monitor.start()

if __name__ == "__main__":
    # Start the monitor thread
    monitor_thread = threading.Thread(target=start_monitor, daemon=True)
    monitor_thread.start()
    
    # Run the Flask app
    # Host must be 0.0.0.0 for Docker/Render
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
