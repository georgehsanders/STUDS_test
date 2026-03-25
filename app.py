import os
import re
import csv
import io
import json
import sqlite3
from datetime import datetime
from functools import wraps
import bcrypt
import pytz
from flask import (Flask, render_template, jsonify, request, redirect,
                   url_for, session, send_file, send_from_directory, flash)

app = Flask(__name__)

# --- Authentication ---
ADMIN_USERNAME = 'hq'
ADMIN_PASSWORD = 'hq'
app.secret_key = 'studs-secret-key-change-in-production'

INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'input')
PROCESSED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'processed')
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
DATABASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'database')
MASTER_DIR = os.path.join(DATABASE_DIR, 'master')
IMAGES_DIR = os.path.join(DATABASE_DIR, 'images')
STORE_DB = os.path.join(DATABASE_DIR, 'store_profiles.db')
ARCHIVE_DB = os.path.join(DATABASE_DIR, 'archive.db')

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
RE_SKU_LIST = re.compile(r'^SKU[_ ]?[Ll]ist[-_](\d{2}[-_]\d{2}[-_]\d{2})\.csv$', re.IGNORECASE)
RE_VARIANCE = re.compile(r'^(\d+)_Variance(?:_\d{2}[-_]\d{2}[-_]\d{2})?(?:_.+)?\.csv$')
RE_AUDIT_TRAIL = re.compile(r'^AuditTrail_(\d{2}[-_]\d{2}[-_]\d{2})\.csv$')

# --- Expected variance file columns (all lowercase; parse_csv lowercases headers) ---
VARIANCE_COLUMNS = {'sku', 'description', 'counted units', 'onhand units', 'unit variance'}

# --- SKU exclusion ---
RE_RS_PREFIX = re.compile(r'^RS', re.IGNORECASE)


def is_excluded_sku(sku):
    """Return True if this SKU should be excluded (starts with RS)."""
    return bool(RE_RS_PREFIX.match(sku))


# --- Store profiles database ---

SEED_STORES = [
    ("001", "001 NY SoHo", "America/New_York"),
    ("002", "002 NY Williamsburg", "America/New_York"),
    ("003", "003 NY Upper East Side", "America/New_York"),
    ("004", "004 NY Hudson Yards", "America/New_York"),
    ("005", "005 NY Flatiron", "America/New_York"),
    ("006", "006 NJ Garden State Plaza", "America/New_York"),
    ("007", "007 NJ Short Hills", "America/New_York"),
    ("008", "008 CT Westfield", "America/New_York"),
    ("009", "009 MA Newbury Street", "America/New_York"),
    ("010", "010 MA Burlington", "America/New_York"),
    ("011", "011 PA King of Prussia", "America/New_York"),
    ("012", "012 PA Rittenhouse", "America/New_York"),
    ("013", "013 DC Georgetown", "America/New_York"),
    ("014", "014 FL Aventura", "America/New_York"),
    ("015", "015 FL Dadeland", "America/New_York"),
    ("016", "016 FL Sawgrass", "America/New_York"),
    ("017", "017 FL International Plaza", "America/New_York"),
    ("018", "018 GA Lenox Square", "America/New_York"),
    ("019", "019 GA Avalon", "America/New_York"),
    ("020", "020 TX NorthPark", "America/Chicago"),
    ("021", "021 TX Domain", "America/Chicago"),
    ("022", "022 TX Galleria", "America/Chicago"),
    ("023", "023 IL Michigan Ave", "America/Chicago"),
    ("024", "024 IL Oakbrook", "America/Chicago"),
    ("025", "025 MN Mall of America", "America/Chicago"),
    ("026", "026 CO Cherry Creek", "America/Denver"),
    ("027", "027 CO Park Meadows", "America/Denver"),
    ("028", "028 AZ Scottsdale Fashion", "America/Phoenix"),
    ("029", "029 AZ Biltmore", "America/Phoenix"),
    ("030", "030 NV Fashion Show", "America/Los_Angeles"),
    ("031", "031 CA Beverly Center", "America/Los_Angeles"),
    ("032", "032 CA Century City", "America/Los_Angeles"),
    ("033", "033 CA Fashion Island", "America/Los_Angeles"),
    ("034", "034 CA Stanford", "America/Los_Angeles"),
    ("035", "035 CA UTC San Diego", "America/Los_Angeles"),
    ("036", "036 CA Santa Monica", "America/Los_Angeles"),
    ("037", "037 WA Bellevue Square", "America/Los_Angeles"),
    ("038", "038 WA University Village", "America/Los_Angeles"),
    ("039", "039 OR Pioneer Place", "America/Los_Angeles"),
    ("040", "040 HI Ala Moana", "Pacific/Honolulu"),
]


