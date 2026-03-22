import os
import re
import csv
import io
import json
from datetime import datetime
from functools import wraps
from flask import (Flask, render_template, jsonify, request, redirect,
                   url_for, session, send_file, flash)

app = Flask(__name__)

# --- Password protection ---
DEFAULT_PASSWORD = 'studs2024'
app.secret_key = 'studs-secret-key-change-in-production'

INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'input')
PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processed')
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')

# --- Status constants ---
STATUS_UPDATED = "Updated"
STATUS_DISCREPANCY = "Discrepancy Detected"
STATUS_INCOMPLETE = "Incomplete — Missing File"
STATUS_INCOMPLETE_FORMAT = "Incomplete — Unrecognized File Format"

# --- Default email template ---
DEFAULT_EMAIL_BODY = (
    "We recently completed an inventory audit and found discrepancies in the following SKUs "
    "at your location. Please review and reconcile these items at your earliest convenience.\n\n"
    "{{sku_table}}\n\n"
    "Please confirm once these have been addressed.\n\n"
    "Thank you,\nInventory Management Team"
)

# --- File pattern regexes ---
RE_SKU_LIST = re.compile(r'^SKUList_(\d{2}_\d{2}_\d{2})\.csv$')
RE_VARIANCE = re.compile(r'^(\d+)_Variance(?:_\d{2}[-_]\d{2}[-_]\d{2})?\.csv$')
RE_AUDIT_TRAIL = re.compile(r'^AuditTrail_(\d{2}[-_]\d{2}[-_]\d{2})\.csv$')

# --- Expected variance file columns (all lowercase; parse_csv lowercases headers) ---
VARIANCE_COLUMNS = {'sku', 'description', 'counted units', 'onhand units', 'unit variance'}

# --- SKU exclusion ---
RE_RS_PREFIX = re.compile(r'^RS', re.IGNORECASE)


def is_excluded_sku(sku):
    """Return True if this SKU should be excluded (starts with RS)."""
    return bool(RE_RS_PREFIX.match(sku))


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def load_settings():
    """Load settings from JSON file."""
    defaults = {
        'email_body_template': DEFAULT_EMAIL_BODY,
        'store_emails': {},
        'app_password': DEFAULT_PASSWORD,
    }
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                saved = json.load(f)
            defaults.update(saved)
        except (json.JSONDecodeError, IOError):
            pass
    return defaults


def save_settings(settings):
    """Save settings to JSON file."""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=2)


def clean_csv_content(raw_bytes):
    """Strip BOM, normalize line endings, decode to string."""
    if raw_bytes.startswith(b'\xef\xbb\xbf'):
        raw_bytes = raw_bytes[3:]
    text = raw_bytes.decode('utf-8', errors='replace')
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    return text


def parse_csv(filepath):
    """Read a CSV file, stripping BOM and whitespace from headers and values."""
    with open(filepath, 'rb') as f:
        raw = f.read()
    text = clean_csv_content(raw)
    reader = csv.DictReader(io.StringIO(text))
    reader.fieldnames = [h.strip().lower() for h in reader.fieldnames]
    rows = []
    for row in reader:
        cleaned = {k.strip().lower(): v.strip() for k, v in row.items()}
        rows.append(cleaned)
    return rows


