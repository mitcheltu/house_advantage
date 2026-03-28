-- ============================================================
-- HOUSE ADVANTAGE — Model V2 Verification Queries
-- ============================================================
-- Purpose: Cross-reference model-flagged trades against known
-- real-world events to validate detection accuracy.
--
-- Run against: house_advantage database (MySQL 8.0)
-- Date: March 2026
-- ============================================================


-- ────────────────────────────────────────────────────────────
-- 1. OVERALL SCORING HEALTH CHECK
-- ────────────────────────────────────────────────────────────
-- Verify score distribution is reasonable: most trades should
-- be UNREMARKABLE, with a small suspicious tail.

SELECT
    severity_quadrant,
    COUNT(*)                                        AS trade_count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER(), 1) AS pct,
    ROUND(AVG(cohort_index), 1)                     AS avg_cohort,
    ROUND(AVG(baseline_index), 1)                   AS avg_baseline,
    SUM(audit_triggered)                            AS audits_triggered
FROM anomaly_scores
GROUP BY severity_quadrant
ORDER BY FIELD(severity_quadrant, 'SEVERE','SYSTEMIC','OUTLIER','UNREMARKABLE');


-- ────────────────────────────────────────────────────────────
-- 2. PELOSI TEMPUS (TEM) TRADE — Jan 2025
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Nancy Pelosi purchased Tempus AI (TEM) options
-- in Jan 2025. Widely reported — stock surged ~150%+ afterward
-- on AI healthcare momentum. This should flag as SYSTEMIC.

SELECT
    p.full_name, t.ticker, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha_30d,
    a.feat_disclosure_lag AS disclosure_lag_days
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%Pelosi%'
  AND t.ticker = 'TEM';
-- EXPECTED: severity_quadrant = SYSTEMIC, high baseline_index,
-- large positive cohort_alpha (~1.5+)


-- ────────────────────────────────────────────────────────────
-- 3. PELOSI PALO ALTO NETWORKS (PANW) — Feb 2024
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Paul Pelosi bought PANW call options Feb 2024.
-- Company reported strong earnings shortly after. Flagged by
-- multiple watchdog orgs.

SELECT
    p.full_name, t.ticker, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha_30d
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%Pelosi%'
  AND t.ticker = 'PANW';
-- EXPECTED: SYSTEMIC flag, positive alpha


-- ────────────────────────────────────────────────────────────
-- 4. TUBERVILLE HEALTHCARE TRADES
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Sen. Tommy Tuberville was investigated for
-- healthcare and defense trades while on Senate Armed Services
-- and Health committees. Multiple ethics complaints filed.

SELECT
    t.ticker, t.industry_sector, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha,
    a.feat_committee_relevance AS comm_rel,
    a.feat_proximity_days AS prox_days
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%Tuberville%'
  AND a.severity_quadrant IN ('SEVERE','SYSTEMIC')
ORDER BY a.baseline_index DESC;
-- EXPECTED: Healthcare trades should flag with high committee_relevance


-- ────────────────────────────────────────────────────────────
-- 5. TSLA TRADES AROUND 2024 ELECTION
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Multiple members of Congress bought/sold TSLA
-- in Oct-Nov 2024 around the presidential election. Musk's
-- political involvement and post-election TSLA surge (~50%)
-- made these trades internationally newsworthy.

SELECT
    p.full_name, p.party, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha_30d,
    a.feat_disclosure_lag AS lag
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE t.ticker = 'TSLA'
  AND t.trade_date BETWEEN '2024-10-01' AND '2024-11-30'
ORDER BY t.trade_date;
-- EXPECTED: Buys before election with positive alpha should be
-- SEVERE/SYSTEMIC. Sells that missed the rally should also flag
-- (negative alpha = unusual in opposite direction).


-- ────────────────────────────────────────────────────────────
-- 6. MARJORIE TAYLOR GREENE — TSLA BUY POST-ELECTION
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Rep. MTG bought TSLA on Nov 7, 2024 (2 days after
-- election). Stock surged ~30%+ post-election on DOGE speculation.
-- Well-documented in media.

SELECT
    t.ticker, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha_30d,
    a.feat_disclosure_lag AS lag
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%Greene, Marjorie%'
  AND t.ticker = 'TSLA';
-- EXPECTED: SEVERE flag, strong positive alpha


