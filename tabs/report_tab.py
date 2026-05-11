# -*- coding: utf-8 -*-
import pandas as pd
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QTextEdit, QMessageBox,
)
from qtpy.QtCore import Qt

from fetch_combined import fetch_with_cache, combine_data, get_target_customers
from domain_repository import get_supplier_payment

from tabs._base import BaseTabWorker, format_error_for_user
from tabs._widgets import MonthYearPicker, ExcelExporter, slice_by_column


class ReportWorker(BaseTabWorker):
    def __init__(self, start_date, end_date, force_refresh=False, year_month=None):
        super().__init__()
        self.start_date    = start_date
        self.end_date      = end_date
        self.force_refresh = force_refresh
        self.year_month    = year_month

    def _do(self):
        if self.force_refresh and self.year_month:
            from cache_manager import CacheManager
            self.emit_progress(f"מוחק נתוני {self.year_month} מהמטמון…")
            cm = CacheManager(); cm.clear_month_data(self.year_month); cm.close()
        self.emit_progress("מושך נתונים מ-Priority…")
        documents, logfile = fetch_with_cache(
            self.start_date, self.end_date,
            progress=self.emit_progress,
        )
        self.emit_progress(f"עיבוד {len(documents)} מסמכים…")
        return combine_data(documents, logfile)


class ReportGeneratorTab(QWidget):
    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)

        title = QLabel("יצירת דוח חיובים ותשלומים")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        date_group = QGroupBox("בחירת תקופה")
        date_group.setStyleSheet("QGroupBox { font-size: 16px; font-weight: bold; }")
        date_layout = QHBoxLayout()
        self.date_picker = MonthYearPicker()
        date_layout.addWidget(self.date_picker)
        date_layout.addStretch()
        date_group.setLayout(date_layout)
        layout.addWidget(date_group)

        buttons_layout = QHBoxLayout()

        self.run_btn = QPushButton("בצע יצירת דוח")
        self.run_btn.setStyleSheet("""
            QPushButton { background-color:#3498db; color:white; font-size:18px;
                          font-weight:bold; padding:15px; border-radius:8px; }
            QPushButton:hover { background-color:#2980b9; }
        """)
        self.run_btn.clicked.connect(self.generate_report)
        buttons_layout.addWidget(self.run_btn)

        self.refresh_btn = QPushButton("בצע יצירת דוח עם ריענון")
        self.refresh_btn.setStyleSheet("""
            QPushButton { background-color:#e67e22; color:white; font-size:18px;
                          font-weight:bold; padding:15px; border-radius:8px; }
            QPushButton:hover { background-color:#d35400; }
        """)
        self.refresh_btn.clicked.connect(self.generate_report_with_refresh)
        buttons_layout.addWidget(self.refresh_btn)

        layout.addLayout(buttons_layout)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet("background-color:#ecf0f1; font-family:Consolas;")
        layout.addWidget(self.status_text)

        layout.addStretch()
        self.setLayout(layout)

    def _start_worker(self, force_refresh=False):
        start_date, end_date = self.date_picker.date_range()
        year_month = self.date_picker.year_month()

        self.status_text.clear()
        self.run_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.status_text.append(f"טוען נתונים עבור {year_month}…\n")

        self._worker = ReportWorker(start_date, end_date,
                                    force_refresh=force_refresh,
                                    year_month=year_month if force_refresh else None)
        self._worker.progress.connect(self.status_text.append)
        self._worker.finished.connect(self._on_report_ready)
        self._worker.error.connect(self._on_report_error)
        self._worker.start()

    def generate_report(self):
        self._start_worker(force_refresh=False)

    def generate_report_with_refresh(self):
        year_month = self.date_picker.year_month()
        reply = QMessageBox.question(
            self, "אישור ריענון",
            f"פעולה זו תמחק את נתוני {year_month} מהמטמון ותמשוך נתונים חדשים מ-Priority.\nהאם להמשיך?",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._start_worker(force_refresh=True)

    def _on_report_ready(self, combined):
        try:
            sheets = slice_by_column(combined, 'מספר לקוח', values=get_target_customers())

            suppliers_data = combined[
                combined['פרטים'].notna() & (combined['פרטים'] != '')
            ].copy()
            if not suppliers_data.empty:
                suppliers_data['תשלום לספק'] = suppliers_data.apply(
                    lambda row: get_supplier_payment(
                        row['מקט'], row['זיהוי מזוודה'], row['כמות']),
                    axis=1
                )
                sheets['תשלום לספקים'] = suppliers_data

            sheets['סיכום חודשי'] = combined

            filename = ExcelExporter('combined_output.xlsx').sheets(sheets).save()
            self.status_text.append(f"\n✓ הקובץ נוצר בהצלחה: {filename}")
            self.status_text.append(f"✓ סך הכל {len(combined)} שורות")
            QMessageBox.information(self, "הצלחה", "הדוח נוצר בהצלחה!")
        except Exception as e:
            self.status_text.append(f"\n✗ שגיאה בשמירה: {e}")
            QMessageBox.critical(self, "שגיאה", str(e))
        finally:
            self.run_btn.setEnabled(True)
            self.refresh_btn.setEnabled(True)

    def _on_report_error(self, tb):
        self.status_text.append(f"\n✗ שגיאה:\n{tb[:800]}")
        QMessageBox.critical(self, "שגיאה", format_error_for_user(tb))
        self.run_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