def scan_input_files():
    """Scan /input/ and classify files by regex."""
    sku_lists = []
    variance_files = {}
    audit_trails = []
    warnings = []
    unrecognized = []

    if not os.path.isdir(INPUT_DIR):
        warnings.append("Input directory does not exist.")
        return {
            'sku_lists': sku_lists,
            'variance_files': variance_files,
            'audit_trails': audit_trails,
            'warnings': warnings,
            'unrecognized': unrecognized,
        }

    for filename in os.listdir(INPUT_DIR):
        filepath = os.path.join(INPUT_DIR, filename)
        if not os.path.isfile(filepath):
            continue

        m_sku = RE_SKU_LIST.match(filename)
        m_var = RE_VARIANCE.match(filename)
        m_audit = RE_AUDIT_TRAIL.match(filename)

        if m_sku:
            sku_lists.append((filename, m_sku.group(1)))
        elif m_var:
            store_id = m_var.group(1).zfill(3)  # Normalize: zero-pad to 3 digits
            variance_files[store_id] = filename
        elif m_audit:
            audit_trails.append((filename, m_audit.group(1)))
        else:
            unrecognized.append(filename)

    if len(sku_lists) > 1:
        sku_lists.sort(key=lambda x: x[1], reverse=True)
        warnings.append(f"Multiple SKU lists found. Using most recent: {sku_lists[0][0]}")
    if len(audit_trails) > 1:
        audit_trails.sort(key=lambda x: x[1], reverse=True)
        warnings.append(f"Multiple audit trails found. Using most recent: {audit_trails[0][0]}")

    if not sku_lists:
        warnings.append("No weekly SKU list file found. Stores cannot be reconciled.")
    if not audit_trails:
        warnings.append("No audit trail file found. Stores cannot be reconciled.")

    return {
        'sku_lists': sku_lists,
        'variance_files': variance_files,
        'audit_trails': audit_trails,
        'warnings': warnings,
        'unrecognized': unrecognized,
    }


def load_sku_list(filepath):
    """Load the weekly SKU list. Returns a set of SKU strings (excluding RS SKUs)."""
    rows = parse_csv(filepath)
    skus = set()
    for row in rows:
        sku = row.get('sku', '').strip()
        if sku and not is_excluded_sku(sku):
            skus.add(sku)
    return skus


def load_variance(filepath):
    """Load a per-store variance file. Validates expected columns before processing.
    Requires format: Sku, Description, Counted Units, Onhand Units, Unit Variance.
    Returns None if the file has an unrecognized schema."""
    filename = os.path.basename(filepath)
    rows = parse_csv(filepath)
    if not rows:
        return []

    headers = set(rows[0].keys())

    missing = VARIANCE_COLUMNS - headers
    if missing:
        print(f"[STUDS] WARNING: {filename} — unrecognized variance file schema. "
              f"Missing expected columns: {', '.join(sorted(missing))}")
        return None

    result = []
    for row in rows:
        sku = row.get('sku', '').strip()
        if not sku or is_excluded_sku(sku):
            continue
        try:
            quantity = int(float(row.get('unit variance', '0').strip() or '0'))
        except (ValueError, TypeError):
            quantity = 0
        result.append({
            'product_id': '',
            'sku': sku,
            'quantity': quantity,
            'location': '',
            'item_cost_price': 0.0,
        })
    return result


def parse_warehouse_id(warehouse_str):
    """Extract numeric store ID from warehouse string like '033 CA Fashion Island'.
    Returns the numeric prefix zero-padded to 3 digits for consistent matching."""
    m = re.match(r'^(\d+)', warehouse_str.strip())
    if m:
        return m.group(1).zfill(3)  # Zero-pad to 3 digits
    return warehouse_str.strip()


def load_audit_trail(filepath):
    """Load global audit trail. Returns list of dicts with parsed fields.
    Parses Warehouse column to extract store ID and full store name."""
    rows = parse_csv(filepath)
    result = []
    for row in rows:
        sku = row.get('sku', '').strip()
        if not sku or is_excluded_sku(sku):
            continue
        ref = row.get('reference', '').strip()
        try:
            qty = int(float(row.get('quantity', '0').strip() or '0'))
        except (ValueError, TypeError):
            qty = 0
        warehouse_raw = row.get('warehouse', '').strip()
        store_id = parse_warehouse_id(warehouse_raw)
        result.append({
            'product_id': row.get('product id', '').strip(),
            'sku': sku,
            'product_name': row.get('product name', '').strip(),
            'options': row.get('options', '').strip(),
            'quantity': qty,
            'price': row.get('price', '').strip(),
            'reference': ref,
            'warehouse': store_id,
            'warehouse_raw': warehouse_raw,
            'date': row.get('date', '').strip(),
            'movement_id': row.get('movement id', '').strip(),
        })
    return result


