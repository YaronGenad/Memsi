-- 015_fix_2026_war_events.sql
-- Sprint C8.0: תיקון נתוני 2026 ב-forecast_events.
--
-- ההיסטוריה: forecast_events.csv תויג ב-Jan 2026 כש"לא ידענו" שתפרוץ
-- מלחמת Roar of Lion ב-Feb-Mar 2026. ב-CSV הוקלדו ידנית 2026-01/02/03
-- כ-is_ceasefire=1, conversion_regime=LOW, notes="שגרה". המלחמה פרצה,
-- ה-CSV לא עודכן, ה-DB נטען עם הנתונים השגויים, ומודלי-תחזית עבדו
-- בהנחה ש-Feb/Mar היו "שגרה".
--
-- התוצאה: תחזית מאי 2026 יצאה 810 כשactual היה 396 (פער +105%).
-- ה-models הסתמכו על rolling-12 של חודשי-שגרה ולא הבחינו שמרץ-אפריל
-- היו war/recovery (244, 255 בפועל).
--
-- ה-migration הזאת:
-- 1. מתקנת את 4 ה-rows הנכונים (Feb=military_op, Mar=war, Apr=recovery,
--    May=routine post-war).
-- 2. CSV עודכן במקביל, אז install חדש יקבל את הערכים הנכונים מהCSV.
-- 3. ב-instances קיימים, ה-UPDATE לפי year_month מחליף את ה-rows.

UPDATE forecast_events SET
  is_war           = 0,
  is_military_op   = 1,
  is_ceasefire     = 0,
  travel_impact    = 'low',
  conversion_regime = 'HIGH',
  notes            = 'Roar of Lion start (peak_attack)'
WHERE year_month = '2026-02';

UPDATE forecast_events SET
  is_war           = 1,
  is_military_op   = 0,
  is_ceasefire     = 0,
  travel_impact    = 'very_low',
  conversion_regime = 'HIGH',
  notes            = 'Roar of Lion full war'
WHERE year_month = '2026-03';

INSERT INTO forecast_events
  (year_month, is_war, is_military_op, is_ceasefire, jewish_holiday,
   season, is_summer_peak, travel_impact, conversion_regime, notes)
VALUES
  ('2026-04', 0, 0, 1, 0, 2, 0, 'recovering', 'MEDIUM',
   'Recovery after Roar of Lion (Pesach)')
ON CONFLICT (year_month) DO UPDATE SET
  is_war           = EXCLUDED.is_war,
  is_military_op   = EXCLUDED.is_military_op,
  is_ceasefire     = EXCLUDED.is_ceasefire,
  travel_impact    = EXCLUDED.travel_impact,
  conversion_regime = EXCLUDED.conversion_regime,
  notes            = EXCLUDED.notes;

INSERT INTO forecast_events
  (year_month, is_war, is_military_op, is_ceasefire, jewish_holiday,
   season, is_summer_peak, travel_impact, conversion_regime, notes)
VALUES
  ('2026-05', 0, 0, 1, 0, 2, 0, 'normal', 'LOW',
   'Routine post-war')
ON CONFLICT (year_month) DO UPDATE SET
  is_war           = EXCLUDED.is_war,
  is_military_op   = EXCLUDED.is_military_op,
  is_ceasefire     = EXCLUDED.is_ceasefire,
  travel_impact    = EXCLUDED.travel_impact,
  conversion_regime = EXCLUDED.conversion_regime,
  notes            = EXCLUDED.notes;
