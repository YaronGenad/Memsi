# -*- coding: utf-8 -*-
"""
unidentified_products_tab.py
- מייצא לקובץ CSV את המוצרים שעדיין אין להם זיהוי קטגוריה
- מאפשר לטעון CSV מעודכן עם 'דרגת מותג / גודל / חומר' ולכתוב אותם ישירות ל-DB
  (luggage_identification table) - לא יותר שכתוב של product_identification.py.
"""
import pandas as pd
from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QTextEdit, QMessageBox, QFileDialog,
)
from qtpy.QtCore import Qt

from datetime import datetime

from fetch_combined import fetch_with_cache, combine_data
import domain_repository as repo
from db_config import get_conn

from tabs._base import BaseTabWorker, format_error_for_user
from tabs._widgets import DateRangePicker


class UnidentifiedExportWorker(BaseTabWorker):
    def __init__(self, start_date, end_date):
        super().__init__()
        self.start_date = start_date
        self.end_date   = end_date

    def _do(self):
        self.emit_progress(f"מושך נתונים: {self.start_date} עד {self.end_date}…")
        documents, logfile = fetch_with_cache(
            self.start_date, self.end_date, progress=self.emit_progress)
        self.emit_progress(f"נטענו {len(documents)} מסמכים, {len(logfile)} תנועות")
        combined = combine_data(documents, logfile)
        if combined.empty:
            return None
        combined = combined[combined['סטטוס'] == 'סופית']
        unidentified = combined[combined['זיהוי מזוודה'].isna()]
        if unidentified.empty:
            return None
        unique_products = unidentified[['תיאור מוצר']].drop_duplicates().copy()
        unique_products['דרגת מותג'] = ''
        unique_products['גודל'] = ''
        unique_products['חומר'] = ''
        return unique_products