def build_store_name_map(audit_rows):
    """Build a mapping of store_id -> full warehouse name from audit trail data."""
    store_names = {}
    for row in audit_rows:
        wh_raw = row.get('warehouse_raw', '')
        store_id = row.get('warehouse', '')
        if wh_raw and store_id and store_id not in store_names:
            store_names[store_id] = wh_raw
    return store_names


def get_audit_date_range(audit_rows):
    """Return (min_date_str, max_date_str) from audit trail rows."""
    dates = [r['date'] for r in audit_rows if r['date']]
    if not dates:
        return (None, None)
    return (min(dates), max(dates))


def reconcile_store(store_id, weekly_skus, variance_data, audit_rows):
    """Reconcile a single store."""
    variance_skus = {item['sku'] for item in variance_data}
    active_skus = {s for s in (weekly_skus & variance_skus) if not is_excluded_sku(s)}

    variance_lookup = {item['sku']: item for item in variance_data}

    store_audit = [
        r for r in audit_rows
        if r['warehouse'] == store_id
        and ('stock update' in r['reference'].lower() or 'stock check' in r['reference'].lower())
    ]

    audit_by_sku = {}
    for r in store_audit:
        audit_by_sku[r['sku']] = audit_by_sku.get(r['sku'], 0) + r['quantity']

    sku_details = []
    discrepancy_count = 0
    net_discrepancy = 0

    for sku in sorted(active_skus):
        var_item = variance_lookup[sku]
        required_push = var_item['quantity']
        actual_push = audit_by_sku.get(sku, 0)
        discrepancy = required_push - actual_push

        detail = {
            'sku': sku,
            'product_id': var_item['product_id'],
            'quantity': required_push,
            'location': var_item['location'],
            'item_cost_price': var_item['item_cost_price'],
            'actual_push': actual_push,
            'discrepancy': discrepancy,
        }
        sku_details.append(detail)

        if discrepancy != 0:
            discrepancy_count += 1
            net_discrepancy += discrepancy

    if discrepancy_count > 0:
        status = STATUS_DISCREPANCY
    else:
        status = STATUS_UPDATED

    return {
        'store_id': store_id,
        'status': status,
        'active_sku_count': len(active_skus),
        'discrepancy_count': discrepancy_count,
        'net_discrepancy': net_discrepancy,
        'sku_details': [d for d in sku_details if d['discrepancy'] != 0],
        'all_sku_details': sku_details,
    }


