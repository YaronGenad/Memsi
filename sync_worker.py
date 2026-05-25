# -*- coding: utf-8 -*-
"""
sync_worker.py — QThread worker שמריץ את nightly_sync ב-background.

המנגנון: ה-GUI מציג דיאלוג עם progress. ה-worker רץ ב-thread נפרד וכותב
progress דרך signals. ה-GUI מציג מה שהוא מקבל. בסיום, ה-worker emit-ים
status (records_pulled / errors).

Sprint C7.1 — בחירה פר-שלב.
Sprint C7.2 — tier-based parallelism. שלבים שלא תלויים אחד בשני רצים במקביל.
  Tier-1: priority_rolling, partbal, iaa, flight_schedule (4 במקביל)
  Tier-2: logfile_full, local_inventory (אחרי tier-1; שניהם תלויים במה
          שתופס priority_rolling/partbal)
  Tier-3: forecast_history (אחרי tier-2; aggregator)

ה-worker מקבל set של מזהי-שלבים שצריך להריץ. ה-UI מאפשר למשתמש לבחור.
"""
from __future__ import annotations
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from qtpy.QtCore import QThread, Signal as pyqtSignal
from logger import logger


# רשימת השלבים הזמינים + תיאור + הערכת-זמן (לתצוגה ב-UI).
SYNC_STEPS = [
    ('priority_rolling', 'מסמכים ותנועות (30 ימים)', '~1-2 דק\''),
    ('partbal',          'מלאי-בפועל מ-Priority',     '~3-5 דק\''),
    ('logfile_full',     'תנועות-מלאי מלאות (לתחזיות)', '~1-3 דק\''),
    ('local_inventory',  'מלאי-מקומי + סטים',         '~3-5 דק\''),
    ('forecast_history', 'אגרגציית-תחזית חודשית',    '~5 שניות'),
    ('iaa',              'נחיתות-נתב"ג היסטוריות',    '~10 שניות'),
    ('flight_schedule',  'לוח-טיסות עתידי',           '~30 שניות'),
]

DEFAULT_STEPS = {'priority_rolling', 'partbal', 'forecast_history',
                  'iaa', 'flight_schedule'}

ALL_STEPS = {s[0] for s in SYNC_STEPS}

# Tier execution order: כל tier רץ במקביל, tiers רצים בסדר.
SYNC_TIERS: list[list[str]] = [
    ['priority_rolling', 'partbal', 'iaa', 'flight_schedule'],
    ['logfile_full', 'local_inventory'],
    ['forecast_history'],
]

# כמה workers במקביל פר-tier. 4 כי tier-1 הוא הגדול (4 שלבים) ואנחנו
# רוצים להגביל לחץ על Priority OData.
_TIER_MAX_WORKERS = 4


