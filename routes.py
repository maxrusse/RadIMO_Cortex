# Standard library imports
import os
import json
import shutil
from datetime import datetime
from functools import wraps

# Flask imports
from flask import (
    Blueprint,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

# Third-party imports
import yaml
import pandas as pd

# Local imports
from config import (
    APP_CONFIG,
    MODALITY_SETTINGS,
    SKILL_SETTINGS,
    allowed_modalities,
    SKILL_COLUMNS,
    SKILL_TEMPLATES,
    modality_labels,
    MASTER_CSV_PATH,
    selection_logger,
    SKILL_ROSTER_AUTO_IMPORT,
    normalize_modality,
    normalize_skill
)
import usage_logger
from utils import (
    get_local_berlin_now,
    get_next_workday,
    parse_time_range,
    TIME_FORMAT,
    normalize_skill_value,
    skill_value_to_numeric,
    calculate_shift_duration_hours
)
from data_manager import (
    modality_data,
    staged_modality_data,
    global_worker_data,
    lock,
    save_state,
    get_canonical_worker_id,
    load_worker_skill_json,
    build_working_hours_from_medweb,
    auto_populate_skill_roster,
    load_staged_dataframe,
    backup_dataframe,
    _update_schedule_row,
    _add_worker_to_schedule,
    _delete_worker_from_schedule,
    _add_gap_to_schedule,
    preload_next_workday,
    _calculate_total_work_hours
)
from balancer import (
    get_next_available_worker,
    update_global_assignment,
    get_global_assignments,
    get_global_weighted_count,
    BALANCER_SETTINGS
)

# Create Blueprint
routes = Blueprint('routes', __name__)

# -----------------------------------------------------------
# Helpers for Routes
# -----------------------------------------------------------
def _df_to_api_response(df: pd.DataFrame) -> list:
    if df is None or df.empty:
        return []

    data = []
    for idx in df.index:
        row = df.loc[idx]
        worker_data = {
            'row_index': int(idx),
            'PPL': row['PPL'],
            'start_time': row['start_time'].strftime(TIME_FORMAT) if pd.notnull(row.get('start_time')) else '',
            'end_time': row['end_time'].strftime(TIME_FORMAT) if pd.notnull(row.get('end_time')) else '',
            'Modifier': float(row.get('Modifier', 1.0)) if pd.notnull(row.get('Modifier')) else 1.0,
        }

        if 'gaps' in df.columns:
            worker_data['gaps'] = row.get('gaps', None)

        for skill in SKILL_COLUMNS:
            value = row.get(skill, 0)
            worker_data[skill] = normalize_skill_value(value) if pd.notnull(value) else 0

        tasks_val = row.get('tasks', '')
        if isinstance(tasks_val, list):
            worker_data['tasks'] = tasks_val
        elif isinstance(tasks_val, str) and tasks_val:
            worker_data['tasks'] = [t.strip() for t in tasks_val.split(',') if t.strip()]
        else:
            worker_data['tasks'] = []

        if 'counts_for_hours' in df.columns:
            val = row.get('counts_for_hours', True)
            if pd.isna(val):
                worker_data['counts_for_hours'] = True
            else:
                worker_data['counts_for_hours'] = bool(val)
        else:
            worker_data['counts_for_hours'] = True

        if 'is_manual' in df.columns:
            worker_data['is_manual'] = bool(row.get('is_manual', False))
        if 'gap_id' in df.columns:
            worker_data['gap_id'] = row.get('gap_id')

        data.append(worker_data)

    return data

def resolve_modality_from_request() -> str:
    return normalize_modality(request.values.get('modality'))

def get_admin_password():
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        return config.get("admin_password", "")
    except Exception as e:
        selection_logger.info("Error loading config.yaml:", e)
        return ""


def get_access_password():
    """Get the basic access password from config."""
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        return config.get("access_password", "change_easy_pw")
    except Exception as e:
        selection_logger.info("Error loading config.yaml:", e)
        return "change_easy_pw"


def is_access_protection_enabled():
    """Check if basic access protection is enabled."""
    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        return config.get("access_protection_enabled", True)
    except Exception as e:
        selection_logger.info("Error loading config.yaml:", e)
        return True


def access_required(f):
    """Decorator that requires basic access authentication for non-admin pages.

    Uses a long-lived session cookie so users don't need to re-login frequently.
    Admin login also grants basic access.
    """
    @wraps(f)
    def decorated(*args, **kwargs):
        # Skip if access protection is disabled
        if not is_access_protection_enabled():
            return f(*args, **kwargs)
        # Admin login also grants access
        if session.get('admin_logged_in') or session.get('access_granted'):
            return f(*args, **kwargs)
        modality = resolve_modality_from_request()
        return redirect(url_for('routes.access_login', modality=modality))
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            modality = resolve_modality_from_request()
            return redirect(url_for('routes.login', modality=modality))
        return f(*args, **kwargs)
    return decorated

# -----------------------------------------------------------
# Route Definitions
# -----------------------------------------------------------

@routes.context_processor
def inject_modality_settings():
    return {
        'modalities': MODALITY_SETTINGS,
        'modality_order': allowed_modalities,
        'modality_labels': modality_labels,
        'skill_definitions': SKILL_TEMPLATES,
        'skill_order': SKILL_COLUMNS,
        'skill_labels': {s['name']: s['label'] for s in SKILL_TEMPLATES},
    }

@routes.route('/')
@access_required
def index():
    modality = resolve_modality_from_request()
    d = modality_data[modality]

    modality_config = MODALITY_SETTINGS.get(modality, {})
    mod_valid_skills = set(modality_config.get('valid_skills', SKILL_COLUMNS))
    mod_hidden_skills = set(modality_config.get('hidden_skills', []))

    visible_skills = []
    for skill_name in SKILL_COLUMNS:
        if skill_name not in mod_valid_skills or skill_name in mod_hidden_skills:
            continue
        skill_config = SKILL_SETTINGS.get(skill_name, {})
        skill_valid_mods = skill_config.get('valid_modalities')
        skill_hidden_mods = set(skill_config.get('hidden_modalities', []))
        if skill_valid_mods is not None and modality not in skill_valid_mods:
            continue
        if modality in skill_hidden_mods:
            continue
        visible_skills.append(skill_name)

    return render_template(
        'index.html',
        info_texts=d.get('info_texts', []),
        modality=modality,
        visible_skills=visible_skills,
        is_admin=session.get('admin_logged_in', False)
    )

@routes.route('/by-skill')
@access_required
def index_by_skill():
    skill = request.args.get('skill', SKILL_COLUMNS[0] if SKILL_COLUMNS else 'Notfall')
    skill = normalize_skill(skill)

    skill_config = SKILL_SETTINGS.get(skill, {})
    skill_valid_mods = skill_config.get('valid_modalities')
    skill_hidden_mods = set(skill_config.get('hidden_modalities', []))

    visible_modalities = []
    for mod in allowed_modalities:
        if skill_valid_mods is not None and mod not in skill_valid_mods:
            continue
        if mod in skill_hidden_mods:
            continue
        mod_config = MODALITY_SETTINGS.get(mod, {})
        mod_valid_skills = mod_config.get('valid_skills')
        mod_hidden_skills = set(mod_config.get('hidden_skills', []))
        if mod_valid_skills is not None and skill not in mod_valid_skills:
            continue
        if skill in mod_hidden_skills:
            continue
        visible_modalities.append(mod)

    info_texts = []
    if allowed_modalities:
        first_modality = allowed_modalities[0]
        info_texts = modality_data[first_modality].get('info_texts', [])

    return render_template(
        'index_by_skill.html',
        skill=skill,
        visible_modalities=visible_modalities,
        info_texts=info_texts
    )

@routes.route('/timetable')
@access_required
def timetable():
    modality = request.args.get('modality', 'all')
    skill_filter = request.args.get('skill', 'all')
    
    # Combine data from all modalities or a specific one
    combined_data = []
    
    target_modalities = allowed_modalities if modality == 'all' else [modality]
    for mod in target_modalities:
        df = modality_data[mod]['working_hours_df']
        if df is not None:
            # Add modality info to each row for the frontend
            temp_df = df.copy()
            temp_df['_modality'] = mod
            combined_data.extend(_df_to_api_response(temp_df))
            
    # Skill slug/color maps for the frontend
    skill_slug_map = {s['name']: s['slug'] for s in SKILL_TEMPLATES}
    skill_color_map = {s['slug']: s['button_color'] for s in SKILL_TEMPLATES}
    modality_color_map = {mod: settings.get('nav_color', '#004892') for mod, settings in MODALITY_SETTINGS.items()}

    return render_template(
        'timetable.html',
        modality=modality,
        skill_filter=skill_filter,
        debug_data=json.dumps(combined_data),
        skill_columns=SKILL_COLUMNS,
        skill_slug_map=skill_slug_map,
        skill_color_map=skill_color_map,
        modality_color_map=modality_color_map
    )

@routes.route('/skill-roster')
@admin_required
def skill_roster_page():
    from data_manager import build_valid_skills_map
    valid_skills_map = build_valid_skills_map()
    return render_template('skill_roster.html', valid_skills_map=valid_skills_map)

@routes.route('/api/admin/skill_roster', methods=['GET', 'POST'])
@admin_required
def skill_roster_api():
    from data_manager import load_worker_skill_json, save_worker_skill_json
    if request.method == 'POST':
        data = request.json
        roster = data.get('roster')
        if roster is not None:
            save_worker_skill_json(roster)
            return jsonify({'success': True})
        return jsonify({'error': 'No roster data'}), 400
    
    roster = load_worker_skill_json()
    return jsonify({
        'success': True,
        'roster': roster,
        'skills': SKILL_COLUMNS,
        'modalities': allowed_modalities
    })

@routes.route('/api/admin/skill_roster/import_new', methods=['POST'])
@admin_required
def import_new_skill_roster_api():
    from data_manager import auto_populate_skill_roster
    # Get current modality DFs
    current_dfs = {mod: modality_data[mod]['working_hours_df'] for mod in allowed_modalities}
    added_count = auto_populate_skill_roster(current_dfs)
    return jsonify({
        'success': True,
        'added_count': added_count
    })

@routes.route('/login', methods=['GET', 'POST'])
def login():
    modality = resolve_modality_from_request()
    error = None
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if pw == get_admin_password():
            session['admin_logged_in'] = True
            return redirect(url_for('routes.upload_file', modality=modality))
        else:
            error = "Falsches Passwort"
    return render_template("login.html", error=error, modality=modality)

@routes.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    modality = resolve_modality_from_request()
    return redirect(url_for('routes.index', modality=modality))


@routes.route('/access-login', methods=['GET', 'POST'])
def access_login():
    """Basic access login for non-admin pages.

    Uses a permanent session cookie for long-lived access.
    """
    modality = resolve_modality_from_request()

    # If access protection is disabled, redirect to index
    if not is_access_protection_enabled():
        return redirect(url_for('routes.index', modality=modality))

    # If already authenticated (either as admin or with basic access), redirect to index
    if session.get('admin_logged_in') or session.get('access_granted'):
        return redirect(url_for('routes.index', modality=modality))

    error = None
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if pw == get_access_password():
            session.permanent = True  # Use permanent session for long-lived cookie
            session['access_granted'] = True
            return redirect(url_for('routes.index', modality=modality))
        else:
            error = "Falsches Passwort"

    return render_template("access_login.html", error=error, modality=modality)


@routes.route('/access-logout')
def access_logout():
    """Logout from basic access (keeps admin session if present)."""
    session.pop('access_granted', None)
    modality = resolve_modality_from_request()
    return redirect(url_for('routes.access_login', modality=modality))


@routes.route('/api/edit_info', methods=['POST'])
@admin_required
def edit_info():
    """Update info texts for a specific modality"""
    try:
        data = request.get_json()
        modality = normalize_modality(data.get('modality', ''))
        info_text = data.get('info_text', '')

        if not modality or modality not in allowed_modalities:
            return jsonify({"success": False, "error": "Ungültige Modalität"}), 400

        # Split info_text by newlines and filter out empty lines
        info_texts = [line.strip() for line in info_text.split('\n') if line.strip()]

        # Update the modality data
        modality_data[modality]['info_texts'] = info_texts

        # Save the updated state and backup
        save_state()
        backup_dataframe(modality)

        selection_logger.info(f"Info texts updated for {modality} by admin")

        return jsonify({
            "success": True,
            "info_texts": info_texts,
            "message": "Info-Texte erfolgreich gespeichert"
        })
    except Exception as e:
        selection_logger.error(f"Error updating info texts: {e}")
        return jsonify({"success": False, "error": str(e)}), 500

@routes.route('/api/master-csv-status')
def master_csv_status():
    if os.path.exists(MASTER_CSV_PATH):
        stat = os.stat(MASTER_CSV_PATH)
        modified = datetime.fromtimestamp(stat.st_mtime).strftime('%d.%m.%Y %H:%M')
        return jsonify({
            'exists': True,
            'filename': 'master_medweb.csv',
            'modified': modified,
            'size': stat.st_size
        })
    return jsonify({'exists': False})

@routes.route('/upload-master-csv', methods=['POST'])
@admin_required
def upload_master_csv():
    if 'file' not in request.files:
        return jsonify({"error": "Keine Datei ausgewählt"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Keine Datei ausgewählt"}), 400

    if not file.filename.lower().endswith('.csv'):
        return jsonify({"error": "Bitte CSV-Datei hochladen"}), 400

    try:
        file.save(MASTER_CSV_PATH)
        selection_logger.info(f"Master CSV uploaded: {MASTER_CSV_PATH}")
        return jsonify({
            "success": True,
            "message": "Master-CSV erfolgreich hochgeladen"
        })
    except Exception as e:
        return jsonify({"error": f"Upload fehlgeschlagen: {str(e)}"}), 500


def auto_preload_job():
    try:
        if not os.path.exists(MASTER_CSV_PATH):
            selection_logger.warning(f"Auto-preload skipped: No master CSV at {MASTER_CSV_PATH}")
            return

        selection_logger.info(f"Starting auto-preload from {MASTER_CSV_PATH}")

        result = preload_next_workday(MASTER_CSV_PATH, APP_CONFIG)

        if result['success']:
            selection_logger.info(
                f"Auto-preload successful: {result['target_date']}, "
                f"modalities={result['modalities_loaded']}, "
                f"workers={result['total_workers']}"
            )
        else:
            selection_logger.error(f"Auto-preload failed: {result['message']}")

    except Exception as e:
        selection_logger.error(f"Auto-preload exception: {str(e)}", exc_info=True)


@routes.route('/preload-from-master', methods=['POST'])
@admin_required
def preload_from_master():
    if not os.path.exists(MASTER_CSV_PATH):
        return jsonify({"error": "Keine Master-CSV vorhanden. Bitte zuerst hochladen."}), 400

    result = preload_next_workday(MASTER_CSV_PATH, APP_CONFIG)

    if result['success']:
        modalities_loaded = result.get('modalities_loaded', [])
        for modality in modalities_loaded:
            d = modality_data[modality]
            scheduled_path = d['scheduled_file_path']

            if os.path.exists(scheduled_path):
                try:
                    with pd.ExcelFile(scheduled_path, engine='openpyxl') as xls:
                        if 'Tabelle1' in xls.sheet_names:
                            df = pd.read_excel(xls, sheet_name='Tabelle1')

                            if 'TIME' in df.columns:
                                time_data = df['TIME'].apply(parse_time_range)
                                df['start_time'] = time_data.apply(lambda x: x[0])
                                df['end_time'] = time_data.apply(lambda x: x[1])
                                df['shift_duration'] = df.apply(
                                    lambda row: calculate_shift_duration_hours(row['start_time'], row['end_time']),
                                    axis=1
                                )

                            if 'PPL' in df.columns:
                                df['canonical_id'] = df['PPL'].apply(get_canonical_worker_id)

                            if 'counts_for_hours' not in df.columns:
                                df['counts_for_hours'] = True

                            staged_modality_data[modality]['working_hours_df'] = df
                            staged_modality_data[modality]['info_texts'] = []
                            staged_modality_data[modality]['total_work_hours'] = _calculate_total_work_hours(df)
                            staged_modality_data[modality]['last_modified'] = get_local_berlin_now()

                            backup_dataframe(modality, use_staged=True)
                            selection_logger.info(f"Staged data updated for {modality} from scheduled file after preload")

                except Exception as e:
                    selection_logger.error(f"Error loading staged data for {modality} after preload: {e}")

        return jsonify(result)
    return jsonify(result), 400


@routes.route('/upload', methods=['GET'])
@admin_required
def upload_file():
    """Admin dashboard page for CSV management and statistics."""
    modality = resolve_modality_from_request()
    d = modality_data[modality]

    all_worker_names = set()
    combined_skill_counts = {skill: {} for skill in SKILL_COLUMNS}

    for mod_key in allowed_modalities:
        mod_d = modality_data[mod_key]
        for skill in SKILL_COLUMNS:
            for worker, count in mod_d['skill_counts'].get(skill, {}).items():
                all_worker_names.add(worker)
                if worker not in combined_skill_counts[skill]:
                    combined_skill_counts[skill][worker] = 0
                combined_skill_counts[skill][worker] += count

    sum_counts = {}
    global_counts = {}
    global_weighted_counts = {}
    for worker in all_worker_names:
        total = sum(combined_skill_counts[skill].get(worker, 0) for skill in SKILL_COLUMNS)
        sum_counts[worker] = total

        canonical = get_canonical_worker_id(worker)
        global_counts[worker] = get_global_assignments(canonical)
        global_weighted_counts[worker] = get_global_weighted_count(canonical)

    combined_workers = sorted(all_worker_names)
    modality_stats = {}
    for worker in combined_workers:
        modality_stats[worker] = {
            skill: combined_skill_counts[skill].get(worker, 0)
            for skill in SKILL_COLUMNS
        }
        modality_stats[worker]['total'] = sum_counts.get(worker, 0)

    debug_info = (
        d['working_hours_df'].to_html(index=True)
        if d['working_hours_df'] is not None else "Keine Daten verfügbar"
    )

    checks = run_operational_checks('admin_view', force=True)

    return render_template(
        'upload.html',
        debug_info=debug_info,
        modality=modality,
        skill_counts=combined_skill_counts,
        sum_counts=sum_counts,
        global_counts=global_counts,
        global_weighted_counts=global_weighted_counts,
        combined_workers=combined_workers,
        modality_stats=modality_stats,
        operational_checks=checks,
        scheduler_config=APP_CONFIG.get('scheduler', {}),
    )

def run_operational_checks(context: str = 'unknown', force: bool = False) -> dict:
    results = []
    now = get_local_berlin_now().isoformat()

    try:
        with open("config.yaml", "r") as f:
            config = yaml.safe_load(f)
        results.append({'name': 'Config File', 'status': 'OK', 'detail': 'config.yaml is readable and valid YAML'})
    except Exception as e:
        results.append({'name': 'Config File', 'status': 'ERROR', 'detail': f'Failed to load config.yaml: {str(e)}'})

    try:
        scheduler_conf = APP_CONFIG.get('scheduler', {})
        reset_time = scheduler_conf.get('daily_reset_time', '07:30')
        preload_hour = scheduler_conf.get('auto_preload_time', 14)

        if not isinstance(preload_hour, int) or not (0 <= preload_hour <= 23):
            results.append({'name': 'Scheduler', 'status': 'ERROR', 'detail': f'Invalid auto_preload_time: {preload_hour} (must be 0-23)'})
        else:
            results.append({'name': 'Scheduler', 'status': 'OK', 'detail': f'Resets at {reset_time}, auto-preloads at {preload_hour}:00'})
    except Exception as e:
        results.append({'name': 'Scheduler', 'status': 'ERROR', 'detail': f'Failed to check scheduler config: {str(e)}'})

    try:
        admin_pw = get_admin_password()
        if not admin_pw:
            results.append({'name': 'Admin Password', 'status': 'WARNING', 'detail': 'Admin password is not set in config.yaml'})
        elif admin_pw == 'change_pw_for_live':
            results.append({'name': 'Admin Password', 'status': 'WARNING', 'detail': 'Admin password is still set to default value - change for production!'})
        else:
            results.append({'name': 'Admin Password', 'status': 'OK', 'detail': 'Admin password is configured'})
    except Exception as e:
        results.append({'name': 'Admin Password', 'status': 'ERROR', 'detail': f'Failed to check admin password: {str(e)}'})

    try:
        upload_folder = 'uploads'
        if not os.path.exists(upload_folder):
            results.append({'name': 'Upload Folder', 'status': 'WARNING', 'detail': f'Upload folder "{upload_folder}" does not exist (will be created on upload)'})
        elif not os.access(upload_folder, os.W_OK):
            results.append({'name': 'Upload Folder', 'status': 'ERROR', 'detail': f'Upload folder "{upload_folder}" is not writable'})
        else:
            file_count = len([f for f in os.listdir(upload_folder) if f.endswith('.xlsx')])
            results.append({'name': 'Upload Folder', 'status': 'OK', 'detail': f'Upload folder "{upload_folder}" is writable ({file_count} Excel files found)'})
    except Exception as e:
        results.append({'name': 'Upload Folder', 'status': 'ERROR', 'detail': f'Failed to check upload folder: {str(e)}'})

    try:
        modality_count = len(allowed_modalities)
        if modality_count == 0:
            results.append({'name': 'Modalities', 'status': 'ERROR', 'detail': 'No modalities configured in config.yaml'})
        else:
            results.append({'name': 'Modalities', 'status': 'OK', 'detail': f'{modality_count} modalities configured: {", ".join(allowed_modalities)}'})
    except Exception as e:
        results.append({'name': 'Modalities', 'status': 'ERROR', 'detail': f'Failed to check modalities: {str(e)}'})

    try:
        skill_count = len(SKILL_COLUMNS)
        if skill_count == 0:
            results.append({'name': 'Skills', 'status': 'ERROR', 'detail': 'No skills configured in config.yaml'})
        else:
            results.append({'name': 'Skills', 'status': 'OK', 'detail': f'{skill_count} skills configured: {", ".join(SKILL_COLUMNS)}'})
    except Exception as e:
        results.append({'name': 'Skills', 'status': 'ERROR', 'detail': f'Failed to check skills: {str(e)}'})

    try:
        total_workers = 0
        for mod in allowed_modalities:
            d = modality_data.get(mod, {})
            if d.get('working_hours_df') is not None:
                total_workers += len(d['working_hours_df']['PPL'].unique())

        if total_workers == 0:
            results.append({'name': 'Worker Data', 'status': 'WARNING', 'detail': 'No worker data loaded - upload an Excel file to get started'})
        else:
            results.append({'name': 'Worker Data', 'status': 'OK', 'detail': f'{total_workers} workers loaded across all modalities'})
    except Exception as e:
        results.append({'name': 'Worker Data', 'status': 'ERROR', 'detail': f'Failed to check worker data: {str(e)}'})

    return {
        'results': results,
        'context': context,
        'timestamp': now
    }

@routes.route('/load-today-from-master', methods=['POST'])
@admin_required
def load_today_from_master():
    if not os.path.exists(MASTER_CSV_PATH):
        return jsonify({"error": "Keine Master-CSV vorhanden. Bitte zuerst CSV hochladen."}), 400

    try:
        target_date = get_local_berlin_now()

        # Debug: Check CSV content before parsing
        try:
            vendor_mapping = APP_CONFIG.get('medweb_mapping', {})
            cols = vendor_mapping.get('columns', {
                'date': 'Datum',
                'activity': 'Beschreibung der Aktivität'
            })
            date_col = cols.get('date', 'Datum')
            activity_col = cols.get('activity', 'Beschreibung der Aktivität')

            try:
                debug_df = pd.read_csv(MASTER_CSV_PATH, sep=',', encoding='utf-8')
            except UnicodeDecodeError:
                debug_df = pd.read_csv(MASTER_CSV_PATH, sep=',', encoding='latin1')
            if date_col not in debug_df.columns:
                try:
                    debug_df = pd.read_csv(MASTER_CSV_PATH, sep=';', encoding='utf-8')
                except UnicodeDecodeError:
                    debug_df = pd.read_csv(MASTER_CSV_PATH, sep=';', encoding='latin1')

            available_dates = debug_df[date_col].unique().tolist() if date_col in debug_df.columns else []
            available_activities = debug_df[activity_col].unique().tolist() if activity_col in debug_df.columns else []
        except Exception as e:
            return jsonify({"error": f"CSV-Lesefehler: {str(e)}"}), 400

        modality_dfs = build_working_hours_from_medweb(
            MASTER_CSV_PATH,
            target_date,
            APP_CONFIG
        )

        if not modality_dfs:
            mapping_rules = APP_CONFIG.get('medweb_mapping', {}).get('rules', [])
            rule_matches = [r.get('match', '') for r in mapping_rules[:10]]
            matched_activities = []
            for activity in available_activities:
                for rule in mapping_rules:
                    if rule.get('match', '').lower() in str(activity).lower():
                        matched_activities.append(activity)
                        break

            return jsonify({
                "error": f"Keine Cortex-Daten für {target_date.strftime('%d.%m.%Y')} gefunden",
                "debug": {
                    "target_date": target_date.strftime('%d.%m.%Y'),
                    "dates_in_csv": available_dates[:10],
                    "activities_in_csv": available_activities[:10],
                    "mapping_rules": rule_matches,
                    "matched_activities": matched_activities[:10],
                }
            }), 400

        with lock:
            global_worker_data['weighted_counts'] = {}

            for modality, df in modality_dfs.items():
                d = modality_data[modality]
                d['draw_counts'] = {}
                d['skill_counts'] = {skill: {} for skill in SKILL_COLUMNS}
                d['WeightedCounts'] = {}
                global_worker_data['assignments_per_mod'][modality] = {}
                d['working_hours_df'] = df

                for worker in df['PPL'].unique():
                    d['draw_counts'][worker] = 0
                    d['WeightedCounts'][worker] = 0.0
                    for skill in SKILL_COLUMNS:
                        if skill not in d['skill_counts']:
                            d['skill_counts'][skill] = {}
                        d['skill_counts'][skill][worker] = 0

                d['info_texts'] = []
                d['last_uploaded_filename'] = f"master_{target_date.strftime('%Y%m%d')}.csv"

            save_state()

        workers_added = 0
        if SKILL_ROSTER_AUTO_IMPORT:
            workers_added = auto_populate_skill_roster(modality_dfs)

        return jsonify({
            "success": True,
            "message": f"Heute ({target_date.strftime('%d.%m.%Y')}) aus Master-CSV geladen",
            "modalities_loaded": list(modality_dfs.keys()),
            "total_workers": sum(len(df) for df in modality_dfs.values()),
            "workers_added_to_roster": workers_added
        })

    except Exception as e:
        return jsonify({"error": f"Fehler: {str(e)}"}), 500

@routes.route('/prep-next-day')
@admin_required
def prep_next_day():
    next_day = get_next_workday()

    roster = load_worker_skill_json()
    if roster is None:
        roster = {}
    worker_list = list(roster.keys())

    medweb_rules = APP_CONFIG.get('medweb_mapping', {}).get('rules', [])
    task_roles = []
    for rule in medweb_rules:
        rule_type = rule.get('type', 'gap' if rule.get('exclusion') else 'shift')
        hours_counting_config = APP_CONFIG.get('balancer', {}).get('hours_counting', {})
        if 'counts_for_hours' in rule:
            counts_for_hours = rule['counts_for_hours']
        elif rule_type == 'gap':
            counts_for_hours = hours_counting_config.get('gap_default', False)
        else:
            counts_for_hours = hours_counting_config.get('shift_default', True)

        # Extract modalities from skill_overrides if available (new structure)
        skill_overrides = rule.get('skill_overrides', {})
        derived_modalities = set()
        for key in skill_overrides.keys():
            if '_' in key:
                parts = key.split('_', 1)
                if len(parts) == 2:
                    mod = parts[1].lower()
                    if mod in allowed_modalities:
                        derived_modalities.add(mod)

        # Use derived modalities, falling back to legacy fields
        if derived_modalities:
            modalities_list = list(derived_modalities)
        elif rule.get('modalities'):
            modalities_list = rule.get('modalities', [])
        elif rule.get('modality'):
            modalities_list = [rule.get('modality')]
        else:
            modalities_list = []

        task_role = {
            'name': rule.get('match', ''),
            'type': rule_type,
            'exclusion': rule.get('exclusion', False),
            'modalities': modalities_list,
            'times': rule.get('times', {}),           # NEW: day-specific times
            'gaps': rule.get('gaps', {}),             # NEW: embedded gaps
            'skill_overrides': skill_overrides,
            'modifier': rule.get('modifier', 1.0),
            'schedule': rule.get('schedule', {}),
            'counts_for_hours': counts_for_hours,
        }
        task_roles.append(task_role)

    exclusion_rules = [r for r in task_roles if r.get('exclusion')]
    worker_skills = load_worker_skill_json()

    return render_template(
        'prep_next_day.html',
        target_date=next_day.strftime('%Y-%m-%d'),
        target_date_german=next_day.strftime('%d.%m.%Y'),
        is_next_day=True,
        skills=SKILL_COLUMNS,
        skill_settings=SKILL_SETTINGS,
        modalities=list(MODALITY_SETTINGS.keys()),
        modality_settings=MODALITY_SETTINGS,
        shift_times=APP_CONFIG.get('shift_times', {}),
        medweb_mapping=APP_CONFIG.get('medweb_mapping', {}),
        worker_list=worker_list,
        worker_skills=worker_skills,
        task_roles=task_roles,
        exclusion_rules=exclusion_rules,
        skill_value_colors=APP_CONFIG.get('skill_value_colors', {}),
        ui_colors=APP_CONFIG.get('ui_colors', {})
    )

@routes.route('/api/prep-next-day/data', methods=['GET'])
@admin_required
def get_prep_data():
    result = {}

    for modality in allowed_modalities:
        if staged_modality_data[modality]['working_hours_df'] is None:
            if not load_staged_dataframe(modality):
                if modality_data[modality]['working_hours_df'] is not None:
                    staged_modality_data[modality]['working_hours_df'] = modality_data[modality]['working_hours_df'].copy()
                    staged_modality_data[modality]['info_texts'] = modality_data[modality]['info_texts'].copy()
                    backup_dataframe(modality, use_staged=True)

        df = staged_modality_data[modality].get('working_hours_df')
        result[modality] = _df_to_api_response(df)

    return jsonify({
        'modalities': result,
        'last_prepped_at': staged_modality_data[allowed_modalities[0]].get('last_prepped_at')
    })

@routes.route('/api/prep-next-day/update-row', methods=['POST'])
@admin_required
def update_prep_row():
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    updates = data.get('updates', {})

    if modality not in staged_modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, error = _update_schedule_row(modality, row_index, updates, use_staged=True)

    if success:
        return jsonify({'success': True})
    return jsonify({'error': error}), 400

@routes.route('/api/prep-next-day/add-worker', methods=['POST'])
@admin_required
def add_prep_worker():
    data = request.json
    modality = data.get('modality')
    worker_data = data.get('worker_data', {})

    if modality not in staged_modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, row_index, error = _add_worker_to_schedule(modality, worker_data, use_staged=True)

    if success:
        return jsonify({'success': True, 'row_index': row_index})
    return jsonify({'error': error}), 400

@routes.route('/api/prep-next-day/delete-worker', methods=['POST'])
@admin_required
def delete_prep_worker():
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    verify_ppl = data.get('verify_ppl')

    if modality not in staged_modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, worker_name, error = _delete_worker_from_schedule(modality, row_index, use_staged=True, verify_ppl=verify_ppl)

    if success:
        return jsonify({'success': True})
    return jsonify({'error': error}), 400

@routes.route('/api/live-schedule/data', methods=['GET'])
@admin_required
def get_live_data():
    result = {}
    for modality in allowed_modalities:
        df = modality_data[modality].get('working_hours_df')
        result[modality] = _df_to_api_response(df)
    return jsonify(result)

@routes.route('/api/live-schedule/update-row', methods=['POST'])
@admin_required
def update_live_row():
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    updates = data.get('updates', {})

    if modality not in modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, error = _update_schedule_row(modality, row_index, updates, use_staged=False)

    if success:
        selection_logger.info(f"Live schedule updated for {modality}, row {row_index} (no counter reset)")
        return jsonify({'success': True})
    return jsonify({'error': error}), 400

@routes.route('/api/live-schedule/add-worker', methods=['POST'])
@admin_required
def add_live_worker():
    data = request.json
    modality = data.get('modality')
    worker_data = data.get('worker_data', {})

    if modality not in modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    ppl_name = worker_data.get('PPL', 'Neuer Worker (NW)')
    success, row_index, error = _add_worker_to_schedule(modality, worker_data, use_staged=False)

    if success:
        d = modality_data[modality]
        if ppl_name not in d['draw_counts']:
            d['draw_counts'][ppl_name] = 0
        if ppl_name not in d['WeightedCounts']:
            d['WeightedCounts'][ppl_name] = 0.0
        for skill in SKILL_COLUMNS:
            if skill not in d['skill_counts']:
                d['skill_counts'][skill] = {}
            if ppl_name not in d['skill_counts'][skill]:
                d['skill_counts'][skill][ppl_name] = 0

        selection_logger.info(f"Worker {ppl_name} added to LIVE {modality} schedule (no counter reset)")
        return jsonify({'success': True, 'row_index': row_index})

    return jsonify({'error': error}), 400

@routes.route('/api/live-schedule/delete-worker', methods=['POST'])
@admin_required
def delete_live_worker():
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    verify_ppl = data.get('verify_ppl')

    if modality not in modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, worker_name, error = _delete_worker_from_schedule(modality, row_index, use_staged=False, verify_ppl=verify_ppl)

    if success:
        selection_logger.info(f"Worker {worker_name} deleted from LIVE {modality} schedule (no counter reset)")
        return jsonify({'success': True})

    return jsonify({'error': error}), 400

@routes.route('/api/live-schedule/add-gap', methods=['POST'])
@admin_required
def add_live_gap():
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    gap_type = data.get('gap_type', 'custom')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')

    if modality not in modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, action, error = _add_gap_to_schedule(modality, row_index, gap_type, gap_start, gap_end, use_staged=False)

    if success:
        return jsonify({'success': True, 'action': action})
    return jsonify({'error': error}), 400

@routes.route('/api/prep-next-day/add-gap', methods=['POST'])
@admin_required
def add_staged_gap():
    data = request.json
    modality = data.get('modality')
    row_index = data.get('row_index')
    gap_type = data.get('gap_type', 'custom')
    gap_start = data.get('gap_start')
    gap_end = data.get('gap_end')

    if modality not in staged_modality_data:
        return jsonify({'error': 'Invalid modality'}), 400

    success, action, error = _add_gap_to_schedule(modality, row_index, gap_type, gap_start, gap_end, use_staged=True)

    if success:
        return jsonify({'success': True, 'action': action})
    return jsonify({'error': error}), 400

def _assign_worker(modality: str, role: str, allow_fallback: bool = True):
    try:
        now = get_local_berlin_now()
        selection_logger.info(
            "Assignment request: modality=%s, role=%s, strict=%s, time=%s",
            modality,
            role,
            not allow_fallback,
            now.strftime('%H:%M:%S'),
        )

        with lock:
            result = get_next_available_worker(
                now,
                role=role,
                modality=modality,
                allow_fallback=allow_fallback,
            )
            if result is not None:
                candidate, used_column, source_modality = result
                actual_modality = source_modality or modality
                d = modality_data[actual_modality]

                candidate = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
                if "PPL" not in candidate:
                    raise ValueError("Candidate row is missing the 'PPL' field")
                person = candidate['PPL']

                actual_skill = candidate.get('__skill_source')
                if not actual_skill and isinstance(used_column, str):
                    actual_skill = used_column
                if not actual_skill:
                    actual_skill = role

                selection_logger.info(
                    "Selected worker: %s using column %s (modality %s)",
                    person,
                    actual_skill,
                    actual_modality,
                )

                d['draw_counts'][person] = d['draw_counts'].get(person, 0) + 1
                if actual_skill in SKILL_COLUMNS:
                    if actual_skill not in d['skill_counts']:
                        d['skill_counts'][actual_skill] = {}
                    if person not in d['skill_counts'][actual_skill]:
                        d['skill_counts'][actual_skill][person] = 0
                    d['skill_counts'][actual_skill][person] += 1

                canonical_id = update_global_assignment(person, actual_skill, actual_modality)

                # Record skill-modality usage for analytics
                usage_logger.record_skill_modality_usage(actual_skill, actual_modality)

                # Check if it's time for scheduled export (7:30 AM)
                usage_logger.check_and_export_at_scheduled_time()

                return jsonify({
                    "selected_person": person,
                    "canonical_id": canonical_id,
                    "source_modality": actual_modality,
                    "skill_used": actual_skill
                })
            else:
                selection_logger.warning("No available worker found")
                return jsonify({"error": "No available worker found"}), 404

    except Exception as e:
        selection_logger.error(f"Error selecting worker: {str(e)}", exc_info=True)
        return jsonify({"error": str(e)}), 500

@routes.route('/api/<modality>/<role>', methods=['GET'])
@access_required
def assign_worker_api(modality, role):
    modality = modality.lower()
    if modality not in modality_data:
        return jsonify({"error": "Invalid modality"}), 400
    return _assign_worker(modality, role)

@routes.route('/api/<modality>/<role>/strict', methods=['GET'])
@access_required
def assign_worker_strict_api(modality, role):
    modality = modality.lower()
    if modality not in modality_data:
        return jsonify({"error": "Invalid modality"}), 400
    return _assign_worker(modality, role, allow_fallback=False)

# Usage Statistics API Endpoints

@routes.route('/api/usage-stats/current', methods=['GET'])
@admin_required
def get_current_usage_stats():
    """Get current daily usage statistics for skill-modality combinations."""
    stats = usage_logger.get_current_usage_stats()

    # Convert to list format for easier consumption
    stats_list = [
        {
            'skill': skill,
            'modality': modality,
            'count': count
        }
        for (skill, modality), count in sorted(stats.items())
    ]

    return jsonify({
        'date': datetime.now().strftime('%Y-%m-%d'),
        'total_combinations': len(stats_list),
        'total_usages': sum(s['count'] for s in stats_list),
        'stats': stats_list
    })

@routes.route('/api/usage-stats/export', methods=['POST'])
@admin_required
def export_usage_stats():
    """Manually trigger export of current usage statistics to CSV (wide format)."""
    try:
        csv_path = usage_logger.export_current_usage()
        if csv_path:
            return jsonify({
                'success': True,
                'message': 'Usage statistics exported successfully (appended to CSV)',
                'file_path': str(csv_path),
                'date': datetime.now().strftime('%Y-%m-%d'),
                'note': 'Data appended as new row in wide format CSV'
            })
        else:
            return jsonify({
                'success': False,
                'message': 'No usage data to export'
            })
    except Exception as e:
        selection_logger.error(f"Error exporting usage stats: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@routes.route('/api/usage-stats/reset', methods=['POST'])
@admin_required
def reset_usage_stats():
    """Reset current usage statistics (use with caution)."""
    try:
        usage_logger.reset_daily_usage()
        return jsonify({
            'success': True,
            'message': 'Usage statistics reset successfully'
        })
    except Exception as e:
        selection_logger.error(f"Error resetting usage stats: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@routes.route('/api/usage-stats/file', methods=['GET'])
@admin_required
def get_usage_stats_file_info():
    """Get information about the usage statistics CSV file."""
    try:
        csv_path = usage_logger.USAGE_STATS_FILE

        if not csv_path.exists():
            return jsonify({
                'success': True,
                'exists': False,
                'message': 'No usage statistics file exists yet'
            })

        # Read dates from the CSV
        import csv
        dates = []
        with open(csv_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if 'date' in row:
                    dates.append(row['date'])

        return jsonify({
            'success': True,
            'exists': True,
            'filename': csv_path.name,
            'path': str(csv_path),
            'size_bytes': csv_path.stat().st_size,
            'total_days': len(dates),
            'dates': dates,
            'date_range': {
                'first': dates[0] if dates else None,
                'last': dates[-1] if dates else None
            }
        })
    except Exception as e:
        selection_logger.error(f"Error getting usage stats file info: {e}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
