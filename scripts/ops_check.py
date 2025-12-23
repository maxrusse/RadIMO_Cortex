"""Quick operational readiness helper.

Loads the Flask app, prints a summary of currently configured modalities and skills,
then runs the inline operational checks (config/admin password/uploads directory).
Use this script right after pulling the latest main branch to verify the deployment
is ready for a test system before starting the server.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pprint import pprint

import app
from config import APP_CONFIG, SKILL_TEMPLATES
from routes import run_operational_checks


def main() -> None:
    print("Loaded modalities:")
    pprint(APP_CONFIG.get('modalities', {}))
    print("\nConfigured skills (in display order):")
    pprint([entry['label'] for entry in SKILL_TEMPLATES])
    print("\nOperational checks:")
    pprint(run_operational_checks('cli', force=True))


if __name__ == '__main__':
    main()