def get_db():
    """Get a SQLite connection to the store profiles database."""
    conn = sqlite3.connect(STORE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_store_db():
    """Create and seed the store profiles database if it doesn't exist."""
    if os.path.exists(STORE_DB):
        return
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = sqlite3.connect(STORE_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS stores (
        store_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        timezone TEXT NOT NULL,
        username TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        email TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    for store_id, name, tz in SEED_STORES:
        pw_hash = bcrypt.hashpw(store_id.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        conn.execute(
            'INSERT OR IGNORE INTO stores (store_id, name, timezone, username, password_hash) VALUES (?, ?, ?, ?, ?)',
            (store_id, name, tz, store_id, pw_hash)
        )
    conn.commit()
    conn.close()


def get_store_by_username(username):
    """Look up a store by username. Returns a dict or None."""
    conn = get_db()
    row = conn.execute('SELECT * FROM stores WHERE username = ?', (username,)).fetchone()
    conn.close()
    if row:
        return dict(row)
    return None


def get_all_stores_db():
    """Return all stores from the database as a list of dicts."""
    conn = get_db()
    rows = conn.execute('SELECT * FROM stores ORDER BY store_id').fetchall()
    conn.close()
    return [dict(r) for r in rows]


def check_password(stored_hash, password):
    """Verify a password against a bcrypt hash."""
    return bcrypt.checkpw(password.encode('utf-8'), stored_hash.encode('utf-8'))


def is_studio_locked(timezone_str):
    """Check if the Studio portal is locked for the given timezone.
    Locked Friday (4) through Sunday (6). Returns True if locked."""
    settings = load_settings()
    if not settings.get('feature_studio_lockout', True):
        return False
    try:
        tz = pytz.timezone(timezone_str)
    except pytz.exceptions.UnknownTimeZoneError:
        return False
    now = datetime.now(tz)
    return now.weekday() >= 4  # 4=Friday, 5=Saturday, 6=Sunday


# --- Archive database ---

def get_archive_db():
    """Get a SQLite connection to the archive database."""
    conn = sqlite3.connect(ARCHIVE_DB)
    conn.row_factory = sqlite3.Row
    return conn


def init_archive_db():
    """Create the archive database and tables if they don't exist."""
    os.makedirs(DATABASE_DIR, exist_ok=True)
    conn = sqlite3.connect(ARCHIVE_DB)
    conn.execute('''CREATE TABLE IF NOT EXISTS archive_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        file_type TEXT NOT NULL,
        original_filename TEXT NOT NULL,
        store_id TEXT,
        archived_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        file_date TEXT,
        row_count INTEGER,
        file_size_bytes INTEGER,
        content TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS image_flags (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        image_filename TEXT NOT NULL UNIQUE,
        flag_type TEXT NOT NULL,
        sku TEXT,
        status TEXT DEFAULT 'unresolved',
        resolved_at TIMESTAMP,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    conn.commit()
    conn.close()


def archive_file_if_exists(filepath, file_type, store_id=None):
    """Archive a file before it gets overwritten. Returns True if archived."""
    if not os.path.isfile(filepath):
        return False
    with open(filepath, 'r', errors='replace') as f:
        content = f.read()
    file_size = os.path.getsize(filepath)
    row_count = max(0, content.count('\n') - 1)  # subtract header row
    filename = os.path.basename(filepath)
    conn = get_archive_db()
    conn.execute(
        'INSERT INTO archive_files (file_type, original_filename, store_id, file_size_bytes, row_count, content) VALUES (?, ?, ?, ?, ?, ?)',
        (file_type, filename, store_id, file_size, row_count, content)
    )
    conn.commit()
    conn.close()
    return True


def classify_upload_filename(filename):
    """Determine file_type and store_id from a filename. Returns (file_type, store_id) or (None, None)."""
    m_sku = RE_SKU_LIST.match(filename)
    if m_sku:
        return ('sku_list', None)
    m_var = RE_VARIANCE.match(filename)
    if m_var:
        return ('variance', m_var.group(1).zfill(3))
    m_audit = RE_AUDIT_TRAIL.match(filename)
    if m_audit:
        return ('audit_trail', None)
    return (None, None)


def run_image_sku_audit():
    """Audit image/SKU matches. Returns {orphaned: N, missing: N}."""
    master = load_master_skus()
    master_skus = set(master.keys())  # uppercase

    # Scan images
    image_files = []
    if os.path.isdir(IMAGES_DIR):
        image_files = [f for f in os.listdir(IMAGES_DIR) if os.path.isfile(os.path.join(IMAGES_DIR, f))]

    # Build matched sets
    matched_images = set()
    matched_skus = set()
    for img in image_files:
        img_lower = img.lower()
        for sku in master_skus:
            if img_lower.startswith(sku.lower()):
                matched_images.add(img)
                matched_skus.add(sku)
                break

    orphaned_images = [img for img in image_files if img not in matched_images]
    missing_skus = [sku for sku in master_skus if sku not in matched_skus]

    conn = get_archive_db()

    # Clear flags that are now resolved
    conn.execute("DELETE FROM image_flags WHERE flag_type = 'orphaned_image' AND status = 'unresolved' AND image_filename NOT IN ({})".format(
        ','.join('?' * len(orphaned_images)) if orphaned_images else "'__none__'"
    ), orphaned_images if orphaned_images else [])

    conn.execute("DELETE FROM image_flags WHERE flag_type = 'missing_image' AND status = 'unresolved' AND image_filename NOT IN ({})".format(
        ','.join('?' * len(missing_skus)) if missing_skus else "'__none__'"
    ), missing_skus if missing_skus else [])

    # Insert new orphaned image flags
    for img in orphaned_images:
        conn.execute(
            "INSERT OR IGNORE INTO image_flags (image_filename, flag_type) VALUES (?, 'orphaned_image')",
            (img,)
        )

    # Insert new missing image flags (use SKU as image_filename for uniqueness)
    for sku in missing_skus:
        conn.execute(
            "INSERT OR IGNORE INTO image_flags (image_filename, flag_type, sku) VALUES (?, 'missing_image', ?)",
            (sku, sku)
        )

    conn.commit()
    conn.close()
    return {'orphaned': len(orphaned_images), 'missing': len(missing_skus)}


def studio_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('studio_logged_in'):
            return redirect(url_for('studio_login'))
        return f(*args, **kwargs)
    return decorated


def hq_login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('hq_logged_in'):
            return redirect(url_for('hq_login'))
        return f(*args, **kwargs)
    return decorated


def load_settings():
    """Load settings from JSON file."""
    defaults = {
        'email_body_template': DEFAULT_EMAIL_BODY,
        'store_emails': {},
        'feature_studio_lockout': True,
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


def load_master_skus():
    """Load SKU_Master.csv and return a dict of SKU (uppercase) -> DESCRIPTION."""
    filepath = os.path.join(MASTER_DIR, 'SKU_Master.csv')
    if not os.path.isfile(filepath):
        return {}
    rows = parse_csv(filepath)
    result = {}
    for row in rows:
        sku = row.get('sku', '').strip().upper()
        desc = row.get('description', '').strip()
        if sku:
            result[sku] = desc
    return result


def find_image_for_sku(sku):
    """Find an image file in IMAGES_DIR whose name starts with the SKU (case-insensitive)."""
    if not os.path.isdir(IMAGES_DIR):
        return None
    sku_lower = sku.lower()
    for fname in os.listdir(IMAGES_DIR):
        if fname.lower().startswith(sku_lower):
            return fname
    return None


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
    if weekly_skus is not None:
        active_skus = {s for s in (weekly_skus & variance_skus) if not is_excluded_sku(s)}
    else:
        # Bypass mode: no SKU list loaded, treat all variance SKUs as active
        active_skus = {s for s in variance_skus if not is_excluded_sku(s)}

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
    sku_bypass = False
    if scan['sku_lists']:
        sku_list_filename = scan['sku_lists'][0][0]
        try:
            weekly_skus = load_sku_list(os.path.join(INPUT_DIR, sku_list_filename))
            sku_count = len(weekly_skus)
        except Exception as e:
            warnings.append(f"Failed to parse SKU list: {e}")
    else:
        # Bypass mode: no SKU list present, reconcile using all variance SKUs
        sku_bypass = True
        weekly_skus = None
        warnings = [w for w in warnings if "No weekly SKU list file found" not in w]

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

    can_reconcile = (bool(weekly_skus) or sku_bypass) and len(scan.get('audit_trails', [])) > 0

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
        'sku_bypass': sku_bypass,
        'audit_date_min': audit_date_min,
        'audit_date_max': audit_date_max,
        'total_stores': len(stores),
        'count_updated': count_updated,
        'count_discrepancy': count_discrepancy,
        'count_incomplete': count_incomplete,
        'last_loaded': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


# --- Flask routes ---

# --- Landing page (unauthenticated) ---

@app.route('/')
def landing():
    return render_template('landing.html')


# --- Studio portal ---

@app.route('/studio/login', methods=['GET', 'POST'])
def studio_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        # Check admin credentials first (bypass lockout)
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['studio_logged_in'] = True
            session['is_admin'] = True
            return redirect(url_for('studio_index'))
        # Look up store
        store = get_store_by_username(username)
        if not store or not check_password(store['password_hash'], password):
            flash('Incorrect username or password.', 'error')
        elif is_studio_locked(store['timezone']):
            flash('Sorry, stud! The new SKU list will be available Monday.', 'lockout')
        else:
            session['studio_logged_in'] = True
            session['store_id'] = store['store_id']
            session['is_admin'] = False
            return redirect(url_for('studio_index'))
    return render_template('studio_login.html')


@app.route('/studio/logout')
def studio_logout():
    session.pop('studio_logged_in', None)
    return redirect(url_for('landing'))


@app.route('/studio/goto-hq')
@studio_login_required
def studio_goto_hq():
    session['hq_logged_in'] = True
    session['is_admin'] = True
    return redirect(url_for('hq_index'))


@app.route('/database/images/<filename>')
def serve_image(filename):
    return send_from_directory(IMAGES_DIR, filename)


@app.route('/studio/')
@studio_login_required
def studio_index():
    scan = scan_input_files()
    sku_list_filename = None
    no_sku_list = True
    sku_items = []

    if scan['sku_lists']:
        no_sku_list = False
        sku_list_filename = scan['sku_lists'][0][0]
        filepath = os.path.join(INPUT_DIR, sku_list_filename)

        # Parse SKU list with product names
        sku_rows = parse_csv(filepath)
        sku_names = {}
        sku_set = set()
        for row in sku_rows:
            sku = row.get('sku', '').strip()
            name = row.get('product name', '').strip()
            if sku and not is_excluded_sku(sku):
                sku_set.add(sku)
                sku_names[sku] = name

        master = load_master_skus()

        for sku in sorted(sku_set):
            desc = master.get(sku.upper(), '') or sku_names.get(sku, '') or sku
            image_filename = find_image_for_sku(sku)
            sku_items.append({
                'sku': sku,
                'description': desc,
                'image_filename': image_filename,
            })

    return render_template('studio.html',
                           sku_items=sku_items,
                           sku_list_filename=sku_list_filename,
                           no_sku_list=no_sku_list)


# --- HQ portal ---

@app.route('/hq/login', methods=['GET', 'POST'])
def hq_login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['hq_logged_in'] = True
            session['is_admin'] = True
            return redirect(url_for('hq_index'))
        else:
            flash('Incorrect username or password.', 'error')
    return render_template('hq_login.html')


@app.route('/hq/logout')
def hq_logout():
    session.pop('hq_logged_in', None)
    return redirect(url_for('landing'))


@app.route('/hq/')
@hq_login_required
def hq_index():
    results = run_reconciliation()
    db_stores = get_all_stores_db()
    return render_template('hq_shell.html', data=results, db_stores=db_stores)


@app.route('/hq/refresh', methods=['POST'])
@hq_login_required
def hq_refresh():
    results = run_reconciliation()
    return jsonify(results)


# --- SPA section fragment routes ---

@app.route('/hq/section/dashboard')
@hq_login_required
def hq_section_dashboard():
    results = run_reconciliation()
    return render_template('fragments/dashboard.html', data=results, settings=load_settings())


@app.route('/hq/section/analytics')
@hq_login_required
def hq_section_analytics():
    return render_template('fragments/analytics.html')


@app.route('/hq/section/database')
@hq_login_required
def hq_section_database():
    msf_path = os.path.join(MASTER_DIR, 'SKU_Master.csv')
    msf_rows = 0
    msf_updated = 'N/A'
    if os.path.isfile(msf_path):
        msf_rows = len(load_master_skus())
        msf_updated = datetime.fromtimestamp(os.path.getmtime(msf_path)).strftime('%Y-%m-%d %H:%M:%S')
    image_count = 0
    if os.path.isdir(IMAGES_DIR):
        image_count = len([f for f in os.listdir(IMAGES_DIR) if os.path.isfile(os.path.join(IMAGES_DIR, f))])
    conn = get_archive_db()
    orphaned = [dict(r) for r in conn.execute(
        "SELECT * FROM image_flags WHERE flag_type = 'orphaned_image' AND status = 'unresolved' ORDER BY image_filename"
    ).fetchall()]
    missing = [dict(r) for r in conn.execute(
        "SELECT * FROM image_flags WHERE flag_type = 'missing_image' AND status = 'unresolved' ORDER BY sku"
    ).fetchall()]
    conn.close()
    master = load_master_skus()
    for m in missing:
        m['description'] = master.get(m['sku'], '')
    return render_template('fragments/database.html',
                           msf_rows=msf_rows, msf_updated=msf_updated,
                           image_count=image_count, orphaned=orphaned, missing=missing)


@app.route('/hq/section/studios')
@hq_login_required
def hq_section_studios():
    db_stores = get_all_stores_db()
    return render_template('fragments/studios.html', db_stores=db_stores)


@app.route('/hq/database/upload-msf', methods=['POST'])
@hq_login_required
def hq_database_upload_msf():
    msf_path = os.path.join(MASTER_DIR, 'SKU_Master.csv')
    f = request.files.get('msf_file')
    if f and f.filename:
        archive_file_if_exists(msf_path, 'master_sku')
        os.makedirs(MASTER_DIR, exist_ok=True)
        f.save(msf_path)
        run_image_sku_audit()
        flash('Master SKU file updated.', 'success')
    return redirect('/hq/?section=database')


@app.route('/hq/database/upload-images', methods=['POST'])
@hq_login_required
def hq_database_upload_images():
    img_files = request.files.getlist('image_files')
    count = 0
    os.makedirs(IMAGES_DIR, exist_ok=True)
    for f in img_files:
        if f.filename:
            f.save(os.path.join(IMAGES_DIR, f.filename))
            count += 1
    if count:
        run_image_sku_audit()
        flash(f'{count} images uploaded.', 'success')
    return redirect('/hq/?section=database')


@app.route('/hq/studios/update-credentials', methods=['POST'])
@hq_login_required
def hq_studios_update_credentials():
    data = request.get_json()
    store_id = data.get('store_id', '')
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    if store_id and username:
        conn = get_db()
        conn.execute('UPDATE stores SET username = ?, updated_at = CURRENT_TIMESTAMP WHERE store_id = ?',
                     (username, store_id))
        if password:
            pw_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            conn.execute('UPDATE stores SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE store_id = ?',
                         (pw_hash, store_id))
        conn.commit()
        conn.close()
        return jsonify({'ok': True})
    return jsonify({'ok': False}), 400


@app.route('/hq/goto-studio')
@hq_login_required
def hq_goto_studio():
    session['studio_logged_in'] = True
    session['is_admin'] = True
    return redirect(url_for('studio_index'))


@app.route('/hq/archive')
@hq_login_required
def hq_archive():
    conn = get_archive_db()
    archives = [dict(r) for r in conn.execute(
        "SELECT id, file_type, original_filename, store_id, archived_at, row_count, file_size_bytes FROM archive_files ORDER BY archived_at DESC LIMIT 50"
    ).fetchall()]
    conn.close()
    return render_template('archive.html', archives=archives)


@app.route('/hq/upload', methods=['GET', 'POST'])
@hq_login_required
def hq_upload():
    if request.method == 'POST':
        files = request.files.getlist('files')
        uploaded = []
        for f in files:
            if f.filename:
                filepath = os.path.join(INPUT_DIR, f.filename)
                file_type, store_id = classify_upload_filename(f.filename)
                if file_type:
                    archive_file_if_exists(filepath, file_type, store_id)
                f.save(filepath)
                uploaded.append(f.filename)
        if uploaded:
            flash(f'Uploaded {len(uploaded)} file(s): {", ".join(uploaded)}', 'success')
        return redirect(url_for('hq_upload'))

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


@app.route('/hq/delete-file', methods=['POST'])
@hq_login_required
def hq_delete_file():
    filename = request.form.get('filename', '')
    if not filename or '/' in filename or '..' in filename:
        flash('Invalid filename.', 'error')
        return redirect(url_for('hq_upload'))
    filepath = os.path.join(INPUT_DIR, filename)
    if os.path.isfile(filepath):
        os.remove(filepath)
        flash(f'Deleted {filename}.', 'success')
    else:
        flash(f'File not found: {filename}', 'error')
    return redirect(url_for('hq_upload'))


@app.route('/hq/delete-all-files', methods=['POST'])
@hq_login_required
def hq_delete_all_files():
    count = 0
    if os.path.isdir(INPUT_DIR):
        for fname in os.listdir(INPUT_DIR):
            fpath = os.path.join(INPUT_DIR, fname)
            if os.path.isfile(fpath):
                os.remove(fpath)
                count += 1
    flash(f'Deleted {count} file(s) from /input/.', 'success')
    return redirect(url_for('hq_upload'))


@app.route('/hq/settings', methods=['GET', 'POST'])
@hq_login_required
def hq_settings_page():
    settings = load_settings()
    if request.method == 'POST':
        settings['email_body_template'] = request.form.get('email_body_template', DEFAULT_EMAIL_BODY)
        # Save per-store emails
        store_emails = {}
        for key, val in request.form.items():
            if key.startswith('store_email_'):
                store_id = key.replace('store_email_', '')
                store_emails[store_id] = val.strip()
        settings['store_emails'] = store_emails
        save_settings(settings)
        # Handle store credential updates
        cred_updated = False
        conn = get_db()
        for key, val in request.form.items():
            if key.startswith('store_username_'):
                store_id = key.replace('store_username_', '')
                new_username = val.strip()
                if new_username:
                    conn.execute('UPDATE stores SET username = ?, updated_at = CURRENT_TIMESTAMP WHERE store_id = ?',
                                 (new_username, store_id))
                    cred_updated = True
            if key.startswith('store_password_'):
                store_id = key.replace('store_password_', '')
                new_pw = val.strip()
                if new_pw:
                    pw_hash = bcrypt.hashpw(new_pw.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                    conn.execute('UPDATE stores SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE store_id = ?',
                                 (pw_hash, store_id))
                    cred_updated = True
        conn.commit()
        conn.close()
        if cred_updated:
            flash('Settings saved. Store credentials have been updated.', 'success')
        else:
            flash('Settings saved.', 'success')
        return redirect(url_for('hq_settings_page'))

    # Get all store IDs for email configuration
    results = run_reconciliation()
    db_stores = get_all_stores_db()
    return render_template('settings.html', settings=settings, stores=results['stores'], db_stores=db_stores)


@app.route('/hq/email-draft/<store_id>')
@hq_login_required
def hq_email_draft(store_id):
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


@app.route('/hq/export')
@hq_login_required
def hq_export_csv():
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


@app.route('/hq/database', methods=['GET', 'POST'])
@hq_login_required
def hq_database():
    msf_path = os.path.join(MASTER_DIR, 'SKU_Master.csv')
    diff_added = []
    diff_removed = []

    if request.method == 'POST':
        action = request.form.get('action', '')

        if action == 'upload_msf':
            f = request.files.get('msf_file')
            if f and f.filename:
                # Archive old MSF
                archive_file_if_exists(msf_path, 'master_sku')
                # Read old SKUs for diff
                old_skus = set(load_master_skus().keys())
                # Save new file
                os.makedirs(MASTER_DIR, exist_ok=True)
                f.save(msf_path)
                # Diff
                new_skus = set(load_master_skus().keys())
                diff_added = sorted(new_skus - old_skus)
                diff_removed = sorted(old_skus - new_skus)
                # Run audit
                run_image_sku_audit()
                flash(f'Master SKU file updated. {len(diff_added)} SKUs added, {len(diff_removed)} SKUs removed.', 'success')

        elif action == 'upload_images':
            img_files = request.files.getlist('image_files')
            count = 0
            os.makedirs(IMAGES_DIR, exist_ok=True)
            for f in img_files:
                if f.filename:
                    f.save(os.path.join(IMAGES_DIR, f.filename))
                    count += 1
            if count:
                run_image_sku_audit()
                flash(f'{count} images uploaded.', 'success')

        return redirect(url_for('hq_database'))

    # MSF status
    msf_rows = 0
    msf_updated = 'N/A'
    if os.path.isfile(msf_path):
        msf_rows = len(load_master_skus())
        msf_updated = datetime.fromtimestamp(os.path.getmtime(msf_path)).strftime('%Y-%m-%d %H:%M:%S')

    # Image count
    image_count = 0
    if os.path.isdir(IMAGES_DIR):
        image_count = len([f for f in os.listdir(IMAGES_DIR) if os.path.isfile(os.path.join(IMAGES_DIR, f))])

    # Audit flags
    conn = get_archive_db()
    orphaned = [dict(r) for r in conn.execute(
        "SELECT * FROM image_flags WHERE flag_type = 'orphaned_image' AND status = 'unresolved' ORDER BY image_filename"
    ).fetchall()]
    missing = [dict(r) for r in conn.execute(
        "SELECT * FROM image_flags WHERE flag_type = 'missing_image' AND status = 'unresolved' ORDER BY sku"
    ).fetchall()]

    # Add descriptions for missing images
    master = load_master_skus()
    for m in missing:
        m['description'] = master.get(m['sku'], '')

    # Archive browser
    archives = [dict(r) for r in conn.execute(
        "SELECT id, file_type, original_filename, store_id, archived_at, row_count, file_size_bytes FROM archive_files ORDER BY archived_at DESC LIMIT 50"
    ).fetchall()]
    conn.close()

    return render_template('database.html',
                           msf_rows=msf_rows, msf_updated=msf_updated,
                           image_count=image_count,
                           orphaned=orphaned, missing=missing,
                           archives=archives,
                           diff_added=diff_added, diff_removed=diff_removed)


@app.route('/hq/database/assign-image', methods=['POST'])
@hq_login_required
def hq_assign_image():
    image_filename = request.form.get('image_filename', '')
    sku = request.form.get('sku', '').strip()
    if image_filename and sku and os.path.isdir(IMAGES_DIR):
        old_path = os.path.join(IMAGES_DIR, image_filename)
        if os.path.isfile(old_path):
            ext = os.path.splitext(image_filename)[1]
            new_filename = sku + ext
            new_path = os.path.join(IMAGES_DIR, new_filename)
            os.rename(old_path, new_path)
            conn = get_archive_db()
            conn.execute("UPDATE image_flags SET status = 'assigned', sku = ?, resolved_at = CURRENT_TIMESTAMP WHERE image_filename = ?",
                         (sku, image_filename))
            conn.commit()
            conn.close()
            run_image_sku_audit()
            flash(f'Image renamed to {new_filename} and assigned to {sku}.', 'success')
    return redirect(url_for('hq_database'))


@app.route('/hq/database/mark-discontinued', methods=['POST'])
@hq_login_required
def hq_mark_discontinued():
    image_filename = request.form.get('image_filename', '')
    if image_filename:
        conn = get_archive_db()
        conn.execute("UPDATE image_flags SET status = 'discontinued', resolved_at = CURRENT_TIMESTAMP WHERE image_filename = ?",
                     (image_filename,))
        conn.commit()
        conn.close()
        flash(f'Flagged as discontinued: {image_filename}', 'success')
    return redirect(url_for('hq_database'))


@app.route('/hq/analytics')
@hq_login_required
def hq_analytics():
    return render_template('analytics.html')


init_store_db()
init_archive_db()

if __name__ == '__main__':
    os.makedirs(INPUT_DIR, exist_ok=True)
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    print(f"[STUDS Stock Check] Input directory: {INPUT_DIR}")
    print(f"[STUDS Stock Check] Starting on http://localhost:5000")
    app.run(debug=True, host='127.0.0.1', port=5000)
