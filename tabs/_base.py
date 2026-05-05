# -*- coding: utf-8 -*-
"""
tabs/_base.py — תשתית משותפת לכל ה-tabs.

BaseTabWorker
    QThread עם signals אחידים:
      - progress(str)         — עדכוני סטטוס לטקסט החי
      - finished(object)      — תוצאה מוצלחת (DataFrame, dict, וכו')
      - error(str)            — traceback מפורמט (כבר logged)
    תומך ב-cancel() ב-best-effort: לבדיקה בלולאות פנימיות.
    בנוי כך שמחלקה יורשת רק מממשת _do() ומשתמשת ב-self.progress.emit().

run_in_worker(parent, fn, on_done, on_error=None, on_progress=None, **kwargs)
    helper נוח: מריץ פונקציה רגילה ב-QThread בלי להגדיר class חדש.
"""
from __future__ import annotations
import traceback
from typing import Any, Callable
from qtpy.QtCore import QThread, Signal as pyqtSignal

from logger import logger


class BaseTabWorker(QThread):
    """
    מחלקת בסיס ל-workers בכל הטאבים.

    Subclass חייבת לממש _do(self) -> Any.
    אם _do מחזיר ערך, הוא נפלט דרך finished(value).
    כל חריגה נתפסת, נרשמת ב-logger ונפלטת דרך error(traceback_str).
    """
    progress = pyqtSignal(str)
    finished = pyqtSignal(object)
    error    = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cancel_requested = False

    # ---- API ל-subclass ----
    def _do(self) -> Any:
        raise NotImplementedError

    def cancel(self):
        """בקשה לעצירה (best-effort). על ה-_do() לבדוק is_cancelled() לעיתים."""
        self._cancel_requested = True

    def is_cancelled(self) -> bool:
        return self._cancel_requested

    def emit_progress(self, msg: str):
        """כיווץ של progress.emit עם בדיקת ביטול."""
        if not self._cancel_requested:
            self.progress.emit(msg)

    # ---- QThread.run ----
    def run(self):
        try:
            result = self._do()
            if not self._cancel_requested:
                self.finished.emit(result)
        except Exception:
            tb = traceback.format_exc()
            logger.exception("%s failed", type(self).__name__)
            self.error.emit(tb)


class _FuncWorker(BaseTabWorker):
    """Worker שעוטף קריאת פונקציה רגילה."""
    def __init__(self, fn: Callable, kwargs: dict, parent=None):
        super().__init__(parent)
        self._fn = fn
        self._kwargs = kwargs

    def _do(self):
        # אם הפונקציה מקבלת progress=callable, נספק אחד
        import inspect
        sig = inspect.signature(self._fn)
        if 'progress' in sig.parameters:
            self._kwargs['progress'] = self.emit_progress
        if 'is_cancelled' in sig.parameters:
            self._kwargs['is_cancelled'] = self.is_cancelled
        return self._fn(**self._kwargs)


def run_in_worker(parent, fn: Callable, *,
                  on_done: Callable[[Any], None] | None = None,
                  on_error: Callable[[str], None] | None = None,
                  on_progress: Callable[[str], None] | None = None,
                  **kwargs) -> _FuncWorker:
    """
    הפעלה מהירה של פונקציה ב-thread עם החיבור לסיגנלים.

    שימוש:
        self._w = run_in_worker(
            self, fetch_data, year_month='2025-04',
            on_done=self._on_done,
            on_error=self._on_error,
            on_progress=self.status_text.append,
        )

    הפונקציה fn יכולה לקבל אופציונלית 'progress' (callable) ו-'is_cancelled'
    אם היא צריכה לדווח התקדמות או לבדוק ביטול.
    """
    w = _FuncWorker(fn, kwargs, parent=parent)
    if on_done:
        w.finished.connect(on_done)
    if on_error:
        w.error.connect(on_error)
    if on_progress:
        w.progress.connect(on_progress)
    w.start()
    return w


def format_error_for_user(tb: str, max_chars: int = 800) -> str:
    """
    מקצר traceback להצגה ב-QMessageBox.
    משאיר את השורה האחרונה (הסוג והמסר), ומוסיף את החלק התחתון של ה-traceback.
    """
    if not tb:
        return "שגיאה לא ידועה"
    lines = tb.strip().splitlines()
    last_line = lines[-1] if lines else ""
    if len(tb) <= max_chars:
        return tb
    head = '\n'.join(lines[:5])
    return f"{head}\n...\n{last_line}\n\n[traceback קצורה — ראה memsi.log למידע מלא]"
