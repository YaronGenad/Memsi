# Historical Tag Proposals — `is_recovery` and `is_routine`

## Methodology

**Signal construction.** Total `forecast_history.quantity` is not directly comparable across months because the active branch panel widens over time (4 branches in 2023-01 → 12 in mid-2023 → 10-12 in 2026). To extract a regime signal I restricted the panel to branches with ≥30 months of history (12 stable branches) and computed **per-branch monthly demand** = SUM(quantity) / COUNT(DISTINCT branch). This collapses the system-rollout artefact of early 2023 from the analysis (where total demand looks tiny only because few branches were live yet).

**Baselines used.**
- *Pre-war settled baseline* = mean per-branch over **2023-05..2023-09** = **97 units/branch** (chosen because the panel had stabilised at 10-12 branches AND the war had not yet started). I treat 2023-08 (125/branch, peak summer) as the upper edge of routine seasonality.
- *Post-crash plateau baseline* = mean per-branch over **2024-11..2026-02** = **~58 units/branch** (excluding 2025-06 which is an isolated dip).
- For "routine" I require: per-branch demand within roughly ±25% of the pre-war baseline of 97 (so ~73-121), AND no active war/military/ceasefire-onset flag.

**Regime change detection.** Two clear breaks: (a) **2023-10/11**: per-branch drops from 85.3 to 45.8 (-46%) coinciding with Oct-7 war start; (b) **2024-10**: per-branch crashes from 188.3 (Sep) to 39.3 (-79%), coinciding with the Iran-Lebanon escalation already flagged as `is_military_op=1`. The puzzling feature in between is **2024-05..2024-09**, when `is_war=1` was active but per-branch demand rose to 124-188, *above* the 2023 baseline. The CSV notes for these months explicitly say "summer peak — partial recovery within war" (התאוששות חלקית). I therefore treat **2024-05..2024-09 as the canonical `is_recovery=1` period within an active war** — exactly the semantic the user wants: market climbing back toward normal but not yet there, with the crisis still ongoing. The longer post-Oct-2024 plateau (Dec-2024 onward) is also recovery, anchored by the Jan-2025 Gaza ceasefire that already carries `is_ceasefire=1`.

## Proposed Tags

