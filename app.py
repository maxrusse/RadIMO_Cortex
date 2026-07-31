# Standard library imports
import os
from datetime import timedelta

# Flask imports
from flask import Flask

# Local imports
from config import APP_CONFIG
from routes import routes
from config import allowed_modalities
from data_manager.file_ops import attempt_initialize_data, load_unified_live_backup
from data_manager.scheduled_tasks import check_and_perform_daily_reset
from data_manager.state_persistence import load_state
from state_manager import StateManager
from lib.utils import selection_logger

# -----------------------------------------------------------
# Flask App Initialization
# -----------------------------------------------------------
app = Flask(__name__)
app.secret_key = APP_CONFIG['secret_key']
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max upload

# Configure permanent session lifetime (365 days for basic access cookie persistence)
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365)

# Register Routes
app.register_blueprint(routes)

# Daily reset check runs on every request
@app.before_request
def before_request_hook() -> None:
    check_and_perform_daily_reset()


# -----------------------------------------------------------
# Startup Logic
# -----------------------------------------------------------
def startup_initialization() -> None:
    load_state()

    # Check for master CSV existence
    master_csv_path = os.path.join(app.config['UPLOAD_FOLDER'], 'master_medweb.csv')
    if os.path.exists(master_csv_path):
        selection_logger.info(f"Found master CSV at {master_csv_path}")
    else:
        selection_logger.info("No master CSV found.")

    # Initialize Modalities
    state = StateManager.get_instance()
    unified_live_backup = state.unified_schedule_paths['live']
    if load_unified_live_backup(unified_live_backup):
        selection_logger.info("Unified live backup loaded at startup.")
        return

    for mod in allowed_modalities:
        backup_dir = os.path.join(app.config['UPLOAD_FOLDER'], "backups")
        live_backup = os.path.join(backup_dir, f"Cortex_{mod.upper()}_live.json")

        if os.path.exists(live_backup):
            selection_logger.info(f"Attempting to load LIVE backup for {mod}: {live_backup}")
            if attempt_initialize_data(live_backup, mod, context='startup backup'):
                continue

        selection_logger.warning(f"Starting {mod} with EMPTY data (no valid backup).")


# -----------------------------------------------------------
# Module-level initialization (runs for both Gunicorn and direct execution)
# -----------------------------------------------------------
startup_initialization()

# -----------------------------------------------------------
# Main Entry Point (development only)
# -----------------------------------------------------------
if __name__ == '__main__':
    # In production, use a proper WSGI server (gunicorn/waitress)
    # For development/local use:
    app.run(host='0.0.0.0', port=5040, debug=True, use_reloader=False)
