"""
accounting.py - The bookkeeping engine.

Every business activity is recorded as a balanced double-entry journal entry
(debits == credits).  The income statement, balance sheet and cash flow
statement are *computed* from the journal, so they can never disagree and the
balance sheet always balances.

Account normal balances
  Debit-normal : Cash, Accounts Receivable, Inventory accounts, all expenses
  Credit-normal: Accounts Payable, Owner Investment, Sales
"""
import calendar
from datetime import date, timedelta

from payroll import calculate_paycheck

# ---- Chart of accounts --------------------------------------------------------
CASH = "Cash"
AR = "Accounts Receivable"
INV_PARTS = "Inventory - Parts"
INV_FG = "Inventory - Finished Goods"
AP = "Accounts Payable"
EQUITY = "Owner Investment"
SALES = "Sales"
COGS = "Cost of Goods Sold"
PAYROLL = "Payroll"                       # net pay to employees
WITHHOLDING = "Payroll Withholding"       # taxes withheld (separate tax account)
BILL_PREFIX = "Bill: "                    # one account per fixed monthly expense

CREDIT_NORMAL = {AP, EQUITY, SALES}
NET_TERMS_DAYS = 30


class BookkeepingError(ValueError):
    """Raised when a transaction can't be recorded; message is shown to the user."""


# ---- Settings (current book date, finished-goods count) -----------------------
def get_setting(conn, key, default=None):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(conn, key, value):
    conn.execute(
        "INSERT INTO settings(key, value) VALUES(?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, str(value)),
    )


def today(conn):
    return get_setting(conn, "current_date")


def fg_qty(conn):
    return int(get_setting(conn, "fg_qty", 0))


def add_month(iso_day):
    d = date.fromisoformat(iso_day)
    year = d.year + d.month // 12
    month = d.month % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day).isoformat()


# ---- Journal ------------------------------------------------------------------
def post(conn, kind, memo, lines, when=None):
    """Record a journal entry. lines = [(account, debit, credit), ...]"""
    when = when or today(conn)
    debits = round(sum(d for _, d, _ in lines), 2)
    credits = round(sum(c for _, _, c in lines), 2)
    if abs(debits - credits) > 0.005:
        raise BookkeepingError(f"Unbalanced entry: debits {debits} vs credits {credits}")
    cur = conn.execute(
        "INSERT INTO entries(date, kind, memo) VALUES(?, ?, ?)", (when, kind, memo)
    )
    entry_id = cur.lastrowid
    for account, debit, credit in lines:
        debit, credit = round(debit, 2), round(credit, 2)
        if debit == 0 and credit == 0:
            continue
        conn.execute(
            "INSERT INTO journal_lines(entry_id, account, debit, credit) VALUES(?, ?, ?, ?)",
            (entry_id, account, debit, credit),
        )
    return entry_id


def balance(conn, account):
    row = conn.execute(
        "SELECT COALESCE(SUM(debit), 0) AS d, COALESCE(SUM(credit), 0) AS c "
        "FROM journal_lines WHERE account = ?",
        (account,),
    ).fetchone()
    net = row["d"] - row["c"]
    return round(-net if account in CREDIT_NORMAL else net, 2) + 0.0  # avoid "-0.00"


def bill_balances(conn):
    rows = conn.execute(
        "SELECT account, ROUND(SUM(debit - credit), 2) AS amount FROM journal_lines "
        "WHERE account LIKE ? GROUP BY account ORDER BY account",
        (BILL_PREFIX + "%",),
    ).fetchall()
    return [(r["account"][len(BILL_PREFIX):], r["amount"]) for r in rows]


# ---- Master data --------------------------------------------------------------
def _require(value, label):
    if value is None or str(value).strip() == "":
        raise BookkeepingError(f"{label} is required.")
    return str(value).strip()


def to_number(value, label, integer=False, minimum=None):
    try:
        n = int(str(value).replace(",", "")) if integer else float(str(value).replace(",", "").replace("$", ""))
    except (TypeError, ValueError):
        raise BookkeepingError(f"{label} must be a {'whole ' if integer else ''}number.")
    if minimum is not None and n < minimum:
        raise BookkeepingError(f"{label} must be at least {minimum}.")
    return n