class SyncWorker(QThread):
    """מריץ שלבים נבחרים של nightly_sync ב-background, בקבוצות-מקבילות.

    Signals:
      step_started(str)         — תחילת שלב (מ-thread כלשהו)
      step_done(str, dict)      — סיום שלב עם הסיכום שלו
      finished_ok(dict)         — סנכרון הסתיים בהצלחה, dict = records_pulled
      finished_failed(str)      — נכשל לחלוטין
      finished_partial(dict, str) — חלקית: גם תוצאות וגם שגיאה
    """
    step_started     = pyqtSignal(str)
    step_done        = pyqtSignal(str, dict)
    finished_ok      = pyqtSignal(dict)
    finished_failed  = pyqtSignal(str)
    finished_partial = pyqtSignal(dict, str)

    def __init__(self, steps: set[str] | None = None, days: int = 30,
                 triggered_by: str = 'app-startup'):
        super().__init__()
        self.steps = ALL_STEPS & (steps if steps is not None else DEFAULT_STEPS)
        self.days = days
        self.triggered_by = triggered_by
        self._pulled: dict = {}
        self._errors: list[str] = []
        self._cancel_requested = False
        # נועל את כתיבות ה-state המשותף (pulled+errors+update_progress)
        self._state_lock = threading.Lock()

    def cancel(self):
        """בקשה לעצור אחרי השלב הנוכחי. השלב הנוכחי לא ייפסק באמצע."""
        self._cancel_requested = True
        logger.info("SyncWorker cancel requested")

    def run(self):
        try:
            from nightly_sync import (
                sync_priority_rolling, sync_partbal, sync_iaa,
                sync_logfile_full, sync_local_inventory, sync_forecast_history,
                sync_flight_schedule,
            )
            from sync_runs import start_run, finish_run

            if not self.steps:
                self.finished_failed.emit("לא נבחרו שלבים לסנכרון")
                return

            run_id = start_run(triggered_by=self.triggered_by)
            logger.info("SyncWorker started run %d, steps=%s", run_id, sorted(self.steps))

            # מיפוי שלב -> (פונקציה, kwargs)
            step_fns = {
                'priority_rolling': (sync_priority_rolling, {'days': self.days}),
                'partbal':          (sync_partbal,          {}),
                'logfile_full':     (sync_logfile_full,     {}),
                'local_inventory':  (sync_local_inventory,  {}),
                'forecast_history': (sync_forecast_history, {}),
                'iaa':              (sync_iaa,              {}),
                'flight_schedule':  (sync_flight_schedule,  {}),
            }

            for tier_idx, tier in enumerate(SYNC_TIERS, start=1):
                if self._cancel_requested:
                    logger.info("SyncWorker cancel honored before tier %d", tier_idx)
                    break
                # מסננים רק שלבים שהמשתמש בחר ושיש עליהם פונקציה
                active = [name for name in tier
                          if name in self.steps and name in step_fns]
                if not active:
                    continue

                logger.info("SyncWorker tier %d: %s", tier_idx, active)
                # מקסימום workers = מספר השלבים בפועל ב-tier (אין טעם ביותר)
                max_workers = min(len(active), _TIER_MAX_WORKERS)
                with ThreadPoolExecutor(max_workers=max_workers,
                                        thread_name_prefix=f'sync-t{tier_idx}') as ex:
                    futures = {
                        ex.submit(self._step, run_id, name, *step_fns[name]): name
                        for name in active
                    }
                    for fut in as_completed(futures):
                        # _step מטפל בחריגות פנימית; לא צריך לעטוף כאן
                        fut.result()

            if not self._errors:
                status = 'ok'
            elif self._pulled:
                status = 'partial'
            else:
                status = 'failed'

            finish_run(
                run_id=run_id,
                status=status,
                records_pulled=self._pulled,
                errors_count=len(self._errors),
                last_error_text='\n'.join(self._errors) if self._errors else None,
            )

            if self._cancel_requested:
                self.finished_partial.emit(self._pulled, "בוטל ע\"י המשתמש")
            elif status == 'ok':
                self.finished_ok.emit(self._pulled)
            elif status == 'partial':
                self.finished_partial.emit(self._pulled, '\n'.join(self._errors))
            else:
                self.finished_failed.emit('\n'.join(self._errors))

        except Exception as e:
            logger.exception("SyncWorker crashed")
            self.finished_failed.emit(f"{type(e).__name__}: {e}")

    def _step(self, run_id: int, name: str, fn, kwargs: dict):
        """עוטף שלב יחיד עם signals + try/except. רץ ב-thread של ה-executor."""
        from sync_runs import update_progress
        self.step_started.emit(name)
        try:
            result = fn(lg=logger, **kwargs)
            with self._state_lock:
                self._pulled.update(result)
                # snapshot של pulled כדי לא להחזיק את הנעילה תוך כדי DB I/O
                snapshot = dict(self._pulled)
            update_progress(run_id, snapshot)
            self.step_done.emit(name, result)
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            logger.error("SyncWorker step %s failed:\n%s", name, tb)
            with self._state_lock:
                self._errors.append(f"{name}: {type(e).__name__}: {e}")
            # ממשיכים לשלב הבא — אל תכשיל את כל הסנכרון בגלל שלב יחיד