def run_reconciliation():
    """Full reconciliation pipeline."""
    scan = scan_input_files()
    warnings = list(scan['warnings'])
    stores = []
    sku_list_filename = None
    sku_count = 0
    audit_date_min = None
    audit_date_max = None

    weekly_skus = set()
    if scan['sku_lists']:
        sku_list_filename = scan['sku_lists'][0][0]
        try:
            weekly_skus = load_sku_list(os.path.join(INPUT_DIR, sku_list_filename))
            sku_count = len(weekly_skus)
        except Exception as e:
            warnings.append(f"Failed to parse SKU list: {e}")

    audit_rows = []
    audit_filename = None
    if scan['audit_trails']:
        audit_filename = scan['audit_trails'][0][0]
        try:
            audit_rows = load_audit_trail(os.path.join(INPUT_DIR, audit_filename))
            audit_date_min, audit_date_max = get_audit_date_range(audit_rows)
        except Exception as e:
            warnings.append(f"Failed to parse audit trail: {e}")

    store_names = build_store_name_map(audit_rows)

    can_reconcile = bool(weekly_skus) and len(scan.get('audit_trails', [])) > 0

    all_store_ids = set(scan['variance_files'].keys())
    for row in audit_rows:
        wh = row['warehouse']
        if wh:
            all_store_ids.add(wh)

    for store_id in sorted(all_store_ids, key=lambda x: x.zfill(10) if x.isdigit() else x):
        store_name = store_names.get(store_id, store_id)

        if store_id not in scan['variance_files']:
            stores.append({
                'store_id': store_id,
                'store_name': store_name,
                'status': STATUS_INCOMPLETE,
                'active_sku_count': 0,
                'discrepancy_count': 0,
                'net_discrepancy': 0,
                'sku_details': [],
                'all_sku_details': [],
            })
            continue
        if not can_reconcile:
            stores.append({
                'store_id': store_id,
                'store_name': store_name,
                'status': STATUS_INCOMPLETE,
                'active_sku_count': 0,
                'discrepancy_count': 0,
                'net_discrepancy': 0,
                'sku_details': [],
                'all_sku_details': [],
            })
            continue

        variance_filename = scan['variance_files'][store_id]
        try:
            variance_data = load_variance(os.path.join(INPUT_DIR, variance_filename))
        except Exception as e:
            warnings.append(f"Failed to parse {variance_filename}: {e}")
            stores.append({
                'store_id': store_id,
                'store_name': store_name,
                'status': STATUS_INCOMPLETE,
                'active_sku_count': 0,
                'discrepancy_count': 0,
                'net_discrepancy': 0,
                'sku_details': [],
                'all_sku_details': [],
            })
            continue

        if variance_data is None:
            stores.append({
                'store_id': store_id,
                'store_name': store_name,
                'status': STATUS_INCOMPLETE_FORMAT,
                'active_sku_count': 0,
                'discrepancy_count': 0,
                'net_discrepancy': 0,
                'sku_details': [],
                'all_sku_details': [],
            })
            continue

        result = reconcile_store(store_id, weekly_skus, variance_data, audit_rows)
        result['store_name'] = store_name
        stores.append(result)

    count_updated = sum(1 for s in stores if s['status'] == STATUS_UPDATED)
    count_discrepancy = sum(1 for s in stores if s['status'] == STATUS_DISCREPANCY)
    count_incomplete = sum(1 for s in stores if s['status'] in (STATUS_INCOMPLETE, STATUS_INCOMPLETE_FORMAT))

    return {
        'stores': stores,
        'warnings': warnings,
        'sku_list_filename': sku_list_filename,
        'sku_count': sku_count,
        'audit_date_min': audit_date_min,
        'audit_date_max': audit_date_max,
        'total_stores': len(stores),
        'count_updated': count_updated,
        'count_discrepancy': count_discrepancy,
        'count_incomplete': count_incomplete,
        'last_loaded': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# --- Flask routes ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        settings = load_settings()
        if request.form.get('password', '').strip() == settings.get('app_password', DEFAULT_PASSWORD):
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            flash('Incorrect password.', 'error')
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))


@app.route('/')
@login_required
def index():
    results = run_reconciliation()
    settings = load_settings()
    return render_template('index.html', data=results, settings=settings)


@app.route('/refresh', methods=['POST'])
@login_required
def refresh():
    results = run_reconciliation()
    return jsonify(results)


@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload():
    if request.method == 'POST':
        files = request.files.getlist('files')
        uploaded = []
        for f in files:
            if f.filename:
                filepath = os.path.join(INPUT_DIR, f.filename)
                f.save(filepath)
                uploaded.append(f.filename)
        if uploaded:
            flash(f'Uploaded {len(uploaded)} file(s): {", ".join(uploaded)}', 'success')
        return redirect(url_for('upload'))

    # List current files in /input/
    current_files = []
    if os.path.isdir(INPUT_DIR):
        for fname in sorted(os.listdir(INPUT_DIR)):
            fpath = os.path.join(INPUT_DIR, fname)
            if os.path.isfile(fpath):
                mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                size_kb = os.path.getsize(fpath) / 1024
                current_files.append({
                    'name': fname,
                    'modified': mtime.strftime('%Y-%m-%d %H:%M:%S'),
                    'size': f'{size_kb:.1f} KB',
                })
    return render_template('upload.html', files=current_files)


@app.route('/delete-file', methods=['POST'])
@login_required
def delete_file():
    filename = request.form.get('filename', '')
    if not filename or '/' in filename or '..' in filename:
        flash('Invalid filename.', 'error')
        return redirect(url_for('upload'))
    filepath = os.path.join(INPUT_DIR, filename)
    if os.path.isfile(filepath):
        os.remove(filepath)
        flash(f'Deleted {filename}.', 'success')
    else:
        flash(f'File not found: {filename}', 'error')
    return redirect(url_for('upload'))


