-- Finance data model (DuckDB).
-- Inputs registered by model.py: gl, account_mapping, department_mapping, coa, entities, fx,
-- budget, budget_line_mapping, budget_fx.
-- Sign convention for P&L views: "profit-signed" (income +, expense -), so totals add up to
-- operating result and a positive variance is always favourable.

CREATE OR REPLACE VIEW fx_all AS
SELECT period, currency, avg_rate_to_usd, close_rate_to_usd FROM fx
UNION ALL
SELECT DISTINCT period, 'USD', 1.0, 1.0 FROM fx;

-- 1. Every GL line with its group account, group department and currency.
CREATE OR REPLACE VIEW gl_mapped AS
SELECT
    g.*,
    m.group_account                    AS account,
    c.account_name,
    c.account_type,
    c.statement_line,
    CASE
        WHEN g.local_department = '' THEN NULL
        ELSE COALESCE(d.department, 'UNALLOCATED')
    END                                AS department,
    e.currency
FROM gl AS g
JOIN entities AS e USING (entity)
LEFT JOIN account_mapping AS m
       ON m.entity = g.entity AND m.local_account = g.local_account
LEFT JOIN coa AS c
       ON c.account = m.group_account
LEFT JOIN department_mapping AS d
       ON d.source = g.entity AND d.local_department = g.local_department;

-- 2. P&L lines in USD at the monthly average rate.
CREATE OR REPLACE VIEW pl_lines AS
SELECT
    gm.entity, gm.period, gm.account, gm.account_name, gm.account_type, gm.statement_line,
    COALESCE(gm.department, 'UNALLOCATED')              AS department,
    (gm.credit - gm.debit)                              AS pl_local,
    (gm.credit - gm.debit) * fx.avg_rate_to_usd         AS pl_usd
FROM gl_mapped AS gm
JOIN fx_all AS fx ON fx.period = gm.period AND fx.currency = gm.currency
WHERE gm.account_type IN ('revenue', 'cogs', 'opex', 'other');

-- 3. Monthly P&L by entity, consolidated: intercompany recharges are eliminated.
CREATE OR REPLACE VIEW pl_monthly AS
SELECT entity, period, account, account_name, account_type, statement_line, department,
       SUM(pl_local) AS actual_local, SUM(pl_usd) AS actual_usd
FROM pl_lines
WHERE account NOT IN ('4900', '6900')
GROUP BY ALL;

-- 4. Cash balance by entity at each month end (cumulative local balance x closing rate).
CREATE OR REPLACE VIEW cash_balance AS
WITH monthly AS (
    SELECT entity, currency, period, SUM(debit - credit) AS movement
    FROM gl_mapped
    WHERE account = '1000'
    GROUP BY ALL
)
SELECT m.entity, m.period,
       SUM(m.movement) OVER (PARTITION BY m.entity ORDER BY m.period) AS cash_local,
       SUM(m.movement) OVER (PARTITION BY m.entity ORDER BY m.period) * fx.close_rate_to_usd AS cash_usd
FROM monthly AS m
JOIN fx_all AS fx ON fx.period = m.period AND fx.currency = m.currency;

-- 5. Budget in the same shape: mapped, profit-signed, at budget FX and at actual FX.
CREATE OR REPLACE VIEW budget_monthly AS
SELECT
    b.entity, b.period, l.account, c.account_name, c.account_type, c.statement_line,
    COALESCE(d.department, 'UNALLOCATED')                                     AS department,
    SUM(CASE WHEN c.account_type IN ('revenue', 'other') THEN 1 ELSE -1 END
        * b.amount_local)                                                     AS budget_local,
    SUM(CASE WHEN c.account_type IN ('revenue', 'other') THEN 1 ELSE -1 END
        * b.amount_local * bfx.budget_rate_to_usd)                            AS budget_usd,
    SUM(CASE WHEN c.account_type IN ('revenue', 'other') THEN 1 ELSE -1 END
        * b.amount_local * fx.avg_rate_to_usd)                                AS budget_usd_actual_fx
FROM budget AS b
JOIN entities AS e USING (entity)
JOIN budget_line_mapping AS l ON l.budget_line = b.budget_line
JOIN coa AS c ON c.account = l.account
JOIN budget_fx AS bfx ON bfx.currency = e.currency
JOIN fx_all AS fx ON fx.period = b.period AND fx.currency = e.currency
LEFT JOIN department_mapping AS d
       ON d.source = 'BUDGET' AND d.local_department = b.local_department
GROUP BY ALL;

-- 6. Budget vs actual. Revenue and COGS are planned without departments, so they are compared
--    at that grain; opex is compared by department.
CREATE OR REPLACE VIEW bva AS
WITH actual AS (
    SELECT entity, period, account, account_name, account_type, statement_line,
           CASE WHEN account_type IN ('revenue', 'cogs', 'other') AND account <> '5100'
                THEN 'UNALLOCATED' ELSE department END AS department,
           SUM(actual_usd) AS actual_usd
    FROM pl_monthly
    WHERE period IN (SELECT DISTINCT period FROM budget)
    GROUP BY ALL
)
SELECT
    COALESCE(a.entity, b.entity)                  AS entity,
    COALESCE(a.period, b.period)                  AS period,
    COALESCE(a.account, b.account)                AS account,
    COALESCE(a.account_name, b.account_name)      AS account_name,
    COALESCE(a.account_type, b.account_type)      AS account_type,
    COALESCE(a.statement_line, b.statement_line)  AS statement_line,
    COALESCE(a.department, b.department)          AS department,
    COALESCE(a.actual_usd, 0)                     AS actual_usd,
    COALESCE(b.budget_usd, 0)                     AS budget_usd,
    COALESCE(b.budget_usd_actual_fx, 0)           AS budget_usd_actual_fx,
    COALESCE(a.actual_usd, 0) - COALESCE(b.budget_usd, 0)            AS variance_usd,
    COALESCE(b.budget_usd_actual_fx, 0) - COALESCE(b.budget_usd, 0)  AS fx_effect_usd
FROM actual AS a
FULL OUTER JOIN budget_monthly AS b
  ON a.entity = b.entity AND a.period = b.period AND a.account = b.account AND a.department = b.department;