def add_employee(conn, f):
    conn.execute(
        "INSERT INTO employees(first_name, last_name, address1, address2, city, state, zip, "
        "ssn, filing_status, state_allowances, salary) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            _require(f.get("first_name"), "First name"), _require(f.get("last_name"), "Last name"),
            f.get("address1", ""), f.get("address2", ""), f.get("city", ""), f.get("state", ""),
            f.get("zip", ""), f.get("ssn", ""),
            f.get("filing_status") if f.get("filing_status") in ("single", "married") else "single",
            to_number(f.get("state_allowances", 0) or 0, "IL allowances", integer=True, minimum=0),
            to_number(f.get("salary"), "Salary", minimum=0.01),
        ),
    )
    return f"Added employee {f['first_name']} {f['last_name']}."


def add_customer(conn, f):
    conn.execute(
        "INSERT INTO customers(company, last_name, first_name, address1, address2, city, state, zip, price) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (
            _require(f.get("company"), "Company name"), f.get("last_name", ""), f.get("first_name", ""),
            f.get("address1", ""), f.get("address2", ""), f.get("city", ""), f.get("state", ""),
            f.get("zip", ""), to_number(f.get("price"), "Price per unit", minimum=0.01),
        ),
    )
    return f"Added customer {f['company']}."


def add_vendor(conn, f):
    company = _require(f.get("company"), "Company name")
    part = _require(f.get("part_name"), "Part")
    existing = conn.execute("SELECT id FROM parts WHERE name = ?", (part,)).fetchone()
    if existing:
        raise BookkeepingError(f"A part named {part} already exists. Use a different part name.")
    cur = conn.execute(
        "INSERT INTO vendors(company, address1, address2, city, state, zip) VALUES(?,?,?,?,?,?)",
        (company, f.get("address1", ""), f.get("address2", ""), f.get("city", ""),
         f.get("state", ""), f.get("zip", "")),
    )
    conn.execute(
        "INSERT INTO parts(name, vendor_id, unit_cost, qty_per_unit, reorder_point) VALUES(?,?,?,?,?)",
        (
            part, cur.lastrowid, to_number(f.get("unit_cost"), "Price per unit", minimum=0.0001),
            to_number(f.get("qty_per_unit", 0) or 0, "Quantity per truck", integer=True, minimum=0),
            to_number(f.get("reorder_point", 0) or 0, "Reorder point", integer=True, minimum=0),
        ),
    )
    return f"Added vendor {company} supplying {part}."


# ---- Transactions -------------------------------------------------------------
def create_invoice(conn, customer_id, qty):
    """Sale on net-30 terms: AR up, Sales up, COGS up, finished goods down."""
    qty = to_number(qty, "Number of units", integer=True, minimum=1)
    cust = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not cust:
        raise BookkeepingError("Choose a customer.")
    in_stock = fg_qty(conn)
    if qty > in_stock:
        raise BookkeepingError(
            f"Only {in_stock:,} finished units are in stock. Build more units or invoice fewer."
        )
    fg_value = balance(conn, INV_FG)
    cogs = fg_value if qty == in_stock else round(fg_value * qty / in_stock, 2)
    total = round(qty * cust["price"], 2)
    d = today(conn)
    due = (date.fromisoformat(d) + timedelta(days=NET_TERMS_DAYS)).isoformat()
    cur = conn.execute(
        "INSERT INTO invoices(date, due_date, customer_id, qty, price, total, cogs, status) "
        "VALUES(?,?,?,?,?,?,?, 'open')",
        (d, due, cust["id"], qty, cust["price"], total, cogs),
    )
    inv_id = cur.lastrowid
    post(conn, "invoice", f"Invoice #{inv_id} to {cust['company']} ({qty:,} units)", [
        (AR, total, 0), (SALES, 0, total),
        (COGS, cogs, 0), (INV_FG, 0, cogs),
    ])
    set_setting(conn, "fg_qty", in_stock - qty)
    return (f"Invoice #{inv_id} created for {cust['company']}: Sales and Accounts Receivable "
            f"+${total:,.2f}; COGS +${cogs:,.2f}; finished units {in_stock:,} → {in_stock - qty:,}.")


