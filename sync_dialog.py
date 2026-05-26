# -*- coding: utf-8 -*-
"""
sync_dialog.py — דיאלוגי-סנכרון: בחירת-שלבים + progress.

זרימה:
1. הדיאלוג נפתח במצב **selection** — checkboxes פר-שלב + הערכת-זמן.
   המשתמש מסמן מה הוא רוצה, ולוחץ "התחל סנכרון".
2. אחרי הלחיצה — מצב **running**: status label, progress bar, "ביטול".
3. בסיום — title צבעוני (ירוק/כתום/אדום) + "סגור".

שני סוגים:
- SmallSyncDialog: בפינה הימנית-תחתונה, לא חוסם. נפתח כשעבר <24 שעות.
- BigSyncDialog: מודלי במרכז המסך, חוסם. נפתח כשעבר >=24 שעות.

הם נבדלים בגודל ומדיניות "חוסם או לא"; ה-flow זהה.
"""
from __future__ import annotations
from qtpy.QtCore import Qt, QPoint
from qtpy.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QProgressBar,
    QPushButton, QCheckBox, QStackedWidget, QWidget, QFrame,
)

from sync_worker import SYNC_STEPS, DEFAULT_STEPS


# שמות-עברית קצרים לשלבים — לתצוגה כשרצים כמה במקביל (tier-based).
_STEP_LABELS = {
    'priority_rolling': 'מסמכים+תנועות',
    'partbal':          'מלאי-Priority',
    'logfile_full':     'תנועות-מלאות',
    'local_inventory':  'מלאי-מקומי+סטים',
    'forecast_history': 'אגרגציית-תחזית',
    'iaa':              'נחיתות-נתב"ג',
    'flight_schedule':  'לוח-טיסות',
}


def _format_pulled(pulled: dict) -> str:
    parts = []
    if 'documents' in pulled:
        parts.append(f"{pulled['documents']} מסמכים")
    if 'logfile' in pulled:
        parts.append(f"{pulled['logfile']} תנועות")
    if 'partbal_rows' in pulled:
        parts.append(f"{pulled['partbal_rows']:,} פריטי מלאי")
    if pulled.get('iaa_months_synced'):
        parts.append(f"{pulled['iaa_months_synced']} חודשי IAA")
    if pulled.get('flight_schedule_rows'):
        parts.append(f"{pulled['flight_schedule_rows']} שורות לו\"ז")
    return ' • '.join(parts) if parts else 'אין נתונים חדשים'


