"""
app.py - Web interface for the Mr. Truck Inc. bookkeeping program.

Run:  python app.py   then open http://127.0.0.1:5000
"""
from datetime import date

from flask import Flask, flash, g, redirect, render_template, request, url_for

import accounting as acct
import db as dbm

app = Flask(__name__)
app.secret_key = "eng566-local-only"


# ---- Database per request -----------------------------------------------------
def get_db():
    if "db" not in g:
        g.db = dbm.connect()
        dbm.ensure_initialized(g.db)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def perform(action, ok_endpoint, err_endpoint=None):
    """Run a transaction; commit + show success, or roll back + show the error."""
    conn = get_db()
    try:
        message = action(conn)
        conn.commit()
        flash(message, "ok")
        return redirect(url_for(ok_endpoint))
    except acct.BookkeepingError as e:
        conn.rollback()
        flash(str(e), "error")
        return redirect(url_for(err_endpoint or ok_endpoint))


# ---- Template helpers ---------------------------------------------------------
@app.template_filter("money")
def money(v):
    v = float(v or 0)
    s = f"${abs(v):,.2f}"
    return f"−{s}" if v < 0 else s


@app.template_filter("longdate")
def longdate(iso):
    d = date.fromisoformat(iso)
    return f"{d:%B} {d.day}, {d.year}"


def fmt(v, kind=None):
    if v is None:
        return ""
    if kind == "money":
        return money(v)
    if kind == "int":
        return f"{int(v):,}"
    return v


@app.context_processor
def inject_globals():
    conn = get_db()
    return {
        "book_date": acct.today(conn),
        "low_stock": acct.low_stock(conn),
        "fmt": fmt,
    }


def col(label, key, kind=None):
    return {"label": label, "key": key, "fmt": kind}


# ---- Main menu ----------------------------------------------------------------
@app.route("/")
def index():
    conn = get_db()
    return render_template("index.html", title="Main menu",
                           bs=acct.balance_sheet(conn), inc=acct.income_statement(conn),
                           fg=acct.fg_qty(conn))


# ---- Employees / customers / vendors ------------------------------------------
EMPLOYEE_FIELDS = [
    {"name": "first_name", "label": "First name", "required": True},
    {"name": "last_name", "label": "Last name", "required": True},
    {"name": "address1", "label": "Address 1"},
    {"name": "address2", "label": "Address 2"},
    {"name": "city", "label": "City"},
    {"name": "state", "label": "State"},
    {"name": "zip", "label": "Zip code"},
    {"name": "ssn", "label": "Social Security number"},
    {"name": "filing_status", "label": "Federal filing status (W-4)", "type": "select",
     "options": [("single", "Single"), ("married", "Married filing jointly")]},
    {"name": "state_allowances", "label": "Illinois allowances (IL-W-4)", "type": "number", "value": 1},
    {"name": "salary", "label": "Annual salary ($)", "type": "number", "step": "0.01", "required": True},
]

CUSTOMER_FIELDS = [
    {"name": "company", "label": "Company name", "required": True},
    {"name": "first_name", "label": "Contact first name"},
    {"name": "last_name", "label": "Contact last name"},
    {"name": "address1", "label": "Address 1"},
    {"name": "address2", "label": "Address 2"},
    {"name": "city", "label": "City"},
    {"name": "state", "label": "State"},
    {"name": "zip", "label": "Zip code"},
    {"name": "price", "label": "Price per truck ($)", "type": "number", "step": "0.01", "value": "2.50",
     "required": True},
]

VENDOR_FIELDS = [
    {"name": "company", "label": "Company name", "required": True},
    {"name": "part_name", "label": "Part supplied", "required": True},
    {"name": "unit_cost", "label": "Price per unit ($)", "type": "number", "step": "0.0001", "required": True},
    {"name": "qty_per_unit", "label": "Quantity used per truck (0 if not in the bill of materials)",
     "type": "number", "value": 0},
    {"name": "reorder_point", "label": "Reorder point (units)", "type": "number", "value": 0},
    {"name": "address1", "label": "Address 1"},
    {"name": "address2", "label": "Address 2"},
    {"name": "city", "label": "City"},
    {"name": "state", "label": "State"},
    {"name": "zip", "label": "Zip code"},
]


@app.route("/employees")
def employees():
    rows = get_db().execute("SELECT * FROM employees ORDER BY last_name").fetchall()
    return render_template("list.html", title="Employees", rows=rows,
                           action={"url": url_for("add_employee"), "label": "Add employee"},
                           columns=[col("First name", "first_name"), col("Last name", "last_name"),
                                    col("Address 1", "address1"), col("Address 2", "address2"),
                                    col("City", "city"), col("State", "state"), col("Zip", "zip"),
                                    col("SSN", "ssn"), col("Filing status", "filing_status"),
                                    col("IL allowances", "state_allowances", "int"),
                                    col("Salary", "salary", "money")])


@app.route("/employees/add", methods=["GET", "POST"])
def add_employee():
    if request.method == "POST":
        return perform(lambda c: acct.add_employee(c, request.form), "employees", "add_employee")
    return render_template("form.html", title="Add employee", fields=EMPLOYEE_FIELDS, submit="Add employee")


