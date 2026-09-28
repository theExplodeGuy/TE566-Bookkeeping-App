"""
db.py - SQLite schema, connection helper, and the "initial conditions" seed.

Run `python db.py` to (re)create books.db with the default starting conditions.
"""
import os
import sqlite3

import accounting as acct

DB_PATH = os.environ.get(
    "BOOKS_DB", os.path.join(os.path.dirname(os.path.abspath(__file__)), "books.db")
)

SCHEMA = """
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE employees (
    id INTEGER PRIMARY KEY, first_name TEXT NOT NULL, last_name TEXT NOT NULL,
    address1 TEXT, address2 TEXT, city TEXT, state TEXT, zip TEXT, ssn TEXT,
    filing_status TEXT NOT NULL DEFAULT 'single',
    state_allowances INTEGER NOT NULL DEFAULT 1,
    salary REAL NOT NULL);

CREATE TABLE customers (
    id INTEGER PRIMARY KEY, company TEXT NOT NULL, last_name TEXT, first_name TEXT,
    address1 TEXT, address2 TEXT, city TEXT, state TEXT, zip TEXT,
    price REAL NOT NULL);

CREATE TABLE vendors (
    id INTEGER PRIMARY KEY, company TEXT NOT NULL,
    address1 TEXT, address2 TEXT, city TEXT, state TEXT, zip TEXT);

CREATE TABLE parts (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    unit_cost REAL NOT NULL,
    qty_per_unit INTEGER NOT NULL DEFAULT 0,      -- bill of materials
    qty_on_hand INTEGER NOT NULL DEFAULT 0,
    value REAL NOT NULL DEFAULT 0,                -- total cost of parts on hand
    reorder_point INTEGER NOT NULL DEFAULT 0);

CREATE TABLE entries (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, kind TEXT NOT NULL, memo TEXT);

CREATE TABLE journal_lines (
    id INTEGER PRIMARY KEY, entry_id INTEGER NOT NULL REFERENCES entries(id),
    account TEXT NOT NULL, debit REAL NOT NULL DEFAULT 0, credit REAL NOT NULL DEFAULT 0);

CREATE TABLE invoices (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, due_date TEXT NOT NULL,
    customer_id INTEGER NOT NULL REFERENCES customers(id),
    qty INTEGER NOT NULL, price REAL NOT NULL, total REAL NOT NULL, cogs REAL NOT NULL,
    status TEXT NOT NULL, paid_date TEXT);

CREATE TABLE purchase_orders (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL, due_date TEXT NOT NULL,
    vendor_id INTEGER NOT NULL REFERENCES vendors(id),
    part_id INTEGER NOT NULL REFERENCES parts(id),
    qty_ordered INTEGER NOT NULL, qty_received INTEGER NOT NULL,
    unit_price REAL NOT NULL, total REAL NOT NULL,
    status TEXT NOT NULL, paid_date TEXT);

CREATE TABLE payroll (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL,
    employee_id INTEGER NOT NULL REFERENCES employees(id),
    salary REAL, bonus REAL, gross REAL, federal REAL, state REAL,
    social_security REAL, medicare REAL, withheld REAL, net REAL);

CREATE TABLE expense_accounts (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, monthly_amount REAL NOT NULL);

CREATE TABLE expenses_paid (
    id INTEGER PRIMARY KEY, date TEXT NOT NULL,
    expense_id INTEGER NOT NULL REFERENCES expense_accounts(id), amount REAL NOT NULL);
"""

TABLES = ["expenses_paid", "expense_accounts", "payroll", "purchase_orders", "invoices",
          "journal_lines", "entries", "parts", "vendors", "customers", "employees", "settings"]

# ---- Initial conditions (edit these, or use the Testing & setup page) ---------
DEFAULTS = {
    "start_date": "2026-01-01",
    "investment": 200_000.00,   # initial investment
    "finished_units": 20_000,   # trucks already built; lets the $50,000 sale happen first
    "part_sets": 10_000,        # raw parts on hand, measured in complete truck sets
    "reorder_sets": 5_000,      # reorder point, in truck sets
}

# Toy truck bill of materials (Instructional Guide, section 2) - 8 unique vendors
# (vendor, address1, city, state, zip, part, unit cost, quantity per truck)
VENDORS = [
    ("Tires R Us", "12 Tread Ave", "Akron", "OH", "44308", "Wheels", 0.01, 8),
    ("Acme Plastics", "400 Polymer Rd", "Toledo", "OH", "43604", "Windshield Glass", 0.05, 1),
    ("Interiors Inc", "88 Seat St", "Detroit", "MI", "48201", "Interior", 0.05, 1),
    ("Mr Mixers", "5 Drum Way", "Peoria", "IL", "61602", "Tank", 0.10, 1),
    ("Micro Axles", "900 Spindle Ln", "Rockford", "IL", "61101", "Axles", 0.01, 4),
    ("Castings for U", "31 Foundry Ct", "Gary", "IN", "46402", "Cab", 0.10, 1),
    ("Casting Man", "77 Mold Blvd", "Joliet", "IL", "60432", "Body", 0.10, 1),
    ("Many Boxes", "2 Carton Pl", "Decatur", "IL", "62523", "Box", 0.05, 1),
]