@app.route('/delete-all-files', methods=['POST'])
@login_required
def delete_all_files():
    count = 0
    if os.path.isdir(INPUT_DIR):
        for fname in os.listdir(INPUT_DIR):
            fpath = os.path.join(INPUT_DIR, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)
                count += 1
    flash(f'Deleted {count} file(s) from /input/.', 'success')
    return redirect(url_for('upload'))


@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_page():
    settings = load_settings()
    if request.method == 'POST':
        settings['email_body_template'] = request.form.get('email_body_template', DEFAULT_EMAIL_BODY)
        # Handle password change
        new_password = request.form.get('new_password', '').strip()
        password_changed = False
        if new_password:
            settings['app_password'] = new_password
            password_changed = True
        # Save per-store emails
        store_emails = {}
        for key, val in request.form.items():
            if key.startswith('store_email_'):
                store_id = key.replace('store_email_', '')
                store_emails[store_id] = val.strip()
        settings['store_emails'] = store_emails
        save_settings(settings)
        if password_changed:
            flash('Settings saved. Password has been updated — use the new password on next login.', 'success')
        else:
            flash('Settings saved.', 'success')
        return redirect(url_for('settings_page'))

    # Get all store IDs for email configuration
    results = run_reconciliation()
    return render_template('settings.html', settings=settings, stores=results['stores'])


@app.route('/email-draft/<store_id>')
@login_required
def email_draft(store_id):
    results = run_reconciliation()
    settings = load_settings()

    store = None
    for s in results['stores']:
        if s['store_id'] == store_id:
            store = s
            break

    if not store:
        return "Store not found", 404

    store_name = store.get('store_name', store_id)
    store_email = settings.get('store_emails', {}).get(store_id, '')

    # Build SKU list
    sku_lines = []
    for d in store.get('sku_details', []):
        sku_lines.append(
            f"- SKU: {d['sku']} | Required Adjustment: {d['quantity']} "
            f"| Actual Adjustment: {d['actual_push']} | Discrepancy: {d['discrepancy']}"
        )
    sku_list = "\n".join(sku_lines) if sku_lines else "(No specific discrepancies)"

    subject = f"{store_name} — Stock Check Discrepancy"
    body = (
        f"Hi {store_name},\n\n"
        "We recently completed an inventory audit based on your most recent stock check "
        "and found discrepancies in the following SKUs at your location. Please review and "
        "adjust these items at your earliest convenience using reason code \"Stock Check\".\n\n"
        f"{sku_list}\n\n"
        "Please email logistics@studs.com to confirm once these have been addressed.\n\n"
        "Cheers,\nLogistics"
    )

    draft = {
        'to': store_email,
        'subject': subject,
        'body': body,
        'store_name': store_name,
    }
    return jsonify(draft)


@app.route('/export')
@login_required
def export_csv():
    results = run_reconciliation()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        'Store ID', 'Store Name', 'Status', 'SKU', 'Product ID',
        'Required Push', 'Location', 'Item Cost Price',
        'Actual Push', 'Discrepancy'
    ])

    for store in results['stores']:
        if store.get('all_sku_details'):
            for d in store['all_sku_details']:
                writer.writerow([
                    store['store_id'],
                    store.get('store_name', ''),
                    store['status'],
                    d['sku'],
                    d.get('product_id', ''),
                    d['quantity'],
                    d.get('location', ''),
                    d.get('item_cost_price', ''),
                    d['actual_push'],
                    d['discrepancy'],
                ])
        else:
            writer.writerow([
                store['store_id'],
                store.get('store_name', ''),
                store['status'],
                '', '', '', '', '', '', '',
            ])

    output.seek(0)
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        io.BytesIO(output.getvalue().encode('utf-8')),
        mimetype='text/csv',
        as_attachment=True,
        download_name=f'STUDS_Dashboard_Export_{timestamp}.csv',
    )


if __name__ == '__main__':
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    print(f"[STUDS Stock Check] Input directory: {INPUT_DIR}")
    print(f"[STUDS Stock Check] Starting on http://localhost:5000")
    app.run(debug=True, host='127.0.0.1', port=5000)
