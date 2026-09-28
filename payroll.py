"""
payroll.py - Paycheck calculator (federal, Illinois, Social Security, Medicare).

All tax constants live at the top of this file so they can be updated each year.
Sources (tax year 2026):
  * IRS Publication 15-T (2026), Worksheet 1A + Annual Percentage Method tables,
    STANDARD schedules (Form W-4 from 2020 or later, Step 2 box NOT checked).
  * Illinois Booklet IL-700-T (2026): flat 4.95%, $2,925 per IL-W-4 allowance.
  * Social Security 6.2% up to the annual wage base; Medicare 1.45%
    (+0.9% additional Medicare tax on wages over $200,000).
"""

TAX_YEAR = 2026
PAY_PERIODS_PER_YEAR = 12          # the business pays salary once a month

# --- Federal (Pub. 15-T, Worksheet 1A line 1g adjustment) --------------------
W4_ADJUSTMENT = {"single": 8_600, "married": 12_900}

# Annual Percentage Method, STANDARD schedules: (bracket starts at, rate)
FEDERAL_BRACKETS = {
    "single": [
        (0, 0.00), (7_500, 0.10), (19_900, 0.12), (57_900, 0.22),
        (113_200, 0.24), (209_275, 0.32), (263_725, 0.35), (648_100, 0.37),
    ],
    "married": [  # married filing jointly
        (0, 0.00), (19_300, 0.10), (44_100, 0.12), (120_100, 0.22),
        (230_700, 0.24), (422_850, 0.32), (531_750, 0.35), (788_000, 0.37),
    ],
}
SUPPLEMENTAL_RATE = 0.22           # flat federal rate for bonuses

# --- Illinois -----------------------------------------------------------------
STATE_RATE = 0.0495
STATE_ALLOWANCE = 2_925            # per IL-W-4 line 1 allowance, per year

# --- FICA ---------------------------------------------------------------------
SOCIAL_SECURITY_RATE = 0.062
SOCIAL_SECURITY_WAGE_BASE = 184_500
MEDICARE_RATE = 0.0145
ADDITIONAL_MEDICARE_RATE = 0.009
ADDITIONAL_MEDICARE_THRESHOLD = 200_000


def _bracket_tax(amount, brackets):
    """Progressive tax on `amount` using (start, rate) brackets."""
    tax = 0.0
    for i, (start, rate) in enumerate(brackets):
        end = brackets[i + 1][0] if i + 1 < len(brackets) else float("inf")
        if amount > start:
            tax += (min(amount, end) - start) * rate
    return tax


def federal_withholding(regular_wages, filing_status="single", periods=PAY_PERIODS_PER_YEAR):
    """Federal income tax for one pay period (percentage method)."""
    status = filing_status if filing_status in FEDERAL_BRACKETS else "single"
    annual = regular_wages * periods
    adjusted = max(0.0, annual - W4_ADJUSTMENT[status])
    return round(_bracket_tax(adjusted, FEDERAL_BRACKETS[status]) / periods, 2)


def state_withholding(gross, allowances=1, periods=PAY_PERIODS_PER_YEAR):
    """Illinois withholding: 4.95% of wages after allowances."""
    taxable = max(0.0, gross - allowances * STATE_ALLOWANCE / periods)
    return round(taxable * STATE_RATE, 2)


def calculate_paycheck(annual_salary, bonus=0.0, filing_status="single",
                       state_allowances=1, ytd_wages=0.0,
                       periods=PAY_PERIODS_PER_YEAR):
    """
    Return a dict describing one paycheck.
    ytd_wages = wages already paid this calendar year (for the Social Security
    wage base and the additional-Medicare threshold).
    """
    salary = round(annual_salary / periods, 2)
    bonus = round(float(bonus or 0), 2)
    gross = round(salary + bonus, 2)

    federal = federal_withholding(salary, filing_status, periods)
    federal = round(federal + bonus * SUPPLEMENTAL_RATE, 2)

    state = state_withholding(gross, state_allowances, periods)

    ss_room = max(0.0, SOCIAL_SECURITY_WAGE_BASE - ytd_wages)
    social_security = round(min(gross, ss_room) * SOCIAL_SECURITY_RATE, 2)

    medicare = gross * MEDICARE_RATE
    over = max(0.0, ytd_wages + gross - max(ADDITIONAL_MEDICARE_THRESHOLD, ytd_wages))
    medicare = round(medicare + over * ADDITIONAL_MEDICARE_RATE, 2)

    withheld = round(federal + state + social_security + medicare, 2)
    return {
        "salary": salary,
        "bonus": bonus,
        "gross": gross,
        "federal": federal,
        "state": state,
        "social_security": social_security,
        "medicare": medicare,
        "total_withheld": withheld,
        "net": round(gross - withheld, 2),
    }


if __name__ == "__main__":
    # Quick check for the course employee: $150,000/yr, single, 1 IL allowance
    for k, v in calculate_paycheck(150_000).items():
        print(f"{k:>16}: {v:>10,.2f}")