@app.route("/customers")
def customers():
    rows = get_db().execute("SELECT * FROM customers ORDER BY id").fetchall()
    return render_template("list.html", title="Customers", rows=rows,
                           action={"url": url_for("add_customer"), "label": "Add customer"},
                           columns=[col("Company", "company"), col("Last name", "last_name"),
                                    col("First name", "first_name"), col("Address 1", "address1"),
                                    col("Address 2", "address2"), col("City", "city"),
                                    col("State", "state"), col("Zip", "zip"),
                                    col("Price", "price", "money")])


@app.route("/customers/add", methods=["GET", "POST"])
def add_customer():
    if request.method == "POST":
        return perform(lambda c: acct.add_customer(c, request.form), "customers", "add_customer")
    return render_template("form.html", title="Add customer", fields=CUSTOMER_FIELDS, submit="Add customer")


@app.route("/vendors")
def vendors():
    rows = get_db().execute(
        "SELECT v.*, p.name AS part, p.unit_cost FROM vendors v LEFT JOIN parts p ON p.vendor_id = v.id "
        "ORDER BY v.id").fetchall()
    return render_template("list.html", title="Vendors", rows=rows,
                           action={"url": url_for("add_vendor"), "label": "Add vendor"},
                           columns=[col("Company", "company"), col("Part", "part"),
                                    col("Price/unit", "unit_cost", "money"), col("Address 1", "address1"),
                                    col("Address 2", "address2"), col("City", "city"),
                                    col("State", "state"), col("Zip", "zip")])


@app.route("/vendors/add", methods=["GET", "POST"])
def add_vendor():
    if request.method == "POST":
        return perform(lambda c: acct.add_vendor(c, request.form), "vendors", "add_vendor")
    return render_template("form.html", title="Add vendor", fields=VENDOR_FIELDS, submit="Add vendor")


# ---- Payroll ------------------------------------------------------------------
@app.route("/pay", methods=["GET", "POST"])
def pay():
    if request.method == "POST":
        return perform(lambda c: acct.pay_employee(c, request.form.get("employee_id"),
                                                   request.form.get("bonus") or 0),
                       "payroll_history", "pay")
    conn = get_db()
    emps = conn.execute("SELECT * FROM employees ORDER BY last_name").fetchall()
    previews = [(e, acct.preview_paycheck(conn, e)) for e in emps]
    return render_template("pay.html", title="Pay employee", previews=previews)


@app.route("/payroll")
def payroll_history():
    conn = get_db()
    rows = conn.execute(
        "SELECT p.*, e.first_name || ' ' || e.last_name AS employee FROM payroll p "
        "JOIN employees e ON e.id = p.employee_id ORDER BY p.id").fetchall()
    totals = conn.execute("SELECT COALESCE(SUM(net),0) net, COALESCE(SUM(withheld),0) withheld, "
                          "COALESCE(SUM(gross),0) gross FROM payroll").fetchone()
    return render_template("payroll.html", title="Payroll history", rows=rows, totals=totals)


# ---- Sales --------------------------------------------------------------------
@app.route("/invoice", methods=["GET", "POST"])
def create_invoice():
    if request.method == "POST":
        return perform(lambda c: acct.create_invoice(c, request.form.get("customer_id"), request.form.get("qty")),
                       "invoices", "create_invoice")
    conn = get_db()
    custs = conn.execute("SELECT * FROM customers ORDER BY company").fetchall()
    return render_template("invoice.html", title="Create invoice", customers=custs, in_stock=acct.fg_qty(conn))


@app.route("/invoices")
def invoices():
    rows = get_db().execute(
        "SELECT i.*, c.company AS customer FROM invoices i JOIN customers c ON c.id = i.customer_id "
        "ORDER BY i.id").fetchall()
    return render_template("list.html", title="Invoice history", rows=rows,
                           action={"url": url_for("create_invoice"), "label": "Create invoice"},
                           columns=[col("Invoice #", "id"), col("Date", "date"), col("Due", "due_date"),
                                    col("Customer", "customer"), col("Quantity", "qty", "int"),
                                    col("Price/unit", "price", "money"), col("Total", "total", "money"),
                                    col("COGS", "cogs", "money"), col("Status", "status"),
                                    col("Paid on", "paid_date")],
                           totals={"Total sales": sum(r["total"] for r in rows),
                                   "Total COGS": sum(r["cogs"] for r in rows)})


# ---- Purchasing ---------------------------------------------------------------
@app.route("/po", methods=["GET", "POST"])
def create_po():
    if request.method == "POST":
        if request.form.get("mode") == "kits":
            return perform(lambda c: acct.order_kits(c, request.form.get("sets")), "purchase_orders", "create_po")

        def single(c):
            po_id, total = acct.create_po(c, request.form.get("part_id"), request.form.get("qty_ordered"),
                                          request.form.get("qty_received"))
            return f"PO #{po_id} created: parts inventory and Accounts Payable +${total:,.2f}."
        return perform(single, "purchase_orders", "create_po")
    conn = get_db()
    inv = acct.inventory_status(conn)
    return render_template("po.html", title="Create purchase order", parts=inv["parts"],
                           cog_per_unit=inv["cog_per_unit"])