class UnidentifiedProductsTab(QWidget):
    def __init__(self):
        super().__init__()
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)

        title = QLabel("זיהוי מוצרים ללא קטגוריה")
        title.setStyleSheet("font-size: 24px; font-weight: bold; color: #2c3e50;")
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # date range
        self.date_range = DateRangePicker(title="בחירת תקופה")
        layout.addWidget(self.date_range)

        # buttons
        self.export_btn = QPushButton("ייצא מוצרים ללא זיהוי ל-CSV")
        self.export_btn.setStyleSheet("""
            QPushButton { background-color:#e74c3c; color:white; font-size:18px;
                          font-weight:bold; padding:15px; border-radius:8px; }
            QPushButton:hover { background-color:#c0392b; }
            QPushButton:disabled { background-color:#bdc3c7; }
        """)
        self.export_btn.clicked.connect(self._export_unidentified)
        layout.addWidget(self.export_btn)

        self.import_btn = QPushButton("ייבוא CSV מעודכן ועדכון מערכת")
        self.import_btn.setStyleSheet("""
            QPushButton { background-color:#27ae60; color:white; font-size:18px;
                          font-weight:bold; padding:15px; border-radius:8px; }
            QPushButton:hover { background-color:#229954; }
            QPushButton:disabled { background-color:#bdc3c7; }
        """)
        self.import_btn.clicked.connect(self._import_and_update)
        layout.addWidget(self.import_btn)

        self.export_identified_btn = QPushButton("ייצא רשימת מוצרים מזוהים")
        self.export_identified_btn.setStyleSheet("""
            QPushButton { background-color:#2980b9; color:white; font-size:18px;
                          font-weight:bold; padding:15px; border-radius:8px; }
            QPushButton:hover { background-color:#21618c; }
            QPushButton:disabled { background-color:#bdc3c7; }
        """)
        self.export_identified_btn.clicked.connect(self._export_identified)
        layout.addWidget(self.export_identified_btn)

        self.status_text = QTextEdit()
        self.status_text.setReadOnly(True)
        self.status_text.setStyleSheet("background-color:#ecf0f1; font-family:Consolas;")
        layout.addWidget(self.status_text)

        layout.addStretch()

    # --- export -------------------------------------------------
    def _export_unidentified(self):
        self.status_text.clear()
        self.export_btn.setEnabled(False)
        start_date, end_date = self.date_range.date_range()
        self._export_meta = (
            self.date_range.start.year_month(),
            self.date_range.end.year_month(),
        )

        self._export_worker = UnidentifiedExportWorker(start_date, end_date)
        self._export_worker.progress.connect(self.status_text.append)
        self._export_worker.finished.connect(self._on_export_done)
        self._export_worker.error.connect(self._on_export_error)
        self._export_worker.start()

    def _on_export_done(self, unique_products):
        self.export_btn.setEnabled(True)
        if unique_products is None or (hasattr(unique_products, 'empty') and unique_products.empty):
            self.status_text.append("\nכל המוצרים מזוהים!")
            QMessageBox.information(self, "הצלחה", "כל המוצרים מזוהים!")
            return
        from_ym, to_ym = self._export_meta
        filename = f"unidentified_products_{from_ym.replace('-','')}_{to_ym.replace('-','')}.csv"
        unique_products.to_csv(filename, index=False, encoding='utf-8-sig')
        self.status_text.append(
            f"\nיוצאו {len(unique_products)} מוצרים לקובץ {filename}"
        )
        self.status_text.append(
            "\nהוראות:\n"
            "1. פתח ב-Excel\n"
            "2. מלא: דרגת מותג / גודל / חומר\n"
            "3. שמור וייבא חזרה דרך 'ייבוא CSV מעודכן'"
        )
        QMessageBox.information(self, "הצלחה",
                                f"יוצאו {len(unique_products)} מוצרים!\n{filename}")

    def _on_export_error(self, tb):
        self.export_btn.setEnabled(True)
        self.status_text.append(f"\nשגיאה:\n{tb[:600]}")
        QMessageBox.critical(self, "שגיאה", format_error_for_user(tb))

    # --- export identified --------------------------------------
    def _export_identified(self):
        """מייצא ל-Excel את כל המוצרים שיש להם זיהוי-קטגוריה ב-DB.
        מסודר לפי קטגוריה, ואז לפי תיאור."""
        self.export_identified_btn.setEnabled(False)
        self.status_text.clear()
        try:
            with get_conn() as conn:
                df = pd.read_sql_query("""
                    SELECT category    AS "קטגוריה",
                           description AS "תיאור מוצר",
                           updated_by  AS "עודכן ע""י",
                           updated_at  AS "תאריך עדכון"
                    FROM luggage_identification
                    ORDER BY category, description
                """, conn)

            if df.empty:
                self.status_text.append("אין מוצרים מזוהים ב-DB.")
                QMessageBox.information(self, "מידע", "אין מוצרים מזוהים ב-DB.")
                return

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_name = f"identified_products_{ts}.xlsx"
            path, _ = QFileDialog.getSaveFileName(
                self, "שמירה כאקסל", default_name, "Excel (*.xlsx)"
            )
            if not path:
                return

            # תאריך-עדכון לפורמט קריא (בלי timezone במחרוזת)
            df['תאריך עדכון'] = pd.to_datetime(df['תאריך עדכון']).dt.tz_localize(None)

            with pd.ExcelWriter(path, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='מוצרים מזוהים', index=False)
                # גם summary לפי קטגוריה
                summary = (df.groupby('קטגוריה').size()
                             .reset_index(name='מספר מוצרים')
                             .sort_values('מספר מוצרים', ascending=False))
                summary.to_excel(writer, sheet_name='סיכום לפי קטגוריה', index=False)

            self.status_text.append(
                f"✓ יוצאו {len(df)} מוצרים ב-{df['קטגוריה'].nunique()} קטגוריות"
                f"\nלקובץ: {path}"
            )
            QMessageBox.information(self, "הצלחה",
                                    f"יוצאו {len(df)} מוצרים מזוהים.\n{path}")
        except Exception as e:
            import traceback
            self.status_text.append(f"\nשגיאה: {e}")
            QMessageBox.critical(self, "שגיאה", format_error_for_user(traceback.format_exc()))
        finally:
            self.export_identified_btn.setEnabled(True)

    # --- import -------------------------------------------------
    def _import_and_update(self):
        filename, _ = QFileDialog.getOpenFileName(
            self, "בחר קובץ CSV", "", "CSV Files (*.csv)"
        )
        if not filename:
            return

        self.status_text.clear()
        self.import_btn.setEnabled(False)
        try:
            df = pd.read_csv(filename, encoding='utf-8-sig')
            self.status_text.append(f"נטענו {len(df)} מוצרים מהקובץ\n")

            user = repo.get_current_user()
            updates, skipped = 0, 0
            for _, row in df.iterrows():
                brand    = str(row.get('דרגת מותג', '') or '').strip()
                size     = str(row.get('גודל', '') or '').strip()
                material = str(row.get('חומר', '') or '').strip()
                desc     = str(row.get('תיאור מוצר', '') or '').strip()
                if not desc:
                    continue
                if not (brand and size and material):
                    skipped += 1
                    continue
                category = f"{size} {brand} {material}"
                try:
                    repo.add_luggage_identification(desc, category, user=user)
                    updates += 1
                    self.status_text.append(f"  + {category}: {desc[:60]}…")
                except Exception as e:
                    self.status_text.append(f"  ✗ {desc[:60]}…  ({e})")

            self.status_text.append(
                f"\n✓ נוספו/עודכנו {updates} מוצרים  ·  דולגו {skipped} (חסרים שדות)"
            )
            QMessageBox.information(
                self, "הצלחה",
                f"עודכנו {updates} מוצרים.\nהשינויים נכנסים לתוקף מיידית - אין צורך להפעיל מחדש."
            )
        except Exception as e:
            self.status_text.append(f"\nשגיאה: {e}")
            QMessageBox.critical(self, "שגיאה", str(e))
        finally:
            self.import_btn.setEnabled(True)