def create_po(conn, part_id, qty_ordered, qty_received=None):
    """Purchase on net-30 terms: parts inventory up, Accounts Payable up.
    The vendor bills for what is actually received, which may differ from the order."""
    qty_ordered = to_number(qty_ordered, "Quantity ordered", integer=True, minimum=1)
    if qty_received in (None, ""):
        qty_received = qty_ordered
    qty_received = to_number(qty_received, "Quantity received", integer=True, minimum=1)
    part = conn.execute(
        "SELECT p.*, v.company AS vendor FROM parts p JOIN vendors v ON v.id = p.vendor_id WHERE p.id = ?",
        (part_id,),
    ).fetchone()
    if not part:
        raise BookkeepingError("Choose a part.")
    total = round(qty_received * part["unit_cost"], 2)
    d = today(conn)
    due = (date.fromisoformat(d) + timedelta(days=NET_TERMS_DAYS)).isoformat()
    cur = conn.execute(
        "INSERT INTO purchase_orders(date, due_date, vendor_id, part_id, qty_ordered, qty_received, "
        "unit_price, total, status) VALUES(?,?,?,?,?,?,?,?, 'open')",
        (d, due, part["vendor_id"], part["id"], qty_ordered, qty_received, part["unit_cost"], total),
    )
    po_id = cur.lastrowid
    post(conn, "purchase", f"PO #{po_id} {part['vendor']}: {qty_received:,} {part['name']}", [
        (INV_PARTS, total, 0), (AP, 0, total),
    ])
    conn.execute(
        "UPDATE parts SET qty_on_hand = qty_on_hand + ?, value = ROUND(value + ?, 2) WHERE id = ?",
        (qty_received, total, part["id"]),
    )
    return po_id, total


def order_kits(conn, sets):
    """One PO per bill-of-materials part, enough to build `sets` trucks."""
    sets = to_number(sets, "Number of truck sets", integer=True, minimum=1)
    parts = conn.execute("SELECT * FROM parts WHERE qty_per_unit > 0 ORDER BY id").fetchall()
    grand = 0.0
    for p in parts:
        _, total = create_po(conn, p["id"], sets * p["qty_per_unit"])
        grand += total
    return f"Created {len(parts)} purchase orders for {sets:,} truck sets: inventory and Accounts Payable +${grand:,.2f}."