@app.route("/pos")
def purchase_orders():
    rows = get_db().execute(
        "SELECT po.*, v.company AS supplier, p.name AS part FROM purchase_orders po "
        "JOIN vendors v ON v.id = po.vendor_id JOIN parts p ON p.id = po.part_id ORDER BY po.id").fetchall()
    return render_template("list.html", title="Purchase order history", rows=rows,
                           action={"url": url_for("create_po"), "label": "Create PO"},
                           columns=[col("PO #", "id"), col("Date", "date"), col("Due", "due_date"),
                                    col("Supplier", "supplier"), col("Part", "part"),
                                    col("Ordered", "qty_ordered", "int"), col("Received", "qty_received", "int"),
                                    col("Price/part", "unit_price", "money"), col("Total", "total", "money"),
                                    col("Status", "status"), col("Paid on", "paid_date")],
                           totals={"Total purchased": sum(r["total"] for r in rows)})


# ---- Inventory ----------------------------------------------------------------
@app.route("/inventory")
def inventory():
    return render_template("inventory.html", title="Inventory", inv=acct.inventory_status(get_db()))


@app.route("/build", methods=["GET", "POST"])
def build():
    if request.method == "POST":
        return perform(lambda c: acct.build_units(c, request.form.get("units")), "inventory", "build")
    return render_template("build.html", title="Build units", inv=acct.inventory_status(get_db()))


# ---- Expenses -----------------------------------------------------------------
@app.route("/expenses")
def expenses():
    conn = get_db()
    rows = conn.execute(
        "SELECT a.*, COALESCE((SELECT SUM(amount) FROM expenses_paid p WHERE p.expense_id = a.id), 0) AS paid "
        "FROM expense_accounts a ORDER BY a.id").fetchall()
    return render_template("expenses.html", title="Expense accounts", rows=rows)


@app.route("/expenses/pay", methods=["POST"])
def pay_bill():
    return perform(lambda c: acct.pay_bill(c, request.form.get("expense_id")), "expenses")


@app.route("/expenses/paid")
def paid_expenses():
    rows = get_db().execute(
        "SELECT p.*, a.name AS expense FROM expenses_paid p JOIN expense_accounts a ON a.id = p.expense_id "
        "ORDER BY p.id").fetchall()
    return render_template("list.html", title="Paid expenses", rows=rows,
                           action={"url": url_for("expenses"), "label": "Pay a bill"},
                           columns=[col("Date paid", "date"), col("Expense", "expense"),
                                    col("Cost", "amount", "money")],
                           totals={"Total paid": sum(r["amount"] for r in rows)})


# ---- Statements ---------------------------------------------------------------
def statements_page(title, show):
    conn = get_db()
    return render_template("statements.html", title=title, show=show,
                           inc=acct.income_statement(conn), bs=acct.balance_sheet(conn),
                           cf=acct.cash_flow(conn))


@app.route("/income-statement")
def income_statement():
    return statements_page("Income statement", ["is"])


@app.route("/balance-sheet")
def balance_sheet():
    return statements_page("Balance sheet", ["bs"])


@app.route("/cash-flow")
def cash_flow():
    return statements_page("Cash flow statement", ["cf"])


@app.route("/statements")
def statements():
    return statements_page("Income statement and balance sheet", ["is", "bs"])


@app.route("/report")
def report():
    return statements_page("Financial report", ["is", "bs", "cf"])


@app.route("/journal")
def journal():
    conn = get_db()
    entries = conn.execute("SELECT * FROM entries ORDER BY id DESC").fetchall()
    lines = {}
    for l in conn.execute("SELECT * FROM journal_lines ORDER BY id").fetchall():
        lines.setdefault(l["entry_id"], []).append(l)
    return render_template("journal.html", title="Journal", entries=entries, lines=lines)


# ---- Testing & setup ----------------------------------------------------------
@app.route("/testing")
def testing():
    return render_template("testing.html", title="Testing and setup",
                           preview=acct.month_end_preview(get_db()), defaults=dbm.DEFAULTS)


@app.route("/testing/close-month", methods=["POST"])
def close_month():
    return perform(lambda c: acct.month_end_close(c, request.form.get("pay_bills") == "on"), "testing")


@app.route("/testing/reset", methods=["POST"])
def reset():
    f = request.form

    def do_reset(c):
        dbm.reset(c, f.get("start_date"),
                  acct.to_number(f.get("investment"), "Initial investment", minimum=0),
                  acct.to_number(f.get("finished_units"), "Finished units", integer=True, minimum=0),
                  acct.to_number(f.get("part_sets"), "Part sets", integer=True, minimum=0),
                  acct.to_number(f.get("reorder_sets"), "Reorder point", integer=True, minimum=0))
        return "Books reset to the initial conditions."
    return perform(do_reset, "statements", "testing")


if __name__ == "__main__":
    app.run(debug=True)
