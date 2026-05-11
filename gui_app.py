# -*- coding: utf-8 -*-
import sys
from qtpy.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel,
    QHBoxLayout, QTabWidget,
)
from qtpy.QtCore import Qt, QThread, Signal as pyqtSignal

from logger import logger
from tabs.report_tab import ReportGeneratorTab
from tabs.airline_report_tab import AirlineReportTab
from tabs.branch_report_tab import BranchReportTab
from tabs.inventory_tab import InventoryTab
from tabs.inventory_analysis_tab import InventoryAnalysisTab
from tabs.unidentified_products_tab import UnidentifiedProductsTab
from tabs.updates_tab import UpdatesTab
from forecast_tab import ForecastTab


class HealthCheckWorker(QThread):
    """בדיקת זמינות Priority API ברקע."""
    finished = pyqtSignal(bool, str)   # (ok, message)

    def run(self):
        try:
            import os, requests
            from pathlib import Path
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).parent / '.env')
            base = os.environ.get('PRIORITY_BASE_URL',
                                  'https://priority.newcinema.co.il/odata/Priority/tabula.ini/ncinema')
            auth = os.environ.get('PRIORITY_AUTH_HEADER', '')
            r = requests.get(base, headers={"Authorization": auth}, timeout=8)
            ok  = r.status_code < 500
            msg = f"Priority API: HTTP {r.status_code}"
            logger.info("health_check API: %s", msg)
            self.finished.emit(ok, msg)
        except Exception as e:
            logger.warning("health_check API failed: %s", e)
            self.finished.emit(False, str(e))


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._init_ui()
        self._run_health_checks()

    def _init_ui(self):
        self.setWindowTitle("מערכת דיווח חיובים ותשלומים - Priority Interface")
        self.setGeometry(100, 100, 1100, 750)
        self.setStyleSheet("""
            QMainWindow { background-color: #f5f6fa; }
            QTabWidget::pane { border: 1px solid #bdc3c7; background-color: white; }
            QTabBar::tab { background-color: #ecf0f1; padding: 10px 16px; margin: 2px;
                           font-size: 13px; min-width: 120px; }
            QTabBar::tab:selected { background-color: #3498db; color: white; }
        """)

        tabs = QTabWidget()
        tabs.addTab(ReportGeneratorTab(),       "בקשת נתונים")
        tabs.addTab(AirlineReportTab(),          "דוחות לפי לקוחות")
        tabs.addTab(BranchReportTab(),           "דוחות לפי סניף")
        tabs.addTab(InventoryTab(),              "מעקב מלאי")
        tabs.addTab(InventoryAnalysisTab(),      "תחקור התנהלות מלאי")
        tabs.addTab(UnidentifiedProductsTab(),   "זיהוי מוצרים")
        tabs.addTab(ForecastTab(),               "תחזיות")
        tabs.addTab(UpdatesTab(),                "עדכונים")

        # ── שורת סטטוס תחתית ──
        footer_bar = QWidget()
        footer_bar.setStyleSheet("background-color:#ecf0f1; border-top:1px solid #bdc3c7;")
        footer_layout = QHBoxLayout(footer_bar)
        footer_layout.setContentsMargins(8, 2, 8, 2)

        self._db_dot  = QLabel("●")
        self._api_dot = QLabel("●")
        self._db_lbl  = QLabel("DB: בדיקה…")
        self._api_lbl = QLabel("Priority API: בדיקה…")
        for w in (self._db_dot, self._api_dot):
            w.setStyleSheet("font-size:10px; color:#f39c12;")
        for w in (self._db_lbl, self._api_lbl):
            w.setStyleSheet("font-size:11px; color:#7f8c8d;")

        footer_layout.addWidget(self._db_dot)
        footer_layout.addWidget(self._db_lbl)
        footer_layout.addSpacing(16)
        footer_layout.addWidget(self._api_dot)
        footer_layout.addWidget(self._api_lbl)
        footer_layout.addStretch()
        credit = QLabel("נכתב על ידי ירון גנד עבור תמוז סחר")
        credit.setStyleSheet("font-size:11px; color:#7f8c8d;")
        footer_layout.addWidget(credit)

        central = QWidget()
        cl = QVBoxLayout()
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)
        cl.addWidget(tabs)
        cl.addWidget(footer_bar)
        central.setLayout(cl)
        self.setCentralWidget(central)

    def _run_health_checks(self):
        # bootstrap-check בלבד: וודא ש-DB נגיש ושטבלת-מפתח אחת קיימת.
        # יצירת/עדכון schema הוא תהליך נפרד דרך migrate.py — לא מתבצע כאן.
        # במקום QMessageBox חוסם, מציגים banner בשורת-הסטטוס שלא חוסם את ה-app.
        try:
            from db_config import get_conn
            with get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        SELECT 1 FROM information_schema.tables
                        WHERE table_name = 'documents' LIMIT 1
                    """)
                    if cur.fetchone() is None:
                        raise RuntimeError(
                            "טבלת documents לא קיימת. הרץ: python migrate.py"
                        )
            self._set_status(self._db_dot, self._db_lbl, True, "DB: מחובר")
            logger.info("health_check DB: OK")
        except Exception as e:
            short = str(e).strip().splitlines()[0][:120]
            self._set_status(self._db_dot, self._db_lbl, False, f"DB: {short}")
            self._db_lbl.setToolTip(
                f"שגיאה: {e}\n\nפעולות שדורשות DB יכשלו עד שהחיבור יחזור.\n"
                "אם זה לאחר התקנה ראשונה, הרץ: python migrate.py"
            )
            logger.exception("health_check DB failed")

        self._api_worker = HealthCheckWorker()
        self._api_worker.finished.connect(self._on_api_health)
        self._api_worker.start()

    def _on_api_health(self, ok, msg):
        self._set_status(self._api_dot, self._api_lbl, ok,
                         f"Priority: {'מחובר' if ok else msg[:50]}")

    @staticmethod
    def _set_status(dot: QLabel, lbl: QLabel, ok: bool, text: str):
        color = "#27ae60" if ok else "#e74c3c"
        dot.setStyleSheet(f"font-size:10px; color:{color};")
        lbl.setStyleSheet(f"font-size:11px; color:{color};")
        lbl.setText(text)

    def closeEvent(self, event):
        """המתנה ל-workers פעילים לפני יציאה.

        מוצא את כל ה-QThread-ים שנעטפו ב-instance attributes שלנו (ושל
        ה-tabs) ומחכה להם עד 5 שניות. אם לא הסתיימו — מבצע terminate() עם
        אזהרה ב-log. בלי זה, QThread פעיל נהרג באמצע ועלול להשאיר חיבור
        DB פתוח ב-pool או קובץ זמני פתוח.
        """
        workers = self._active_workers()
        if workers:
            logger.info("closeEvent: waiting for %d worker(s) to finish", len(workers))
            for w in workers:
                if not w.wait(5000):
                    logger.warning("closeEvent: worker %s did not finish in 5s, terminating",
                                   type(w).__name__)
                    w.terminate()
                    w.wait(1000)
        # סגירת ה-pool ביציאה נקייה (psycopg2 סוגר כל החיבורים שיש).
        try:
            from db_config import close_pool
            close_pool()
        except Exception:
            logger.exception("close_pool failed")
        super().closeEvent(event)

    def _active_workers(self) -> list:
        """אוסף QThread פעילים מכל הtabs ומ-self."""
        from qtpy.QtCore import QThread
        seen = []
        stack = [self]
        # אוספים מעצמנו ומכל ה-widgets-הילדים, כל QThread שיש כ-attribute
        # על אחד מהם.
        for widget in self.findChildren(QWidget) + [self]:
            for name in dir(widget):
                if name.startswith('__'):
                    continue
                try:
                    attr = getattr(widget, name, None)
                except Exception:
                    continue
                if isinstance(attr, QThread) and attr.isRunning() and attr not in seen:
                    seen.append(attr)
        return seen


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setLayoutDirection(Qt.RightToLeft)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