def inventory_status(conn):
    parts = conn.execute(
        "SELECT p.*, v.company AS vendor FROM parts p JOIN vendors v ON v.id = p.vendor_id ORDER BY p.id"
    ).fetchall()
    bom = [p for p in parts if p["qty_per_unit"] > 0]
    buildable = min((p["qty_on_hand"] // p["qty_per_unit"] for p in bom), default=0)
    cog_per_unit = round(sum(p["unit_cost"] * p["qty_per_unit"] for p in bom), 4)
    return {
        "parts": parts,
        "parts_value": balance(conn, INV_PARTS),
        "cog_per_unit": cog_per_unit,
        "buildable": buildable,
        "fg_qty": fg_qty(conn),
        "fg_value": balance(conn, INV_FG),
    }


def low_stock(conn):
    return conn.execute(
        "SELECT name, qty_on_hand, reorder_point FROM parts "
        "WHERE reorder_point > 0 AND qty_on_hand <= reorder_point ORDER BY name"
    ).fetchall()


def build_units(conn, n):
    """Turn parts into finished trucks: parts inventory down, finished goods up (at cost)."""
    n = to_number(n, "Units to build", integer=True, minimum=1)
    status = inventory_status(conn)
    if n > status["buildable"]:
        raise BookkeepingError(f"Parts on hand can build at most {status['buildable']:,} units.")
    cost = 0.0
    for p in status["parts"]:
        if p["qty_per_unit"] == 0:
            continue
        use = n * p["qty_per_unit"]
        c = p["value"] if use == p["qty_on_hand"] else round(p["value"] * use / p["qty_on_hand"], 2)
        conn.execute(
            "UPDATE parts SET qty_on_hand = qty_on_hand - ?, value = ROUND(value - ?, 2) WHERE id = ?",
            (use, c, p["id"]),
        )
        cost += c
    cost = round(cost, 2)
    post(conn, "build", f"Built {n:,} units", [(INV_FG, cost, 0), (INV_PARTS, 0, cost)])
    set_setting(conn, "fg_qty", fg_qty(conn) + n)
    return f"Built {n:,} units: ${cost:,.2f} moved from parts inventory to finished goods."


def _ytd_wages(conn, employee_id, iso_day):
    row = conn.execute(
        "SELECT COALESCE(SUM(gross), 0) AS w FROM payroll WHERE employee_id = ? AND substr(date, 1, 4) = ?",
        (employee_id, iso_day[:4]),
    ).fetchone()
    return row["w"]


def preview_paycheck(conn, emp, bonus=0.0):
    return calculate_paycheck(emp["salary"], bonus, emp["filing_status"],
                              emp["state_allowances"], _ytd_wages(conn, emp["id"], today(conn)))


def pay_employee(conn, employee_id, bonus=0.0):
    """Cash down by gross pay; expense split into net pay (Payroll) and taxes (Payroll Withholding)."""
    bonus = to_number(bonus or 0, "Bonus", minimum=0)
    emp = conn.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not emp:
        raise BookkeepingError("Choose an employee.")
    check = preview_paycheck(conn, emp, bonus)
    cash = balance(conn, CASH)
    if check["gross"] > cash:
        raise BookkeepingError(f"Not enough cash (${cash:,.2f}) to cover gross pay of ${check['gross']:,.2f}.")
    d = today(conn)
    conn.execute(
        "INSERT INTO payroll(date, employee_id, salary, bonus, gross, federal, state, social_security, "
        "medicare, withheld, net) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (d, emp["id"], check["salary"], check["bonus"], check["gross"], check["federal"], check["state"],
         check["social_security"], check["medicare"], check["total_withheld"], check["net"]),
    )
    name = f"{emp['first_name']} {emp['last_name']}"
    post(conn, "payroll", f"Payroll: {name}", [
        (PAYROLL, check["net"], 0), (WITHHOLDING, check["total_withheld"], 0), (CASH, 0, check["gross"]),
    ])
    return (f"Paid {name}: cash −${check['gross']:,.2f}; Payroll +${check['net']:,.2f}; "
            f"Payroll Withholding +${check['total_withheld']:,.2f}.")


def pay_bill(conn, expense_id, check_cash=True):
    exp = conn.execute("SELECT * FROM expense_accounts WHERE id = ?", (expense_id,)).fetchone()
    if not exp:
        raise BookkeepingError("Choose an expense account.")
    amount = exp["monthly_amount"]
    if check_cash and amount > balance(conn, CASH):
        raise BookkeepingError(f"Not enough cash to pay {exp['name']}.")
    conn.execute("INSERT INTO expenses_paid(date, expense_id, amount) VALUES(?,?,?)",
                 (today(conn), exp["id"], amount))
    post(conn, "bill", f"Paid {exp['name']}", [(BILL_PREFIX + exp["name"], amount, 0), (CASH, 0, amount)])
    return f"Paid {exp['name']}: cash −${amount:,.2f}; expenses +${amount:,.2f}."


def month_end_preview(conn):
    ar = conn.execute("SELECT COALESCE(SUM(total), 0) t, COUNT(*) n FROM invoices WHERE status = 'open'").fetchone()
    ap = conn.execute("SELECT COALESCE(SUM(total), 0) t, COUNT(*) n FROM purchase_orders WHERE status = 'open'").fetchone()
    bills = conn.execute("SELECT COALESCE(SUM(monthly_amount), 0) t FROM expense_accounts").fetchone()
    return {"ar": ar["t"], "ar_n": ar["n"], "ap": ap["t"], "ap_n": ap["n"], "bills": bills["t"],
            "next_date": add_month(today(conn))}


def month_end_close(conn, pay_bills=True):
    """End-of-month posting (course rule: settle AR and AP even if 30 days haven't passed),
    optionally pay the fixed monthly bills, then advance the book date one month."""
    d = today(conn)
    collected = paid = bills = 0.0
    for inv in conn.execute("SELECT * FROM invoices WHERE status = 'open'").fetchall():
        post(conn, "collection", f"Collected invoice #{inv['id']}", [(CASH, inv["total"], 0), (AR, 0, inv["total"])])
        conn.execute("UPDATE invoices SET status = 'paid', paid_date = ? WHERE id = ?", (d, inv["id"]))
        collected += inv["total"]
    for po in conn.execute("SELECT * FROM purchase_orders WHERE status = 'open'").fetchall():
        post(conn, "ap_payment", f"Paid PO #{po['id']}", [(AP, po["total"], 0), (CASH, 0, po["total"])])
        conn.execute("UPDATE purchase_orders SET status = 'paid', paid_date = ? WHERE id = ?", (d, po["id"]))
        paid += po["total"]
    if pay_bills:
        for e in conn.execute("SELECT id, monthly_amount FROM expense_accounts").fetchall():
            pay_bill(conn, e["id"], check_cash=False)
            bills += e["monthly_amount"]
    new_date = add_month(d)
    set_setting(conn, "current_date", new_date)
    return (f"Month closed: collected ${collected:,.2f} of receivables, paid ${paid:,.2f} of payables"
            + (f" and ${bills:,.2f} of bills" if pay_bills else "") + f". Book date is now {new_date}.")


# ---- Financial statements -----------------------------------------------------
def income_statement(conn):
    sales = balance(conn, SALES)
    cogs = balance(conn, COGS)
    payroll = balance(conn, PAYROLL)
    withholding = balance(conn, WITHHOLDING)
    bills = bill_balances(conn)
    bills_total = round(sum(a for _, a in bills), 2)
    total_expenses = round(payroll + withholding + bills_total, 2)
    gross_profit = round(sales - cogs, 2)
    operating_income = round(gross_profit - total_expenses, 2)
    income_taxes = 0.0   # business income tax not modeled (pass-through / out of scope)
    return {
        "sales": sales, "cogs": cogs, "gross_profit": gross_profit,
        "payroll": payroll, "withholding": withholding,
        "bills": bills, "bills_total": bills_total,
        "total_expenses": total_expenses, "other_income": 0.0,
        "operating_income": operating_income, "income_taxes": income_taxes,
        "net_income": round(operating_income - income_taxes, 2),
    }


def balance_sheet(conn):
    cash = balance(conn, CASH)
    ar = balance(conn, AR)
    inventory = round(balance(conn, INV_PARTS) + balance(conn, INV_FG), 2)
    total_current = round(cash + ar + inventory, 2)
    fixed = {"land": 0.0, "equipment": 0.0, "furniture": 0.0}
    total_fixed = 0.0
    total_assets = round(total_current + total_fixed, 2)

    ap = balance(conn, AP)
    notes, accruals, mortgage = 0.0, 0.0, 0.0
    total_current_liab = round(ap + notes + accruals, 2)
    total_liab = round(total_current_liab + mortgage, 2)
    investment = balance(conn, EQUITY)
    net_income = income_statement(conn)["net_income"]
    net_worth = round(investment + net_income, 2)
    total_le = round(total_liab + net_worth, 2)
    return {
        "cash": cash, "ar": ar, "inventory": inventory, "total_current": total_current,
        **fixed, "total_fixed": total_fixed, "total_assets": total_assets,
        "ap": ap, "notes": notes, "accruals": accruals, "total_current_liab": total_current_liab,
        "mortgage": mortgage, "total_ltd": mortgage, "total_liab": total_liab,
        "investment": investment, "net_income": net_income, "net_worth": net_worth,
        "total_le": total_le, "difference": round(total_assets - total_le, 2),
    }


CASH_FLOW_LABELS = [
    ("collection", "Collections from customers", "operating"),
    ("ap_payment", "Payments to vendors", "operating"),
    ("payroll", "Payroll (gross pay)", "operating"),
    ("bill", "Monthly bills", "operating"),
    ("opening", "Owner investment (net of opening inventory)", "financing"),
]


def cash_flow(conn):
    rows = conn.execute(
        "SELECT e.kind, ROUND(SUM(l.debit - l.credit), 2) AS amount FROM journal_lines l "
        "JOIN entries e ON e.id = l.entry_id WHERE l.account = ? GROUP BY e.kind",
        (CASH,),
    ).fetchall()
    by_kind = {r["kind"]: r["amount"] for r in rows}
    lines = [(label, section, by_kind.get(kind, 0.0)) for kind, label, section in CASH_FLOW_LABELS]
    operating = round(sum(a for _, s, a in lines if s == "operating"), 2)
    financing = round(sum(a for _, s, a in lines if s == "financing"), 2)
    return {
        "operating_lines": [(l, a) for l, s, a in lines if s == "operating"],
        "financing_lines": [(l, a) for l, s, a in lines if s == "financing"],
        "operating": operating, "investing": 0.0, "financing": financing,
        "net_change": round(operating + financing, 2),
        "ending_cash": balance(conn, CASH),
    }