class _BaseSyncDialog(QDialog):
    """דיאלוג עם 2 מצבים: selection ואז running.

    Worker נוצר מבחוץ — הדיאלוג לא יודע לבד מתי להתחיל. ה-caller צריך
    לקרוא ל-`exec()` או `show()`, ואז להאזין ל-signal `start_requested`
    כדי לקבל את ה-set של השלבים שהמשתמש בחר.
    """

    # API שה-caller יכול לחבר אליו
    from qtpy.QtCore import Signal as _Signal
    start_requested = _Signal(set)   # set[str] של שלבים נבחרים
    cancel_requested = _Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("סנכרון מסד נתונים")
        self._auto_close = True
        self._worker = None
        self._active_steps: list[str] = []  # ordered, פר-tier יש כמה
        self._build_ui()

    # ────────────────────────────────────────────────
    # UI
    # ────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(16, 12, 16, 12)

        self.stack = QStackedWidget()
        root.addWidget(self.stack)

        self.stack.addWidget(self._build_selection_page())
        self.stack.addWidget(self._build_running_page())

    def _build_selection_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(8)
        v.setContentsMargins(0, 0, 0, 0)

        title = QLabel("בחרו אילו שלבים לסנכרן")
        title.setStyleSheet("font-size:14px; font-weight:bold; color:#2c3e50;")
        v.addWidget(title)

        hint = QLabel(
            "השלבים המסומנים מראש הם המהירים. שני הכבדים "
            "(תנועות מלאות, מלאי-מקומי) דורשים אישור ידני."
        )
        hint.setStyleSheet("font-size:11px; color:#7f8c8d;")
        hint.setWordWrap(True)
        v.addWidget(hint)

        # רשימת ה-checkboxes
        self._step_checks: dict[str, QCheckBox] = {}
        for name, label, eta in SYNC_STEPS:
            cb = QCheckBox(f"{label}    [{eta}]")
            cb.setChecked(name in DEFAULT_STEPS)
            cb.setStyleSheet("font-size:12px; padding:2px;")
            self._step_checks[name] = cb
            v.addWidget(cb)

        # קו מפריד
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet("color:#bdc3c7;")
        v.addWidget(sep)

        # כפתורים
        h = QHBoxLayout()
        self._cancel_select_btn = QPushButton("ביטול")
        self._cancel_select_btn.clicked.connect(self.reject)
        h.addWidget(self._cancel_select_btn)
        h.addStretch()
        self._start_btn = QPushButton("התחל סנכרון")
        self._start_btn.setStyleSheet(
            "background:#27ae60; color:white; padding:6px 14px; font-weight:bold;"
        )
        self._start_btn.clicked.connect(self._on_start_clicked)
        h.addWidget(self._start_btn)
        v.addLayout(h)

        return page

    def _build_running_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setSpacing(10)
        v.setContentsMargins(0, 0, 0, 0)

        self.title_lbl = QLabel("מסנכרן...")
        self.title_lbl.setStyleSheet("font-size:14px; font-weight:bold; color:#2c3e50;")
        v.addWidget(self.title_lbl)

        self.status_lbl = QLabel("מתחבר...")
        self.status_lbl.setStyleSheet("font-size:12px; color:#34495e;")
        self.status_lbl.setWordWrap(True)
        v.addWidget(self.status_lbl)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # indeterminate
        v.addWidget(self.progress)

        h = QHBoxLayout()
        h.addStretch()
        self._cancel_run_btn = QPushButton("בטל")
        self._cancel_run_btn.clicked.connect(self._on_cancel_clicked)
        h.addWidget(self._cancel_run_btn)
        self.close_btn = QPushButton("סגור")
        self.close_btn.setEnabled(False)
        self.close_btn.clicked.connect(self.accept)
        h.addWidget(self.close_btn)
        v.addLayout(h)

        return page

    # ────────────────────────────────────────────────
    # Selection → start
    # ────────────────────────────────────────────────
    def _on_start_clicked(self):
        selected = {name for name, cb in self._step_checks.items() if cb.isChecked()}
        if not selected:
            self.status_lbl.setText("לא נבחרו שלבים")
            return
        self.start_requested.emit(selected)
        # עוברים למצב running; ה-caller יוצר worker וקורא ל-attach_worker
        self.stack.setCurrentIndex(1)

    def _on_cancel_clicked(self):
        if self._worker is not None and self._worker.isRunning():
            self._cancel_run_btn.setEnabled(False)
            self._cancel_run_btn.setText("מבטל...")
            self.cancel_requested.emit()
        else:
            self.reject()

    # ────────────────────────────────────────────────
    # Worker attach (נקרא מ-gui_app אחרי start_requested)
    # ────────────────────────────────────────────────
    def attach_worker(self, worker):
        """מחבר את ה-worker שה-caller יצר. חייב להיקרא אחרי start_requested."""
        self._worker = worker
        worker.step_started.connect(self._on_step_started)
        worker.step_done.connect(self._on_step_done)
        worker.finished_ok.connect(self._on_ok)
        worker.finished_partial.connect(self._on_partial)
        worker.finished_failed.connect(self._on_failed)

    # ────────────────────────────────────────────────
    # Running callbacks
    # ────────────────────────────────────────────────
    def _on_step_started(self, name: str):
        if name not in self._active_steps:
            self._active_steps.append(name)
        self._refresh_active_label()

    def _on_step_done(self, name: str, result: dict):
        if name in self._active_steps:
            self._active_steps.remove(name)
        self._refresh_active_label()

    def _refresh_active_label(self):
        if not self._active_steps:
            self.status_lbl.setText("מסיים...")
            return
        labels = [_STEP_LABELS.get(n, n) for n in self._active_steps]
        prefix = "מסנכרן במקביל: " if len(labels) > 1 else "מסנכרן: "
        self.status_lbl.setText(prefix + " • ".join(labels))

    def _on_ok(self, pulled: dict):
        self.title_lbl.setText("הסנכרון הסתיים בהצלחה")
        self.title_lbl.setStyleSheet("font-size:14px; font-weight:bold; color:#27ae60;")
        self.status_lbl.setText(_format_pulled(pulled))
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self._cancel_run_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        if self._auto_close:
            from qtpy.QtCore import QTimer
            QTimer.singleShot(2000, self.accept)

    def _on_partial(self, pulled: dict, errors: str):
        self.title_lbl.setText("הסנכרון הסתיים חלקית")
        self.title_lbl.setStyleSheet("font-size:14px; font-weight:bold; color:#e67e22;")
        self.status_lbl.setText(
            f"{_format_pulled(pulled)}\nשגיאות:\n{errors[:300]}"
        )
        self.progress.setRange(0, 100)
        self.progress.setValue(100)
        self._cancel_run_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self._auto_close = False

    def _on_failed(self, error: str):
        self.title_lbl.setText("הסנכרון נכשל")
        self.title_lbl.setStyleSheet("font-size:14px; font-weight:bold; color:#e74c3c;")
        self.status_lbl.setText(error[:300])
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self._cancel_run_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        self._auto_close = False


class SmallSyncDialog(_BaseSyncDialog):
    """דיאלוג קטן בפינה הימנית-תחתונה. לא חוסם — המשתמש יכול לעבוד.

    מוצג כשעבר <24 שעות מהסנכרון האחרון: אז זה מהיר ולא קריטי.
    """

    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowFlags(Qt.Tool | Qt.WindowStaysOnTopHint)
        self.setModal(False)
        self.setMinimumSize(420, 360)
        self.setStyleSheet(
            "QDialog{background:#ecf0f1;}"
        )

    def showEvent(self, event):
        super().showEvent(event)
        if self.parent():
            geo = self.parent().geometry()
            x = geo.right() - self.width() - 20
            y = geo.bottom() - self.height() - 40
            self.move(QPoint(x, y))


class BigSyncDialog(_BaseSyncDialog):
    """דיאלוג מרכזי וחוסם, ל-startup אחרי 24+ שעות.

    יום שלם עבר, יש סיכוי לשינויים גדולים. המשתמש מחכה לסיום לפני שהוא
    מתחיל לעבוד — מבטיח שהנתונים שמוצגים מעודכנים.
    """

    def __init__(self, parent):
        super().__init__(parent)
        # Sprint C7.5: חייב להיות לפני שהworker מתחיל. ב-_on_ok של הבסיס
        # יש QTimer.singleShot(2000, self.accept) שמתזמן סגירה אם
        # _auto_close=True. עד C7.4 ניסינו לבטל את זה ב-_on_ok-הoverride
        # *אחרי* super(), אבל אז ה-timer כבר תוזמן ו-BigSyncDialog
        # נסגר אוטומטית כמו ה-Small. עכשיו מאפסים פה ומסירים את ה-override.
        self._auto_close = False
        self.setModal(True)
        self.setMinimumSize(520, 420)
        self.title_lbl.setText("מעדכן מסד נתונים מעדכון אחרון, נא להמתין")
