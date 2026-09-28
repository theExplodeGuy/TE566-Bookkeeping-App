"""
run_final_assignment.py - Runs the three turn-in transactions on a scratch
database and prints the income statement and balance sheet before and after
each one.  Use it to check your numbers before you take screenshots.

    python run_final_assignment.py
"""
import os
import tempfile

import accounting as acct
import db as dbm


def show(conn, heading):
    inc, bs = acct.income_statement(conn), acct.balance_sheet(conn)
    print(f"\n=== {heading} ===")
    print(f"  Sales {inc['sales']:>12,.2f}   COGS {inc['cogs']:>10,.2f}   Gross profit {inc['gross_profit']:>12,.2f}")
    print(f"  Payroll {inc['payroll']:>10,.2f}   Withholding {inc['withholding']:>9,.2f}   Bills {inc['bills_total']:>10,.2f}")
    print(f"  Net income {inc['net_income']:>12,.2f}")
    print(f"  Cash {bs['cash']:>12,.2f}   AR {bs['ar']:>10,.2f}   Inventory {bs['inventory']:>10,.2f}   "
          f"Total assets {bs['total_assets']:>12,.2f}")
    print(f"  AP {bs['ap']:>14,.2f}   Net worth {bs['net_worth']:>12,.2f}   "
          f"Liabilities + net worth {bs['total_le']:>12,.2f}")
    assert bs["difference"] == 0, "Balance sheet does not balance!"
    print("  Balanced ✔")


def main():
    path = os.path.join(tempfile.mkdtemp(), "scratch.db")
    conn = dbm.connect(path)
    dbm.reset(conn)
    show(conn, "A/B. Initial conditions")

    smith = conn.execute("SELECT id FROM customers WHERE company = 'Smith Co.'").fetchone()["id"]
    print("\n1) " + acct.create_invoice(conn, smith, 20_000))       # 20,000 x $2.50 = $50,000
    show(conn, "After $50,000 sale")

    tank = conn.execute("SELECT id FROM parts WHERE name = 'Tank'").fetchone()["id"]
    po_id, total = acct.create_po(conn, tank, 200_000)                # 200,000 x $0.10 = $20,000
    print(f"\n2) PO #{po_id}: ${total:,.2f} of inventory on account")
    show(conn, "After $20,000 inventory purchase")

    emp = conn.execute("SELECT id FROM employees").fetchone()["id"]
    print("\n3) " + acct.pay_employee(conn, emp))
    show(conn, "After one payroll period")

    print("\n(optional) " + acct.month_end_close(conn, pay_bills=True))
    show(conn, "After month-end close (net 30 settled)")
    conn.close()


if __name__ == "__main__":
    main()
