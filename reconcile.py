import os
import re
import csv
import io
from datetime import datetime

# --- Paths ---
_DATA_DIR = os.environ.get('STUDS_DATA_DIR', '').strip()
if _DATA_DIR:
    INPUT_DIR = os.path.join(_DATA_DIR, 'input')
else:
    INPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'input')

# --- Status constants ---
STATUS_UPDATED = "Updated"
STATUS_DISCREPANCY = "Discrepancy Detected"
STATUS_INCOMPLETE = "Incomplete (missing file)"
STATUS_INCOMPLETE_FORMAT = "Incomplete (unrecognized file format)"

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


# --- Dependency: set by app.py after import ---
get_all_stores_db = None


# --- CSV helpers ---

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


# --- Reconciliation functions ---

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

    # Always use the full seeded store list as the source of truth
    all_stores_db = get_all_stores_db()
    db_store_names = {s['store_id']: s['name'] for s in all_stores_db}
    all_store_ids = {s['store_id'] for s in all_stores_db}
    # Also include any variance files that exist but aren't in the DB (edge case)
    all_store_ids.update(scan['variance_files'].keys())

    for store_id in sorted(all_store_ids, key=lambda x: x.zfill(10) if x.isdigit() else x):
        store_name = db_store_names.get(store_id) or store_names.get(store_id, store_id)

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
