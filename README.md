# Mr. Truck Inc. bookkeeping program — step-by-step guide (ENG/TE 566)

This project is a complete solution to the computer program assignment: a small web app
(Python + Flask + SQLite) that records every business activity as a double-entry journal
entry and recomputes the income statement, balance sheet and cash flow statement after
each one. It stores full history (invoices, POs, payroll, paid bills, journal) and every
statement page has a Print button for hard copies.

## Step 1. Install the tools

1. Install Python 3.10 or newer from python.org (on Windows, tick "Add Python to PATH").
2. Open a terminal in this folder and install Flask:

   ```
   pip install -r requirements.txt
   ```

## Step 2. Understand the file layout

| File | What it does |
|---|---|
| `payroll.py` | Paycheck calculator: 2026 federal (IRS Pub. 15-T percentage method), Illinois 4.95%, Social Security 6.2%, Medicare 1.45%. All rates are constants at the top. |
| `accounting.py` | The bookkeeping engine: chart of accounts, `post()` for balanced journal entries, every transaction (invoice, PO, payroll, bills, build units, month-end close) and the three statements. |
| `db.py` | SQLite schema, the seed data (8 vendors / bill of materials, 10 customers, 1 employee, 10 expense accounts) and the initial conditions. |
| `app.py` | Flask routes: one page per menu item. |
| `templates/` | HTML pages (Jinja2). `statements.html` draws all three financial statements. |
| `static/style.css` | Styling, including print styles. |
| `run_final_assignment.py` | Runs the three required transactions in the terminal and checks the books balance. |

## Step 3. Creating the statements

Every transaction is a balanced journal entry (debits = credits). The statements are
calculated from the journal, so the balance sheet always balances:
**Assets = Liabilities + Net worth**, where **Net worth = Owner investment + Net income**.

| Transaction | Debit | Credit | Effect on statements |
|---|---|---|---|
| Initial conditions | Cash, Parts inventory, Finished goods | Owner investment | Net worth = $200,000 |
| Create invoice (net 30) | Accounts receivable; COGS | Sales; Finished goods | Sales ↑, COGS ↑, AR ↑, inventory ↓ |
| Create PO (net 30) | Parts inventory | Accounts payable | Inventory ↑, AP ↑, no income statement change |
| Build units | Finished goods | Parts inventory | Moves cost only; totals unchanged |
| Pay employee | Payroll (net pay); Payroll withholding (taxes) | Cash (gross pay) | Cash ↓, expenses ↑ |
| Pay a bill | Bill: <account> | Cash | Cash ↓, expenses ↑ |
| Month-end close | Cash; AP | AR; Cash | Receivables collected, payables paid, date +1 month |

The course rule "at the end of each month, post receivables to cash and pay your bills even
if it's not quite 30 days" is the **Close month** button on the Testing and setup page.

POs record both *quantity ordered* and *quantity received*; the vendor bills (and inventory
increases) by the quantity received, as the instructional guide describes.

## Step 4. Create the database with initial conditions

```
python db.py
```

Default initial conditions (edit `DEFAULTS` in `db.py`, or use the reset form in the app):

* Initial investment $200,000, start date 2026-01-01
* 20,000 finished trucks on hand (needed so the $50,000 sale can happen first:
  $50,000 ÷ $2.50 = 20,000 trucks)
* 10,000 truck sets of raw parts; reorder point at 5,000 sets
* Cost of goods per truck from the bill of materials = **$0.57**

Starting inventory is bought out of the investment, so the opening balance sheet is
Cash $182,900 + Inventory $17,100 = Total assets $200,000 = Net worth.

## Step 5. Check the numbers in the terminal

```
python run_final_assignment.py
```

You should see these results (and "Balanced ✔" after each step):

| After… | Sales | COGS | Payroll + withholding | Net income | Cash | AR | Inventory | AP | Net worth |
|---|---|---|---|---|---|---|---|---|---|
| Start | 0 | 0 | 0 | 0 | 182,900.00 | 0 | 17,100.00 | 0 | 200,000.00 |
| $50,000 sale | 50,000.00 | 11,400.00 | 0 | 38,600.00 | 182,900.00 | 50,000.00 | 5,700.00 | 0 | 238,600.00 |
| $20,000 purchase | 50,000.00 | 11,400.00 | 0 | 38,600.00 | 182,900.00 | 50,000.00 | 25,700.00 | 20,000.00 | 238,600.00 |
| 1 payroll | 50,000.00 | 11,400.00 | 8,875.90 + 3,624.10 | 26,100.00 | 170,400.00 | 50,000.00 | 25,700.00 | 20,000.00 | 226,100.00 |

Payroll for $150,000/yr, single, 1 IL allowance: gross $12,500.00; federal $2,061.17;
Illinois $606.68; Social Security $775.00; Medicare $181.25; net pay $8,875.90.

## Step 6. Run the program

```
python app.py
```