-- ────────────────────────────────────────────────────────────
-- 7. UNITEDHEALTH (UNH) CLUSTER — Apr 2025
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: UNH stock crashed ~30% in April 2025 after
-- pulled guidance, DOJ investigation, and CEO departure.
-- Multiple members bought BEFORE the crash (negative alpha)
-- and some sold right before. This cluster is highly suspicious.

SELECT
    p.full_name, p.party, p.chamber, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha_30d,
    a.feat_committee_relevance AS comm_rel,
    a.feat_proximity_days AS vote_prox
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE t.ticker = 'UNH'
  AND t.trade_date BETWEEN '2025-03-01' AND '2025-06-01'
ORDER BY t.trade_date;
-- EXPECTED: Sells before crash = positive alpha = SEVERE/SYSTEMIC
-- Buys before crash = negative alpha = also flags as anomalous
-- (institutional investors don't buy stocks that drop 30%)


-- ────────────────────────────────────────────────────────────
-- 8. LISA McCLAIN — PALANTIR (PLTR) TRADES
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Rep. McClain made notable PLTR trades in 2024.
-- PLTR surged ~300%+ in 2024 on government AI contracts.
-- She appears as one of the most-flagged politicians.

SELECT
    t.ticker, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha_30d,
    a.feat_committee_relevance AS comm_rel
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%McClain, Lisa%'
  AND t.ticker = 'PLTR'
ORDER BY t.trade_date;
-- EXPECTED: SEVERE flags, high alpha (PLTR's govt contract windfall)


-- ────────────────────────────────────────────────────────────
-- 9. TOP ACTIVE TRADERS vs. FLAGGED TRADERS
-- ────────────────────────────────────────────────────────────
-- Verify that the model isn't just flagging volume.
-- Heavy traders should NOT automatically have more flags.

SELECT
    p.full_name, p.party, p.chamber,
    COUNT(DISTINCT t.id) AS total_trades,
    SUM(CASE WHEN a.severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END) AS flagged,
    ROUND(SUM(CASE WHEN a.severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END)
          * 100.0 / COUNT(DISTINCT t.id), 1) AS flag_rate_pct,
    ROUND(AVG(a.baseline_index), 1) AS avg_baseline
FROM trades t
JOIN politicians p ON t.politician_id = p.id
LEFT JOIN anomaly_scores a ON a.trade_id = t.id
GROUP BY p.id, p.full_name, p.party, p.chamber
HAVING total_trades >= 10
ORDER BY flag_rate_pct DESC
LIMIT 25;
-- EXPECTED: High flag rate should NOT correlate perfectly with
-- high trade count. Some heavy traders should have low flag rates
-- (e.g., routine portfolio rebalancing).


-- ────────────────────────────────────────────────────────────
-- 10. SHELDON WHITEHOUSE — TSLA SELLS
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Sen. Whitehouse sold TSLA in Oct 2024, shortly
-- before the post-election surge. These were widely covered.
-- Alpha should be positive (stock went up after he sold).

SELECT
    t.ticker, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha_30d
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%Whitehouse%'
  AND t.ticker = 'TSLA'
ORDER BY t.trade_date;
-- EXPECTED: SEVERE — these are among the highest-scored trades
-- in the entire database.


-- ────────────────────────────────────────────────────────────
-- 11. SECTOR CONCENTRATION IN FLAGGED TRADES
-- ────────────────────────────────────────────────────────────
-- Which sectors are disproportionately flagged?
-- Tech and Healthcare should dominate (most legislative activity).

SELECT
    COALESCE(t.industry_sector, 'UNMAPPED') AS sector,
    COUNT(*) AS flagged,
    SUM(CASE WHEN a.severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END) AS severe,
    SUM(CASE WHEN a.severity_quadrant = 'SYSTEMIC' THEN 1 ELSE 0 END) AS systemic,
    ROUND(AVG(a.feat_cohort_alpha), 3) AS avg_alpha,
    COUNT(DISTINCT t.politician_id) AS unique_politicians
FROM anomaly_scores a
JOIN trades t ON a.trade_id = t.id
WHERE a.severity_quadrant IN ('SEVERE','SYSTEMIC')
GROUP BY COALESCE(t.industry_sector, 'UNMAPPED')
ORDER BY flagged DESC;


-- ────────────────────────────────────────────────────────────
-- 12. GOTTHEIMER — TOP FLAGGED POLITICIAN
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Rep. Josh Gottheimer (D-NJ) is one of the most
-- active stock traders in Congress. Under scrutiny from multiple
-- watchdog groups. 43 SYSTEMIC flags.

SELECT
    t.ticker, t.trade_type, t.trade_date,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha_30d,
    a.feat_proximity_days AS vote_prox,
    a.feat_committee_relevance AS comm_rel
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%Gottheimer%'
  AND a.severity_quadrant IN ('SEVERE','SYSTEMIC')
ORDER BY a.baseline_index DESC;
-- EXPECTED: High volume of SYSTEMIC flags — trades that look
-- normal within congressional norms but anomalous vs. institutional
-- investors. Validates the "widespread pattern" detection.


-- ────────────────────────────────────────────────────────────
-- 13. COMMITTEE-RELEVANT TRADES: HEALTHCARE COMMITTEE + PHARMA
-- ────────────────────────────────────────────────────────────
-- Politicians on health-related committees trading healthcare
-- stocks should have elevated committee_relevance scores.

SELECT
    p.full_name, p.party, t.ticker, t.industry_sector,
    t.trade_type, t.trade_date,
    a.severity_quadrant,
    a.feat_committee_relevance AS comm_rel,
    ROUND(a.feat_cohort_alpha, 3) AS alpha,
    GROUP_CONCAT(DISTINCT c.name ORDER BY c.name SEPARATOR '; ') AS committees
FROM anomaly_scores a
JOIN trades t ON a.trade_id = t.id
JOIN politicians p ON t.politician_id = p.id
JOIN committee_memberships cm ON cm.politician_id = p.id
JOIN committees c ON c.id = cm.committee_id
WHERE t.industry_sector = 'healthcare'
  AND a.feat_committee_relevance >= 0.7
  AND a.severity_quadrant IN ('SEVERE','SYSTEMIC')
GROUP BY a.id, p.full_name, p.party, t.ticker, t.industry_sector,
         t.trade_type, t.trade_date, a.severity_quadrant,
         a.feat_committee_relevance, a.feat_cohort_alpha
ORDER BY a.feat_committee_relevance DESC, (a.cohort_index + a.baseline_index) DESC;
-- EXPECTED: Boozman, Tuberville, Britt, Letlow should appear —
-- all sit on health-adjacent committees.


-- ────────────────────────────────────────────────────────────
-- 14. PARTY BREAKDOWN OF FLAGS
-- ────────────────────────────────────────────────────────────
-- The model should not be biased toward either party.

SELECT
    p.party,
    COUNT(DISTINCT t.id) AS total_trades,
    SUM(CASE WHEN a.severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END) AS flagged,
    ROUND(SUM(CASE WHEN a.severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END)
          * 100.0 / COUNT(*), 2) AS flag_rate_pct,
    SUM(CASE WHEN a.severity_quadrant = 'SEVERE' THEN 1 ELSE 0 END) AS severe,
    SUM(CASE WHEN a.severity_quadrant = 'SYSTEMIC' THEN 1 ELSE 0 END) AS systemic,
    ROUND(AVG(a.cohort_index), 1) AS avg_cohort,
    ROUND(AVG(a.baseline_index), 1) AS avg_baseline
FROM trades t
JOIN politicians p ON t.politician_id = p.id
LEFT JOIN anomaly_scores a ON a.trade_id = t.id
GROUP BY p.party;
-- EXPECTED: Roughly proportional flag rates between D and R.
-- Neither party should be >2x the other's flag rate.


-- ────────────────────────────────────────────────────────────
-- 15. DISCLOSURE LAG OUTLIERS
-- ────────────────────────────────────────────────────────────
-- Trades with long disclosure lags (>45 days) are themselves
-- a red flag under the STOCK Act. Who delayed disclosure?

SELECT
    p.full_name, p.party, p.chamber, t.ticker,
    t.trade_type, t.trade_date, t.disclosure_date,
    t.disclosure_lag_days,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha
FROM trades t
JOIN politicians p ON t.politician_id = p.id
LEFT JOIN anomaly_scores a ON a.trade_id = t.id
WHERE t.disclosure_lag_days > 45
ORDER BY t.disclosure_lag_days DESC
LIMIT 20;
-- REAL-WORLD: STOCK Act requires disclosure within 45 days.
-- Late filers have historically included members under investigation.


-- ────────────────────────────────────────────────────────────
-- 16. SUSIE LEE — KNOWN ETHICS INVESTIGATION
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Rep. Susie Lee (D-NV) was investigated by the
-- Office of Congressional Ethics in 2022-2023 for stock trades
-- potentially conflicting with her committee work.

SELECT
    t.ticker, t.industry_sector, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha,
    a.feat_committee_relevance AS comm_rel
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%Lee, Susie%'
ORDER BY a.baseline_index DESC;
-- EXPECTED: 5 flags (2 SEVERE, 3 SYSTEMIC) — model correctly
-- identifies her as suspicious.


-- ────────────────────────────────────────────────────────────
-- 17. NVDA TRADES — CHIPS ACT BENEFICIARY
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: NVDA was a primary beneficiary of the CHIPS and
-- Science Act. Multiple members traded NVDA around legislative
-- activity on tech/semiconductor policy.

SELECT
    p.full_name, p.party, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha,
    a.feat_proximity_days AS vote_prox,
    a.feat_committee_relevance AS comm_rel
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE t.ticker = 'NVDA'
  AND a.severity_quadrant IN ('SEVERE','SYSTEMIC','OUTLIER')
ORDER BY a.baseline_index DESC;
-- EXPECTED: SYSTEMIC flags — congressional NVDA trades
-- outperform what institutional investors achieved.


-- ────────────────────────────────────────────────────────────
-- 18. MULTI-POLITICIAN SAME-STOCK SAME-WEEK CLUSTERS
-- ────────────────────────────────────────────────────────────
-- When multiple unrelated politicians trade the same stock
-- in the same week, it suggests shared non-public information.

SELECT
    t.ticker,
    YEARWEEK(t.trade_date, 1) AS trade_week,
    MIN(t.trade_date) AS week_start,
    MAX(t.trade_date) AS week_end,
    COUNT(DISTINCT t.politician_id) AS unique_politicians,
    COUNT(*) AS total_trades,
    GROUP_CONCAT(DISTINCT p.full_name ORDER BY p.full_name SEPARATOR ', ') AS who,
    ROUND(AVG(a.baseline_index), 1) AS avg_baseline,
    ROUND(AVG(a.feat_cohort_alpha), 3) AS avg_alpha
FROM trades t
JOIN politicians p ON t.politician_id = p.id
LEFT JOIN anomaly_scores a ON a.trade_id = t.id
WHERE a.severity_quadrant IN ('SEVERE','SYSTEMIC')
GROUP BY t.ticker, YEARWEEK(t.trade_date, 1)
HAVING unique_politicians >= 2
ORDER BY unique_politicians DESC, avg_baseline DESC
LIMIT 20;
-- EXPECTED: UNH April 2025 cluster, TSLA Oct-Nov 2024 cluster


-- ────────────────────────────────────────────────────────────
-- 19. SYSTEMIC SIGNAL STRENGTH
-- ────────────────────────────────────────────────────────────
-- The core thesis: congressional trades as a WHOLE beat the
-- baseline of institutional investors. Compare average alpha.

SELECT
    'Congressional (all scored)' AS population,
    COUNT(*) AS n,
    ROUND(AVG(feat_cohort_alpha), 4) AS mean_alpha,
    ROUND(STD(feat_cohort_alpha), 4) AS std_alpha
FROM anomaly_scores

UNION ALL

SELECT
    'Congressional (SYSTEMIC only)',
    COUNT(*),
    ROUND(AVG(feat_cohort_alpha), 4),
    ROUND(STD(feat_cohort_alpha), 4)
FROM anomaly_scores
WHERE severity_quadrant = 'SYSTEMIC'

UNION ALL

SELECT
    'Congressional (SEVERE only)',
    COUNT(*),
    ROUND(AVG(feat_cohort_alpha), 4),
    ROUND(STD(feat_cohort_alpha), 4)
FROM anomaly_scores
WHERE severity_quadrant = 'SEVERE'

UNION ALL

SELECT
    'Congressional (UNREMARKABLE)',
    COUNT(*),
    ROUND(AVG(feat_cohort_alpha), 4),
    ROUND(STD(feat_cohort_alpha), 4)
FROM anomaly_scores
WHERE severity_quadrant = 'UNREMARKABLE';
-- EXPECTED: SYSTEMIC and SEVERE trades should have higher
-- absolute alpha (positive or negative) than UNREMARKABLE,
-- indicating the model correctly separates signal from noise.


-- ────────────────────────────────────────────────────────────
-- 20. BRESNAHAN — FRESHMAN TRADER
-- ────────────────────────────────────────────────────────────
-- REAL-WORLD: Rep. Robert Bresnahan (R-PA) is a freshman
-- member (sworn in Jan 2025) who quickly became one of the
-- most active traders in Congress. 42 flagged trades.

SELECT
    t.ticker, t.trade_type, t.trade_date,
    t.amount_lower, t.amount_upper,
    a.cohort_index, a.baseline_index, a.severity_quadrant,
    ROUND(a.feat_cohort_alpha, 3) AS alpha,
    a.feat_committee_relevance AS comm_rel
FROM trades t
JOIN politicians p ON t.politician_id = p.id
JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%Bresnahan%'
  AND a.severity_quadrant IN ('SEVERE','SYSTEMIC')
ORDER BY a.baseline_index DESC
LIMIT 20;
-- EXPECTED: High flag count for a freshman is itself notable.
-- Compare his flag rate to other freshmen.


-- ────────────────────────────────────────────────────────────
-- 21. SCORE CALIBRATION: DO HIGH SCORES = HIGH ABSOLUTE ALPHA?
-- ────────────────────────────────────────────────────────────
-- The models should assign higher scores to trades with more
-- extreme market-beating (or market-losing) returns.

SELECT
    CASE
        WHEN ABS(feat_cohort_alpha) < 0.05 THEN '<5%'
        WHEN ABS(feat_cohort_alpha) < 0.10 THEN '5-10%'
        WHEN ABS(feat_cohort_alpha) < 0.20 THEN '10-20%'
        WHEN ABS(feat_cohort_alpha) < 0.50 THEN '20-50%'
        ELSE '>50%'
    END AS abs_alpha_bucket,
    COUNT(*) AS trades,
    ROUND(AVG(cohort_index), 1) AS avg_cohort,
    ROUND(AVG(baseline_index), 1) AS avg_baseline,
    SUM(CASE WHEN severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END) AS flagged
FROM anomaly_scores
GROUP BY abs_alpha_bucket
ORDER BY FIELD(abs_alpha_bucket, '<5%','5-10%','10-20%','20-50%','>50%');
-- EXPECTED: Higher alpha buckets should have higher average
-- scores and more flags. This validates model calibration.


-- ────────────────────────────────────────────────────────────
-- 22. FALSE NEGATIVE CHECK: KNOWN SUSPICIOUS, NOT FLAGGED?
-- ────────────────────────────────────────────────────────────
-- Search for well-known suspicious traders whose trades
-- might NOT have been flagged (potential false negatives).

SELECT
    p.full_name, p.party,
    COUNT(*) AS total_trades,
    SUM(CASE WHEN a.severity_quadrant IN ('SEVERE','SYSTEMIC') THEN 1 ELSE 0 END) AS flagged,
    ROUND(AVG(a.baseline_index), 1) AS avg_baseline,
    ROUND(AVG(ABS(a.feat_cohort_alpha)), 3) AS avg_abs_alpha
FROM trades t
JOIN politicians p ON t.politician_id = p.id
LEFT JOIN anomaly_scores a ON a.trade_id = t.id
WHERE p.full_name LIKE '%Pelosi%'
   OR p.full_name LIKE '%Tuberville%'
   OR p.full_name LIKE '%Crenshaw%'
   OR p.full_name LIKE '%Ossoff%'
   OR p.full_name LIKE '%Hagerty%'
   OR p.full_name LIKE '%Lee, Susie%'
   OR p.full_name LIKE '%Greene, Marjorie%'
   OR p.full_name LIKE '%Gottheimer%'
   OR p.full_name LIKE '%McClain, Lisa%'
GROUP BY p.id, p.full_name, p.party
ORDER BY flagged DESC;
-- EXPECTED: All should have at least SOME flags. Pelosi and
-- Tuberville are household names for this issue. If they have
-- 0 flags, the model needs investigation.