CUSTOMERS = [
    ("Smith Co.", "Smith", "John", "4567 Smith Lane", "Urbana", "IL", "61801"),
    ("Toys r Us", "", "", "", "", "", ""),
    ("Online Hobbies", "", "", "", "", "", ""),
    ("TowerHobbies", "", "", "", "", "", ""),
    ("Hobbytron", "", "", "", "", "", ""),
    ("Walmart", "", "", "", "", "", ""),
    ("Kmart", "", "", "", "", "", ""),
    ("Target", "", "", "", "", "", ""),
    ("Hobbytown", "", "", "", "", "", ""),
    ("Cars are Us", "", "", "", "", "", ""),
]
CUSTOMER_PRICE = 2.50

EMPLOYEES = [
    # first, last, address1, city, state, zip, ssn, filing status, IL allowances, salary
    ("John", "Smith", "123 Front St", "Champaign", "IL", "61820", "123-45-6789", "single", 1, 150_000.00),
]

# 10 expense accounts totalling ~$200,000/year ($16,666.67/month)
EXPENSES = [
    ("Maintenance", 2500.00), ("Cleaning", 833.33), ("Water", 833.33), ("Sewage", 1666.67),
    ("Electricity", 2500.00), ("Travel", 1666.67), ("Donuts", 833.33), ("Gas", 2500.00),
    ("High Speed Internet", 1666.67), ("Phone", 1666.67),
]


def connect(path=None):
    conn = sqlite3.connect(path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def is_initialized(conn):
    row = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='settings'").fetchone()
    return row is not None


def reset(conn, start_date=None, investment=None, finished_units=None, part_sets=None,
          reorder_sets=None):
    """Wipe all data and load the initial conditions.

    The opening entry keeps the books balanced:
        Dr Cash + Dr Parts inventory + Dr Finished goods = Cr Owner Investment
    so any starting inventory is paid for out of the initial investment.
    """
    start_date = start_date or DEFAULTS["start_date"]
    investment = float(DEFAULTS["investment"] if investment in (None, "") else investment)
    finished_units = int(DEFAULTS["finished_units"] if finished_units in (None, "") else finished_units)
    part_sets = int(DEFAULTS["part_sets"] if part_sets in (None, "") else part_sets)
    reorder_sets = int(DEFAULTS["reorder_sets"] if reorder_sets in (None, "") else reorder_sets)

    # Validate before wiping anything
    std_cost = sum(cost * qpu for *_, cost, qpu in VENDORS)
    if investment < round(part_sets * std_cost + finished_units * std_cost, 2):
        raise acct.BookkeepingError("Starting inventory costs more than the initial investment.")

    for t in TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {t}")
    conn.executescript(SCHEMA)

    acct.set_setting(conn, "current_date", start_date)
    acct.set_setting(conn, "start_date", start_date)

    parts_value = 0.0
    cog_per_unit = 0.0
    for company, a1, city, st, z, part, cost, qpu in VENDORS:
        cur = conn.execute(
            "INSERT INTO vendors(company, address1, address2, city, state, zip) VALUES(?,?,?,?,?,?)",
            (company, a1, "", city, st, z),
        )
        qty = part_sets * qpu
        value = round(qty * cost, 2)
        conn.execute(
            "INSERT INTO parts(name, vendor_id, unit_cost, qty_per_unit, qty_on_hand, value, reorder_point) "
            "VALUES(?,?,?,?,?,?,?)",
            (part, cur.lastrowid, cost, qpu, qty, value, reorder_sets * qpu),
        )
        parts_value += value
        cog_per_unit += cost * qpu

    for company, last, first, a1, city, st, z in CUSTOMERS:
        conn.execute(
            "INSERT INTO customers(company, last_name, first_name, address1, address2, city, state, zip, price) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (company, last, first, a1, "", city, st, z, CUSTOMER_PRICE),
        )

    for first, last, a1, city, st, z, ssn, fs, allow, salary in EMPLOYEES:
        conn.execute(
            "INSERT INTO employees(first_name, last_name, address1, address2, city, state, zip, ssn, "
            "filing_status, state_allowances, salary) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (first, last, a1, "", city, st, z, ssn, fs, allow, salary),
        )

    for name, amount in EXPENSES:
        conn.execute("INSERT INTO expense_accounts(name, monthly_amount) VALUES(?,?)", (name, amount))

    parts_value = round(parts_value, 2)
    fg_value = round(finished_units * cog_per_unit, 2)
    cash = round(investment - parts_value - fg_value, 2)
    if cash < 0:
        raise acct.BookkeepingError("Starting inventory costs more than the initial investment.")
    acct.set_setting(conn, "fg_qty", finished_units)
    acct.post(conn, "opening", "Initial investment and opening inventory", [
        (acct.CASH, cash, 0),
        (acct.INV_PARTS, parts_value, 0),
        (acct.INV_FG, fg_value, 0),
        (acct.EQUITY, 0, investment),
    ], when=start_date)
    conn.commit()


def ensure_initialized(conn):
    if not is_initialized(conn):
        reset(conn)


if __name__ == "__main__":
    c = connect()
    reset(c)
    print(f"Created {DB_PATH} with default initial conditions.")