| year_month | current_flags | demand (total / per-branch) | is_recovery | is_routine | rationale |
|---|---|---|---|---|---|
| 2023-01 | season=winter | 30 / 7.5 | 0 | 0 | System roll-in: only 4 branches reporting; per-branch 7.5 reflects data immaturity, not real demand. Mark **ambiguous** — exclude from baseline. |
| 2023-02 | season=winter | 86 / 17.2 | 0 | 0 | Roll-in continues (5 branches). Per-branch 17 vs settled baseline 97 = 18% — data artefact, **ambiguous**. |
| 2023-03 | season=spring | 254 / 31.8 | 0 | 0 | Roll-in (8 branches). Still below true baseline due to panel incompleteness — **ambiguous**, not routine. |
| 2023-04 | jewish=1 (Pesach), travel=high | 435 / 54.4 | 0 | 0 | 8 branches; per-branch 54 still below 97 baseline. Pesach should *boost* not suppress — panel still maturing. **Ambiguous**. |
| 2023-05 | season=spring | 750 / 75.0 | 0 | 1 | First month with 10 stable branches; per-branch 75 = 77% of 97 baseline. Within routine band, no crisis. **Routine**. |
| 2023-06 | summer | 1101 / 91.8 | 0 | 1 | Per-branch 92 ≈ 95% of 97 baseline; pre-war summer onset, no flags. **Routine**. |
| 2023-07 | summer, peak=1, travel=high | 1290 / 107.5 | 0 | 1 | Per-branch 108, +11% over baseline = normal summer peak. **Routine**. |
| 2023-08 | summer, peak=1, travel=high | 1500 / 125.0 | 0 | 1 | Per-branch 125, +29% over baseline but explained by summer-peak seasonality. **Routine** (seasonal high). |
| 2023-09 | jewish=2 (HHD), travel=high | 1023 / 85.3 | 0 | 1 | Per-branch 85 = 88% of baseline; Tishrei holidays, no war yet. **Routine**. |
| 2023-10 | is_war=1, travel=collapse | 876 / 73.0 | 0 | 0 | Oct-7 war onset. Per-branch 73 = 75% of baseline, only 41% of the Aug-2023 peak (125). Active crisis, NOT recovery yet. |
| 2023-11 | is_war=1, travel=very_low | 549 / 45.8 | 0 | 0 | Trough of initial shock: per-branch 46 = 47% of baseline. Active war crisis phase. |
| 2023-12 | is_war=1, jewish=3 (Hanukkah), very_low | 582 / 48.5 | 0 | 0 | Per-branch 49, essentially flat with Nov; active war, no recovery signal. |
| 2024-01 | is_war=1, very_low | 753 / 62.8 | 0 | 0 | Per-branch 63, up from 49 (+30% MoM) but still 65% of baseline. Early stabilisation but war active and travel rated very_low — too early to call recovery. |
| 2024-02 | is_war=1, very_low | 969 / 80.8 | 1 | 0 | Per-branch 81 = 83% of baseline, +29% over war-trough avg (49). Sustained climb; **recovery** begins (still under war flag). |
| 2024-03 | is_war=1, season=spring, low | 1364 / 113.7 | 1 | 0 | Per-branch 114 surpasses baseline; clear upward trajectory from war trough. War still active → recovery, not routine. |
| 2024-04 | is_war=1, jewish=1 (Pesach), low | 1200 / 100.0 | 1 | 0 | Pesach month, per-branch 100 ≈ baseline. Travel "low" per CSV but demand recovering. War active → **recovery**. |
| 2024-05 | is_war=1, low | 1496 / 124.7 | 1 | 0 | Per-branch 125 matches Aug-2023 seasonal peak. Strong recovery within war. |
| 2024-06 | is_war=1, summer | 1448 / 120.7 | 1 | 0 | Per-branch 121, +24% over baseline. Pre-summer climb, war active. **Recovery**. |
| 2024-07 | is_war=1, summer, peak=1, low | 2084 / 173.7 | 1 | 0 | Per-branch 174, +79% over baseline. CSV explicitly notes "summer peak — partial recovery". Recovery within war. |
| 2024-08 | is_war=1, summer, peak=1, low | 2200 / 183.3 | 1 | 0 | Per-branch 183 = recovery peak. War still active per flags → recovery, not routine. |
| 2024-09 | is_war=1, military_op=1, jewish=2 (HHD), very_low | 2260 / 188.3 | 1 | 0 | Per-branch 188 = highest in series. Counter-intuitive given Lebanon op started: likely stockpiling + HHD travel. Still classified **recovery within crisis** because military_op active. |
| 2024-10 | is_war=1, military_op=1, very_low | 471 / 39.3 | 0 | 0 | Major regime crash: 188 → 39 (-79%) on Iran-Lebanon escalation. Active crisis, NOT recovery. |
| 2024-11 | is_war=1, ceasefire=1 (Lebanon), low | 478 / 43.5 | 0 | 0 | Per-branch 44 = same trough level. Lebanon ceasefire signed late Nov but Gaza war still active; demand has not climbed yet → not recovery. |
| 2024-12 | is_war=1, jewish=3 (Hanukkah), low | 653 / 59.4 | 1 | 0 | Per-branch 59, +37% MoM from Nov-trough (44). First upward signal post-Oct-crash. Gaza war active → **recovery beginning**. |
| 2025-01 | ceasefire=1 (Gaza Jan-19), recovering | 659 / 59.9 | 1 | 0 | Gaza ceasefire signed mid-month, CSV explicitly labels "recovering". Per-branch 60, holding. **Recovery**. |
| 2025-02 | ceasefire=1, recovering | 652 / 59.3 | 1 | 0 | CSV notes "post-ceasefire reconstruction". Per-branch 59, plateau forming at ~61% of 97 baseline. **Recovery**. |
| 2025-03 | ceasefire=1, spring, normal | 658 / 59.8 | 1 | 0 | Per-branch 60. CSV labels "normal" but level is still only 62% of pre-war baseline — semantically this is **recovery plateau**, not routine. |
| 2025-04 | ceasefire=1, jewish=1 (Pesach), high | 618 / 56.2 | 1 | 0 | Pesach month should peak; per-branch 56 is *below* 2023-04 panel-adjusted equivalent. Recovery, not yet routine. |
| 2025-05 | ceasefire=1, normal | 611 / 55.5 | 1 | 0 | Per-branch 56 = 57% of pre-war baseline. Clearly suppressed plateau → **recovery**. |
| 2025-06 | ceasefire=1, summer, high | 398 / 33.2 | 1 | 0 | Per-branch 33 — anomalous dip (Iran-Israel 12-day exchange in June 2025 is the most likely cause, not in current flags). Still recovery, **note as edge case**. |
| 2025-07 | ceasefire=1, summer, peak=1, high | 653 / 54.4 | 1 | 0 | Summer peak should hit ~108 (2023) or 174 (2024) per-branch; only 54 = 31% of 2024-07 peak. Heavy suppression → **recovery**. |
| 2025-08 | ceasefire=1, summer, peak=1, high | 794 / 72.2 | 1 | 0 | Per-branch 72 — best post-crash reading but still 58% of 2024-08 peak (183) and below the 75 routine floor. **Recovery**, borderline. |
| 2025-09 | ceasefire=1, jewish=2 (HHD), high | 657 / 54.8 | 1 | 0 | Per-branch 55 vs 2023-09's 85. Holiday season suppressed → **recovery**. |
| 2025-10 | ceasefire=1, high | 706 / 58.8 | 1 | 0 | Per-branch 59. Stable plateau at ~60. **Recovery**. |
| 2025-11 | ceasefire=1, normal | 678 / 61.6 | 1 | 0 | Per-branch 62 = 64% of baseline. **Recovery** plateau continues. |
| 2025-12 | ceasefire=1, jewish=3 (Hanukkah), normal | 709 / 64.5 | 1 | 0 | Per-branch 65 vs 2023-12's 49 (war trough) — better, but still 67% of pre-war baseline. **Recovery**. |
| 2026-01 | ceasefire=1, normal | 724 / 65.8 | 1 | 0 | Per-branch 66, slow upward drift. **Recovery**; not yet routine (still <75% of baseline). |
| 2026-02 | ceasefire=1, normal | 575 / 52.3 | 1 | 0 | Per-branch 52, MoM dip. **Recovery** plateau. |
| 2026-03 | ceasefire=1, spring, normal | 222 / 22.2 | 0 | 0 | Only 10 branches and unusually low total — partial-month extract (data run on 2026-05-11; March may have been re-pulled with stale ETL) or genuine collapse. **Ambiguous** — flag for data-quality check before tagging. |

