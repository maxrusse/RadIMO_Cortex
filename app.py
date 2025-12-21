# Standard library imports
import os
import atexit
import logging
from apscheduler.schedulers.background import BackgroundScheduler

# Flask imports
from flask import Flask

# Local imports
from config import APP_CONFIG
from routes import routes, auto_preload_job
from data_manager import (
    load_state,
    check_and_perform_daily_reset,
    modality_data,
    allowed_modalities,
    attempt_initialize_data,
    lock
)
from utils import selection_logger

# -----------------------------------------------------------
# Flask App Initialization
# -----------------------------------------------------------
app = Flask(__name__)
app.secret_key = 'super_secret_key_for_dev'  # Ideally move to config
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# Register Routes
app.register_blueprint(routes)

# -----------------------------------------------------------
# Scheduler Setup
# -----------------------------------------------------------
scheduler = BackgroundScheduler()

# Daily reset check (runs on every request, but we also schedule it to be safe or just rely on request)
# Original code had it in before_request.
@app.before_request
def before_request_hook():
    check_and_perform_daily_reset()

# Schedule auto-preload daily from Master CSV
preload_hour = APP_CONFIG.get('scheduler', {}).get('auto_preload_time', 14)
scheduler.add_job(auto_preload_job, 'cron', hour=preload_hour, minute=0)
scheduler.start()
atexit.register(lambda: scheduler.shutdown())

# -----------------------------------------------------------
# Startup Logic
# -----------------------------------------------------------
def startup_initialization():
    load_state()
    
    # Check for master CSV existence
    master_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'master_medweb.csv')
    if os.path.exists(master_csv_path):
        selection_logger.info(f"Found master CSV at {master_csv_path}")
    else:
        selection_logger.info("No master CSV found.")

    # Initialize Modalities
    for mod in allowed_modalities:
        d = modality_data[mod]
        # Priority 1: Live Backup
        # Priority 2: Default file
        # Priority 3: Start empty
        
        backup_dir = os.path.join(app.config['UPLOAD_FOLDER'], "backups")
        live_backup = os.path.join(backup_dir, f"Cortex_{mod.upper()}_live.xlsx")
        
        loaded = False
        
        if os.path.exists(live_backup):
            selection_logger.info(f"Attempting to load LIVE backup for {mod}: {live_backup}")
            if attempt_initialize_data(live_backup, mod, context='startup backup'):
                loaded = True
        
        if not loaded and os.path.exists(d['default_file_path']):
            selection_logger.info(f"Attempting to load DEFAULT file for {mod}: {d['default_file_path']}")
            if attempt_initialize_data(d['default_file_path'], mod, context='startup default'):
                loaded = True
                
        if not loaded:
            selection_logger.warning(f"Starting {mod} with EMPTY data (no valid backup or default file).")


# -----------------------------------------------------------
# Main Entry Point
# -----------------------------------------------------------
if __name__ == '__main__':
    startup_initialization()
    
    # In production, use a proper WSGI server (gunicorn/waitress)
    # For development/local use:
    app.run(host='0.0.0.0', port=5000, debug=True, use_reloader=False)