## Edge Cases & Notes

**Data-immature months (2023-01..2023-04).** The active panel grows from 4→8 branches over these months and per-branch demand of 7.5..54 is below any plausible real baseline. These months reflect system rollout, not market state. I deliberately leave both flags = 0 with rationale "ambiguous" so that a future modeller can either back-fill them as `is_routine=1` if confirmed pre-war or exclude them via a separate `is_data_immature` flag (worth proposing).

**The 2024 paradox.** From Feb-2024 onward the per-branch series climbs *above* the 2023 pre-war baseline despite `is_war=1` being active the entire year. The CSV notes acknowledge this with travel_impact going from `very_low` → `low` and explicit "התאוששות חלקית" (partial recovery) language in summer. My tagging follows the CSV's spirit: these months are **`is_recovery=1, is_routine=0`** because the war flag stays on. If the user instead treats those summer-2024 months as a return to normal (which the absolute numbers would justify), they would become `is_routine=1` despite war — that is a semantic call only the user can make. I went with recovery to stay consistent with the user's definition ("recovering after crisis but not back to normal" — and the underlying crisis IS still going).

**2025-06 anomaly.** Per-branch drops from 56 (May) to 33 (Jun) then back to 54 (Jul). The 12-day Iran-Israel direct exchange in June 2025 is not captured in current flags but is the most likely driver. Suggest adding a separate `iran_strikes` event flag rather than reclassifying this month — left as `is_recovery=1` here.

**2026-03 (latest month).** Only 10 stable branches reporting and per-branch=22 (lowest non-rollup reading in the series). Combined with today's date (2026-05-11), this almost certainly reflects an in-flight ETL snapshot rather than real demand collapse. Recommend excluding from any model training run until the month is closed and re-ingested; tags left as 0/0 with explicit "ambiguous — data quality" rationale.

**No month was tagged `is_routine=1` from 2023-10 onward.** This is intentional and conservative: the war/ceasefire flags are still on throughout, demand never recovers to the 73-121 routine band (the closest is 2025-08 at 72), and the user explicitly asked us to be strict on the routine label.
