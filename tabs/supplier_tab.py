# -*- coding: utf-8 -*-
"""
tabs/supplier_tab.py — Sprint C9.

לשונית "טיפול בספקים". מכילה שתי תת-לשוניות:

  1. הזנת נתונים — טופס לתיעוד תיקון שביצע ספק חיצוני בסניף (פעולה שלא
     עברה ב-Priority). אופציית OCR לטיוטה אוטומטית מדוח-ספק ידני מצולם.
  2. הפקת דוחות — בחירת טווח חודשים, ייצוא Excel עם שתי לשוניות לכל חודש:
     "פעולות נקודה" (מ-Priority, החלק הקיים) ו"הזנה חיצונית" (החדש מטופס).
"""
from __future__ import annotations
import calendar
from datetime import date, datetime

from qtpy.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel, QLineEdit,
    QComboBox, QPushButton, QDoubleSpinBox, QDateEdit, QTableWidget,
    QTableWidgetItem, QMessageBox, QTextEdit, QTabWidget, QHeaderView,
    QFileDialog, QApplication, QDialog,
)
from qtpy.QtCore import Qt, QDate
from qtpy.QtGui import QColor

import domain_repository as repo
from fetch_combined import fetch_supplier_payments_for_month
from logger import logger

from tabs._base import BaseTabWorker, format_error_for_user
from tabs._widgets import DateRangePicker, ExcelExporter


# ════════════════════════════════════════════════════════════════
#  Sub-tab #1: הזנת נתונים
# ════════════════════════════════════════════════════════════════
class _ExternalEntryForm(QWidget):
    """Form to insert one external_repairs row + table of recent entries."""

    HISTORY_COLUMNS = [
        ('id',                   'ID'),
        ('repair_date',          'תאריך'),
        ('vendor',               'ספק'),
        ('sender_name',          'שולח'),
        ('branch_code',          'סניף'),
        ('luggage_type',         'גודל מזוודה'),
        ('part_sku',             'מק"ט'),
        ('repair_notes',         'הערות'),
        ('amount_due',           'סכום'),
        ('damage_report_number', 'מס\' דוח נזק'),
        ('created_by',           'נוצר ע"י'),
        ('created_at',           'נוצר ב'),
    ]

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self); v.setSpacing(10)

        # ── OCR toolbar ──
        ocr_group = QGroupBox("מילוי-טיוטה אוטומטי מ-OCR")
        ocr_layout = QHBoxLayout()
        info = QLabel(
            "בחר תמונה של דוח ספק ידני; השורות יחזרו לטבלת עריכה ל-תיקון "
            "וייכנסו לDB אחרי אישור."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color:#7f8c8d;")
        ocr_layout.addWidget(info, 1)
        self.ocr_file_btn = QPushButton("📁 סריקה מקובץ")
        self.ocr_file_btn.clicked.connect(self._ocr_from_file)
        ocr_layout.addWidget(self.ocr_file_btn)
        self.ocr_clip_btn = QPushButton("📋 הדבק תמונה")
        self.ocr_clip_btn.clicked.connect(self._ocr_from_clipboard)
        ocr_layout.addWidget(self.ocr_clip_btn)
        ocr_group.setLayout(ocr_layout)
        v.addWidget(ocr_group)

        # ── Form: single-row entry ──
        form_group = QGroupBox("הזנה ידנית")
        fg = QVBoxLayout()

        # Row 1: date, vendor, sender
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("תאריך:"))
        self.repair_date = QDateEdit(QDate.currentDate())
        self.repair_date.setCalendarPopup(True)
        self.repair_date.setDisplayFormat("yyyy-MM-dd")
        row1.addWidget(self.repair_date)
        row1.addWidget(QLabel("ספק (משווק):"))
        self.vendor = QComboBox(); self.vendor.setEditable(True)
        self.vendor.setMinimumWidth(160)
        row1.addWidget(self.vendor)
        row1.addWidget(QLabel("שם השולח:"))
        self.sender = QLineEdit()
        self.sender.setMinimumWidth(140)
        row1.addWidget(self.sender)
        row1.addStretch()
        fg.addLayout(row1)

        # Row 2: branch, luggage_type, sku
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("סניף:"))
        self.branch = QComboBox()
        self.branch.setMinimumWidth(220)
        row2.addWidget(self.branch)
        row2.addWidget(QLabel("גודל מזוודה:"))
        self.luggage = QComboBox(); self.luggage.setEditable(True)
        self.luggage.setMinimumWidth(180)
        row2.addWidget(self.luggage)
        row2.addWidget(QLabel('מק"ט:'))
        self.sku = QComboBox(); self.sku.setEditable(True)
        self.sku.setMinimumWidth(140)
        row2.addWidget(self.sku)
        row2.addStretch()
        fg.addLayout(row2)

        # Row 3: notes, damage report number
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("הערות לתיקון:"))
        self.notes = QLineEdit(); self.notes.setMinimumWidth(240)
        row3.addWidget(self.notes, 1)
        row3.addWidget(QLabel("מס' דוח נזק:"))
        self.damage_report = QLineEdit()
        self.damage_report.setMinimumWidth(120)
        self.damage_report.setPlaceholderText("ידני - לתחקור")
        row3.addWidget(self.damage_report)
        fg.addLayout(row3)

        # Row 4: amount + save
        row4 = QHBoxLayout()
        row4.addWidget(QLabel("סכום:"))
        self.amount = QDoubleSpinBox()
        self.amount.setMaximum(99999); self.amount.setDecimals(2)
        row4.addWidget(self.amount)
        row4.addStretch()
        self.save_btn = QPushButton("שמור")
        self.save_btn.setStyleSheet(
            "QPushButton{background:#27ae60;color:white;font-weight:bold;padding:6px 18px;}")
        self.save_btn.clicked.connect(self._save_one)
        row4.addWidget(self.save_btn)
        fg.addLayout(row4)

        form_group.setLayout(fg)
        v.addWidget(form_group)

        # ── History table ──
        hist_group = QGroupBox("30 ההזנות האחרונות")
        hg = QVBoxLayout()
        # +3 widget columns: זיהוי / חריגים / מחק
        self.table = QTableWidget(0, len(self.HISTORY_COLUMNS) + 3)
        headers = [h for _, h in self.HISTORY_COLUMNS] + ['זיהוי', 'חריגים', 'מחיקה']
        self.table.setHorizontalHeaderLabels(headers)
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        hg.addWidget(self.table)
        hist_group.setLayout(hg)
        v.addWidget(hist_group, 1)

        self._reload_options()
        self._reload_table()

    # ---- option loaders ----
    def _reload_options(self):
        # Vendors: known ones from DB + לאפשר new entry
        self.vendor.clear()
        vendors = repo.list_external_vendors()
        self.vendor.addItems(vendors)
        self.vendor.setEditText('')

        # Branches: ordered "code – name"
        self.branch.clear()
        branches = repo.list_branches()  # dict {code: name}
        for code, name in sorted(branches.items()):
            self.branch.addItem(f"{code} – {name}", code)

        # Luggage categories
        self.luggage.clear()
        self.luggage.addItems(repo.list_luggage_categories())
        self.luggage.setEditText('')

        # SKUs
        self.sku.clear()
        self.sku.addItems(repo.list_repair_part_skus())
        self.sku.setEditText('')

    def _reload_table(self):
        df = repo.list_recent_external_repairs(limit=30)
        self.table.setRowCount(len(df))
        for r, (_, row) in enumerate(df.iterrows()):
            for c, (key, _) in enumerate(self.HISTORY_COLUMNS):
                val = row[key]
                if hasattr(val, 'strftime'):
                    txt = val.strftime('%Y-%m-%d %H:%M') if hasattr(val, 'hour') \
                          else val.strftime('%Y-%m-%d')
                elif val is None or (isinstance(val, float) and val != val):
                    txt = ''
                else:
                    txt = str(val)
                self.table.setItem(r, c, QTableWidgetItem(txt))
            # כפתור "זיהוי" — מתאים דוח-נזק פנימי לתיקון-ספק הזה.
            identify_btn = QPushButton("🔎 זיהוי")
            identify_btn.setStyleSheet("color:#2980b9;")
            identify_btn.clicked.connect(
                lambda _checked, rid=int(row['id']),
                        bc=str(row['branch_code']),
                        rd=row['repair_date']: self._identify_row(rid, bc, rd))
            self.table.setCellWidget(r, len(self.HISTORY_COLUMNS), identify_btn)

            # כפתור "חריגים" — מציג מקרים בסניף שיש בהם retl_details1 כפול
            # (אותה מזוודה דווחה כמה פעמים).
            anomaly_btn = QPushButton("⚠ חריגים")
            anomaly_btn.setStyleSheet("color:#d35400;")
            anomaly_btn.clicked.connect(
                lambda _checked, bc=str(row['branch_code']),
                        rd=row['repair_date']: self._show_anomalies(bc, rd))
            self.table.setCellWidget(r, len(self.HISTORY_COLUMNS) + 1, anomaly_btn)

            del_btn = QPushButton("מחק")
            del_btn.setStyleSheet("color:#c0392b;")
            del_btn.clicked.connect(
                lambda _checked, rid=int(row['id']): self._delete_row(rid))
            self.table.setCellWidget(r, len(self.HISTORY_COLUMNS) + 2, del_btn)

    def _delete_row(self, repair_id: int):
        reply = QMessageBox.question(
            self, "אישור מחיקה",
            f"למחוק את הזנה #{repair_id}? לא ניתן לבטל.",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
        if reply != QMessageBox.Yes:
            return
        try:
            repo.delete_external_repair(repair_id)
            self._reload_table()
        except Exception as e:
            logger.exception("delete_external_repair failed")
            QMessageBox.critical(self, "שגיאה", f"{type(e).__name__}: {e}")

    def _show_anomalies(self, branch_code: str, repair_date):
        """פותח dialog שמציג DOCNOs באותו סניף ב-±חודש עם retl_details1 כפול.
        תצוגה בלבד — לא מעדכן שום-דבר."""
        dlg = _ShowAnomaliesDialog(self, branch_code, repair_date)
        dlg.exec_()

    def _identify_row(self, repair_id: int, branch_code: str, repair_date):
        """פותח dialog לבחירת תיקון פנימי. בבחירה — שומר את ה-DOCNO ל-row."""
        dlg = _PickInternalRepairDialog(self, branch_code, repair_date,
                                          current_repair_id=repair_id)
        if dlg.exec_() != QDialog.Accepted:
            return
        docno = dlg.get_selected_docno()
        if not docno:
            return
        try:
            repo.update_external_repair_damage_report(repair_id, docno)
            self._reload_table()
            QMessageBox.information(
                self, "עודכן",
                f"הזנה #{repair_id} עודכנה: דוח נזק = {docno}")
        except Exception as e:
            logger.exception("update damage_report failed")
            QMessageBox.critical(self, "שגיאה", f"{type(e).__name__}: {e}")

    # ---- save ----
    def _read_form(self) -> dict | None:
        date_qd = self.repair_date.date()
        repair_date = date(date_qd.year(), date_qd.month(), date_qd.day())
        vendor = self.vendor.currentText().strip()
        sender = self.sender.text().strip() or None
        branch_code = self.branch.currentData()
        luggage_type = self.luggage.currentText().strip() or None
        part_sku = self.sku.currentText().strip() or None
        notes = self.notes.text().strip() or None
        damage_report = self.damage_report.text().strip() or None
        amount = float(self.amount.value())

        if not vendor:
            QMessageBox.warning(self, "שגיאה", "ספק הוא שדה חובה.")
            return None
        if not branch_code:
            QMessageBox.warning(self, "שגיאה", "סניף הוא שדה חובה.")
            return None
        if amount <= 0:
            QMessageBox.warning(self, "שגיאה", "סכום חייב להיות גדול מ-0.")
            return None
        return dict(repair_date=repair_date, vendor=vendor, sender_name=sender,
                    branch_code=branch_code, luggage_type=luggage_type,
                    part_sku=part_sku, repair_notes=notes, amount_due=amount,
                    damage_report_number=damage_report)

    def _save_one(self):
        data = self._read_form()
        if not data:
            return
        try:
            new_id = repo.insert_external_repair(**data)
            self._reload_options()  # vendor combobox may have a new entry
            self._reload_table()
            self._clear_form()
            QMessageBox.information(
                self, "הצלחה",
                f"נוצרה הזנה #{new_id}: {data['vendor']} בסניף "
                f"{data['branch_code']} סכום {data['amount_due']:.2f}")
        except Exception as e:
            logger.exception("insert_external_repair failed")
            QMessageBox.critical(self, "שגיאה", f"{type(e).__name__}: {e}")

    def _clear_form(self):
        self.sender.clear()
        self.notes.clear()
        self.damage_report.clear()
        self.amount.setValue(0)

    # ---- OCR ----
    def _ocr_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "בחר תמונת דוח ספק",
            "", "תמונות (*.png *.jpg *.jpeg);;כל הקבצים (*)")
        if not path:
            return
        from tabs._supplier_ocr import read_image_file_bytes
        data, mt = read_image_file_bytes(path)
        self._run_ocr(data, mt)

    def _ocr_from_clipboard(self):
        from tabs._supplier_ocr import grab_clipboard_image_bytes
        data = grab_clipboard_image_bytes()
        if data is None:
            QMessageBox.warning(self, "אין תמונה",
                                "לא נמצאה תמונה ב-clipboard.")
            return
        self._run_ocr(data, 'image/png')

    def _run_ocr(self, image_bytes: bytes, media_type: str):
        from tabs._supplier_ocr import (
            extract_supplier_report, OcrPreviewDialog,
        )
        # Show a wait cursor while the API runs (could take ~5s).
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            drafted = extract_supplier_report(image_bytes, media_type=media_type)
        except Exception as e:
            QApplication.restoreOverrideCursor()
            logger.exception("OCR extract failed")
            QMessageBox.critical(self, "שגיאת OCR", f"{type(e).__name__}: {e}")
            return
        QApplication.restoreOverrideCursor()

        if not drafted:
            QMessageBox.information(self, "OCR",
                                     "לא זוהו שורות בתמונה. נסה תמונה אחרת.")
            return

        dlg = OcrPreviewDialog(self, drafted,
                                known_vendors=repo.list_external_vendors())
        if dlg.exec_() != QDialog.Accepted:
            return

        rows = dlg.get_rows()
        # Resolve branch_code from text (the OCR may have a branch name; we map
        # it to a code via fuzzy match against the known branches list).
        branches = repo.list_branches()
        name_to_code = {v: k for k, v in branches.items()}
        inserted, errors = 0, []
        for i, r in enumerate(rows):
            branch_raw = (r.get('branch_code') or '').strip()
            branch_code = None
            if branch_raw in branches:
                branch_code = branch_raw
            elif branch_raw in name_to_code:
                branch_code = name_to_code[branch_raw]
            else:
                # partial: scan
                for code, name in branches.items():
                    if branch_raw and branch_raw in name:
                        branch_code = code
                        break
            if not branch_code:
                errors.append(f"שורה {i+1}: סניף '{branch_raw}' לא זוהה")
                continue

            try:
                rd = r.get('repair_date')
                if isinstance(rd, str) and rd:
                    repair_date = datetime.strptime(rd, '%Y-%m-%d').date()
                else:
                    errors.append(f"שורה {i+1}: תאריך חסר/שגוי")
                    continue
                repo.insert_external_repair(
                    repair_date=repair_date,
                    vendor=r['vendor'],
                    sender_name=None,
                    branch_code=branch_code,
                    luggage_type=r.get('luggage_type'),
                    part_sku=None,
                    repair_notes=r.get('repair_notes'),
                    amount_due=float(r.get('amount_due') or 0),
                )
                inserted += 1
            except Exception as e:
                logger.exception("OCR row insert failed")
                errors.append(f"שורה {i+1}: {type(e).__name__}: {e}")

        self._reload_options()
        self._reload_table()
        msg = f"נשמרו {inserted} שורות."
        if errors:
            msg += "\n\nשגיאות:\n" + "\n".join(errors[:10])
            if len(errors) > 10:
                msg += f"\n... ועוד {len(errors)-10} שגיאות נוספות"
        QMessageBox.information(self, "OCR סיים", msg)


# ════════════════════════════════════════════════════════════════
#  Sub-tab #2: הפקת דוחות
# ════════════════════════════════════════════════════════════════
class _ReportWorker(BaseTabWorker):
    def __init__(self, year_months: list[str]):
        super().__init__()
        self.year_months = year_months

    def _do(self):
        priority_by_ym = {}
        external_df = None

        # Priority data per month (cached by C7)
        for ym in self.year_months:
            self.emit_progress(f"שולף נתוני Priority עבור {ym}...")
            try:
                priority_by_ym[ym] = fetch_supplier_payments_for_month(
                    ym, progress=self.emit_progress)
            except Exception:
                logger.exception("priority fetch failed for %s", ym)
                priority_by_ym[ym] = None  # signal failure

        # External entries: one query for the whole range
        if self.year_months:
            self.emit_progress("שולף הזנות חיצוניות...")
            external_df = repo.list_external_repairs(
                self.year_months[0], self.year_months[-1])

        return priority_by_ym, external_df


class _ExternalReportForm(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self); v.setSpacing(12)

        # Period picker
        self.range = DateRangePicker("בחירת טווח חודשים")
        v.addWidget(self.range)

        self.run_btn = QPushButton("הפקת דוח חיצוני (Excel)")
        self.run_btn.setStyleSheet(
            "QPushButton{background:#3498db;color:white;font-size:16px;"
            "font-weight:bold;padding:12px;border-radius:6px;}"
            "QPushButton:hover{background:#2980b9;}")
        self.run_btn.clicked.connect(self._generate)
        v.addWidget(self.run_btn)

        self.status = QTextEdit()
        self.status.setReadOnly(True)
        self.status.setStyleSheet(
            "background:#ecf0f1;font-family:Consolas;font-size:12px;")
        v.addWidget(self.status, 1)

    def _months_in_range(self, ym_from: str, ym_to: str) -> list[str]:
        y, m = int(ym_from[:4]), int(ym_from[5:7])
        y_end, m_end = int(ym_to[:4]), int(ym_to[5:7])
        out = []
        while (y, m) <= (y_end, m_end):
            out.append(f"{y}-{m:02d}")
            m += 1
            if m > 12:
                m = 1; y += 1
        return out

    def _generate(self):
        start_date, end_date = self.range.date_range()
        ym_from = start_date[:7]
        ym_to = end_date[:7]
        if ym_from > ym_to:
            QMessageBox.warning(self, "שגיאה", "טווח לא תקין: 'מ' אחרי 'עד'.")
            return
        months = self._months_in_range(ym_from, ym_to)
        if not months:
            QMessageBox.warning(self, "שגיאה", "טווח ריק.")
            return

        self.status.clear()
        self.status.append(f"מפיק דוח לחודשים: {', '.join(months)}\n")
        self.run_btn.setEnabled(False)

        self._worker = _ReportWorker(months)
        self._worker.progress.connect(self.status.append)
        self._worker.finished.connect(self._on_done)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_done(self, result):
        priority_by_ym, external_df = result
        try:
            sheets = {}
            total_priority_rows, total_external_rows = 0, 0
            for ym in sorted(priority_by_ym.keys()):
                p_df = priority_by_ym[ym]
                if p_df is not None and not p_df.empty:
                    sheets[f'{ym} פעולות נקודה'] = p_df
                    total_priority_rows += len(p_df)
                if external_df is not None and not external_df.empty:
                    e_sub = external_df[external_df['year_month'] == ym]
                    if not e_sub.empty:
                        sheets[f'{ym} הזנה חיצונית'] = e_sub
                        total_external_rows += len(e_sub)

            if not sheets:
                self.status.append("✗ אין נתונים להפקה.")
                QMessageBox.warning(self, "ריק",
                                     "לא נמצאו נתונים בטווח שנבחר.")
                return

            ym_from = sorted(priority_by_ym.keys())[0]
            ym_to = sorted(priority_by_ym.keys())[-1]
            fname = (f"external_repairs_{ym_from.replace('-', '')}"
                     f"_{ym_to.replace('-', '')}.xlsx")
            saved = ExcelExporter(fname).sheets(sheets).save()
            self.status.append(
                f"\n✓ הקובץ נוצר: {saved}\n"
                f"  לשוניות: {len(sheets)}\n"
                f"  שורות Priority: {total_priority_rows}\n"
                f"  שורות הזנה-חיצונית: {total_external_rows}"
            )
            QMessageBox.information(self, "הצלחה",
                                     f"הדוח נוצר: {saved}")
        except Exception as e:
            logger.exception("export failed")
            self.status.append(f"\n✗ שגיאה: {e}")
            QMessageBox.critical(self, "שגיאה", str(e))
        finally:
            self.run_btn.setEnabled(True)

    def _on_error(self, tb: str):
        self.status.append(f"\n✗ שגיאה:\n{tb[:800]}")
        QMessageBox.critical(self, "שגיאה", format_error_for_user(tb))
        self.run_btn.setEnabled(True)


# ════════════════════════════════════════════════════════════════
#  Main SupplierTab — קונטיינר
# ════════════════════════════════════════════════════════════════
class SupplierTab(QWidget):
    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        v.setContentsMargins(8, 8, 8, 8)

        title = QLabel("טיפול בספקים")
        title.setStyleSheet("font-size:22px;font-weight:bold;color:#2c3e50;")
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)

        sub = QTabWidget()
        sub.setStyleSheet(
            "QTabBar::tab{font-size:13px;padding:6px 14px;}"
            "QTabBar::tab:selected{font-weight:bold;color:#2980b9;}"
        )
        sub.addTab(_ExternalEntryForm(), "הזנת נתונים")
        sub.addTab(_ExternalReportForm(), "הפקת דוחות")
        v.addWidget(sub, 1)


# ════════════════════════════════════════════════════════════════
#  Dialog: בחירת תיקון פנימי לזיהוי דוח-נזק (Sprint C9.2/C9.3)
# ════════════════════════════════════════════════════════════════
class _PickInternalRepairDialog(QDialog):
    """מציג תיקונים פנימיים מהמטמון לסניף נתון בחלון דו-כיווני סביב תאריך-הספק.

    סניפים שונים מריצים בקופה בעיתוי שונה: חלקם לפני שליחת המזוודה
    לתיקון (DOCNO לפני תאריך-הספק), חלקם רק אחרי החזרה מהמעבדה (DOCNO
    אחרי תאריך-הספק). לכן ברירת-המחדל היא ±14 יום ויש כפתורים להרחיב
    את החיפוש לכל כיוון (מוסיפים עוד 14 יום בכל לחיצה).

    DOCNOs ששובצו כבר לתיקון-ספק אחר מוצגים באפור ולא ניתן לבחירה.
    המשתמש בוחר שורה זמינה → ה-DOCNO חוזר ל-_identify_row לעדכון.
    """

    COLUMNS = [
        ('docno',     "מס' דוח"),
        ('curdate',   'תאריך'),
        ('partname',  'מק"ט'),
        ('topartdes', 'תיאור'),
        ('tquant',    'כמות'),
        ('custname',  'לקוח'),
    ]
    REPAIR_EXPAND_STEP_DAYS = 14
    REPLACEMENT_EXPAND_STEP_DAYS = 2

    def __init__(self, parent, branch_code: str, repair_date,
                 current_repair_id: int | None = None,
                 days_back: int = 14, days_forward: int = 14):
        super().__init__(parent)
        self.setWindowTitle(f"זיהוי תיקון פנימי בסניף {branch_code}")
        self.resize(960, 580)
        self._selected_docno: str | None = None
        self._branch_code = branch_code
        self._repair_date = repair_date
        self._current_repair_id = current_repair_id

        # שני chunks של state — אחד לכל mode. כשהמשתמש עובר בין modes
        # החלון של ה-mode השני נשמר.
        self._mode = 'repairs'           # 'repairs' | 'replacements'
        self._days_back = days_back
        self._days_forward = days_forward
        self._repl_days_back = 5
        self._repl_days_forward = 5

        v = QVBoxLayout(self)

        self._header = QLabel()
        v.addWidget(self._header)

        # שורת mode-toggle
        mode_row = QHBoxLayout()
        self._toggle_btn = QPushButton()  # טקסט נקבע ב-_reload
        self._toggle_btn.setStyleSheet(
            "QPushButton{background:#9b59b6;color:white;font-weight:bold;"
            "padding:6px 14px;}"
            "QPushButton:hover{background:#8e44ad;}")
        self._toggle_btn.clicked.connect(self._toggle_mode)
        mode_row.addWidget(self._toggle_btn)
        self._mode_hint = QLabel()
        self._mode_hint.setStyleSheet("color:#7f8c8d;padding:4px 8px;")
        mode_row.addWidget(self._mode_hint, 1)
        v.addLayout(mode_row)

        # Table — נבנית פעם אחת, מתמלאת ב-_reload.
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([h for _, h in self.COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.SingleSelection)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.doubleClicked.connect(self._accept_pick)
        v.addWidget(self.table, 1)

        self._empty_label = QLabel()
        self._empty_label.setStyleSheet("color:#7f8c8d;padding:20px;")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        v.addWidget(self._empty_label)

        # Buttons row
        btns = QHBoxLayout()
        self._expand_back = QPushButton()
        self._expand_back.clicked.connect(self._do_expand_back)
        btns.addWidget(self._expand_back)
        self._expand_fwd = QPushButton()
        self._expand_fwd.clicked.connect(self._do_expand_forward)
        btns.addWidget(self._expand_fwd)
        btns.addStretch()
        cancel = QPushButton("ביטול")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self._pick_btn = QPushButton("בחר")
        self._pick_btn.setStyleSheet(
            "QPushButton{background:#3498db;color:white;font-weight:bold;padding:6px 18px;}")
        self._pick_btn.clicked.connect(self._accept_pick)
        btns.addWidget(self._pick_btn)
        v.addLayout(btns)

        self._reload()

    # ---- mode toggle ----
    def _toggle_mode(self):
        self._mode = 'replacements' if self._mode == 'repairs' else 'repairs'
        self._reload()

    # ---- window expansion (פר-mode) ----
    def _do_expand_back(self):
        step = (self.REPAIR_EXPAND_STEP_DAYS if self._mode == 'repairs'
                else self.REPLACEMENT_EXPAND_STEP_DAYS)
        if self._mode == 'repairs':
            self._days_back += step
        else:
            self._repl_days_back += step
        self._reload()

    def _do_expand_forward(self):
        step = (self.REPAIR_EXPAND_STEP_DAYS if self._mode == 'repairs'
                else self.REPLACEMENT_EXPAND_STEP_DAYS)
        if self._mode == 'repairs':
            self._days_forward += step
        else:
            self._repl_days_forward += step
        self._reload()

    # ---- (re)populate the table ----
    def _reload(self):
        if self._mode == 'repairs':
            kind_he = 'תיקונים'
            days_b, days_f = self._days_back, self._days_forward
            step = self.REPAIR_EXPAND_STEP_DAYS
            df = repo.get_internal_repairs_at_branch(
                self._branch_code, self._repair_date,
                days_back=days_b, days_forward=days_f)
            self.setWindowTitle(f"זיהוי תיקון פנימי בסניף {self._branch_code}")
            self._toggle_btn.setText("הצג החלפות במקום")
            self._mode_hint.setText(
                "אם הקלידו את הסניף שגוי בדוח הספק, ייתכן שמדובר בהחלפה.")
            empty_msg = (
                "לא נמצאו תיקונים פנימיים בטווח שנבחר.\n"
                "הרחב חיפוש (קדימה/אחורה), נסה את כפתור 'הצג החלפות',\n"
                "או רענן את הדוח הראשי אם המטמון לא כולל את התקופה.")
        else:
            kind_he = 'החלפות'
            days_b, days_f = self._repl_days_back, self._repl_days_forward
            step = self.REPLACEMENT_EXPAND_STEP_DAYS
            df = repo.get_internal_replacements_at_branch(
                self._branch_code, self._repair_date,
                days_back=days_b, days_forward=days_f)
            self.setWindowTitle(
                f"זיהוי החלפה פנימית בסניף {self._branch_code}")
            self._toggle_btn.setText("חזור לתיקונים")
            self._mode_hint.setText(
                "מציג החלפות בלבד. ייתכן שטעות בהקלדת הסניף בדוח הספק.")
            empty_msg = (
                "לא נמצאו החלפות פנימיות בטווח שנבחר.\n"
                "הרחב חיפוש בקפיצות של 2 ימים, או חזור לתיקונים.")

        self._expand_back.setText(f"⮜ הרחב {step} אחורה")
        self._expand_fwd.setText(f"הרחב {step} קדימה ⮞")
        self._empty_label.setText(empty_msg)

        self._header.setText(
            f"<b>סניף:</b> {self._branch_code} &nbsp;|&nbsp; "
            f"<b>תאריך ספק:</b> {self._repair_date.strftime('%Y-%m-%d')} &nbsp;|&nbsp; "
            f"<b>מצב:</b> {kind_he} &nbsp;|&nbsp; "
            f"<b>חלון:</b> {days_b} ימים אחורה, {days_f} ימים קדימה")

        assigned = repo.list_assigned_damage_report_numbers(
            exclude_id=self._current_repair_id)

        self.table.setRowCount(len(df))
        self.table.setUpdatesEnabled(False)
        try:
            for r, (_, row) in enumerate(df.iterrows()):
                docno = str(row['docno'])
                is_taken = docno in assigned
                for c, (key, _) in enumerate(self.COLUMNS):
                    val = row[key]
                    if hasattr(val, 'strftime'):
                        txt = val.strftime('%Y-%m-%d')
                    elif val is None or (isinstance(val, float) and val != val):
                        txt = ''
                    else:
                        txt = str(val)
                    if is_taken and c == 0:
                        txt = f"{txt}  (משובץ)"
                    item = QTableWidgetItem(txt)
                    if is_taken:
                        item.setForeground(Qt.gray)
                        item.setFlags(item.flags()
                                       & ~Qt.ItemIsSelectable
                                       & ~Qt.ItemIsEnabled)
                    self.table.setItem(r, c, item)
        finally:
            self.table.setUpdatesEnabled(True)

        n_available = sum(
            1 for r in range(self.table.rowCount())
            if self.table.item(r, 0)
            and (self.table.item(r, 0).flags() & Qt.ItemIsSelectable))
        has_rows = len(df) > 0
        self.table.setVisible(has_rows)
        self._empty_label.setVisible(not has_rows)
        self._pick_btn.setEnabled(n_available > 0)

    def _accept_pick(self):
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        if not rows:
            QMessageBox.warning(self, "בחר", "בחר שורה זמינה מהטבלה "
                                              "(שורות באפור משובצות כבר).")
            return
        # Defence: בכל זאת לבדוק שלא נבחר משובץ (Selection-flags כבר מונעות,
        # אבל בטוח להתעקש).
        item = self.table.item(rows[0], 0)
        if item is None or not (item.flags() & Qt.ItemIsSelectable):
            QMessageBox.warning(self, "משובץ", "ה-DOCNO הזה כבר שובץ "
                                                 "לתיקון אחר.")
            return
        # הסר את הסיומת "  (משובץ)" אם הוצגה (כאן לא תהיה כי השורה זמינה,
        # אבל בטוח לחתוך).
        docno = item.text().split('  ')[0].strip()
        self._selected_docno = docno
        self.accept()

    def get_selected_docno(self) -> str | None:
        return self._selected_docno


# ════════════════════════════════════════════════════════════════
#  Dialog: זיהוי חריגים — DOCNOs שחולקים retl_details1 בסניף (Sprint C9.5)
# ════════════════════════════════════════════════════════════════
class _ShowAnomaliesDialog(QDialog):
    """תצוגה בלבד: מציג DOCNOs בסניף שחולקים את אותו retl_details1
    (לרוב tag-המזוודה) ב-±חודש סביב תאריך-הספק. עוזר לאתר מקרים של
    מזוודה אחת שטופלה כמה פעמים — דיווח כפול או בעיה חוזרת.
    """

    COLUMNS = [
        ('retl_details1', "מזהה (RETL_DETAILS1)"),
        ('docno',         "מס' דוח"),
        ('curdate',       'תאריך'),
        ('custname',      'לקוח'),
        ('branchname',    'סניף'),
    ]
    EXPAND_STEP_DAYS = 14

    def __init__(self, parent, branch_code: str, repair_date,
                 days_back: int = 30, days_forward: int = 30):
        super().__init__(parent)
        self.setWindowTitle(f"זיהוי חריגים בסניף {branch_code}")
        self.resize(900, 540)
        self._branch_code = branch_code
        self._repair_date = repair_date
        self._days_back = days_back
        self._days_forward = days_forward

        v = QVBoxLayout(self)

        self._header = QLabel()
        v.addWidget(self._header)

        info = QLabel(
            "מציג DOCNOs באותו סניף שחולקים את אותו ערך RETL_DETAILS1 — "
            "מקרים שעלולים להעיד על דיווח כפול או על מזוודה שחזרה מספר "
            "פעמים. שורות עם אותו מזהה מקובצות יחד.")
        info.setStyleSheet("color:#7f8c8d;padding:4px;")
        info.setWordWrap(True)
        v.addWidget(info)

        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([h for _, h in self.COLUMNS])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        v.addWidget(self.table, 1)

        self._empty_label = QLabel(
            "לא נמצאו חריגים בטווח שנבחר.\n"
            "הרחב את החיפוש או רענן את הדוח הראשי לחודש הרלוונטי.")
        self._empty_label.setStyleSheet("color:#7f8c8d;padding:20px;")
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)
        v.addWidget(self._empty_label)

        btns = QHBoxLayout()
        self._expand_back = QPushButton(f"⮜ הרחב {self.EXPAND_STEP_DAYS} אחורה")
        self._expand_back.clicked.connect(self._do_expand_back)
        btns.addWidget(self._expand_back)
        self._expand_fwd = QPushButton(f"הרחב {self.EXPAND_STEP_DAYS} קדימה ⮞")
        self._expand_fwd.clicked.connect(self._do_expand_forward)
        btns.addWidget(self._expand_fwd)
        btns.addStretch()
        close_btn = QPushButton("סגור")
        close_btn.clicked.connect(self.accept)
        btns.addWidget(close_btn)
        v.addLayout(btns)

        self._reload()

    def _do_expand_back(self):
        self._days_back += self.EXPAND_STEP_DAYS
        self._reload()

    def _do_expand_forward(self):
        self._days_forward += self.EXPAND_STEP_DAYS
        self._reload()

    def _reload(self):
        df = repo.get_anomalous_docs_at_branch(
            self._branch_code, self._repair_date,
            days_back=self._days_back, days_forward=self._days_forward)

        n_groups = df['retl_details1'].nunique() if not df.empty else 0
        self._header.setText(
            f"<b>סניף:</b> {self._branch_code} &nbsp;|&nbsp; "
            f"<b>תאריך ספק:</b> {self._repair_date.strftime('%Y-%m-%d')} &nbsp;|&nbsp; "
            f"<b>חלון:</b> {self._days_back} אחורה, {self._days_forward} קדימה "
            f"&nbsp;|&nbsp; "
            f"<b>קבוצות חריגות:</b> {n_groups} &nbsp;|&nbsp; "
            f"<b>סך שורות:</b> {len(df)}")

        # קביעת רקע מתחלף לפי קבוצת retl_details1, כדי שהקיבוץ ברור עין.
        # ערכי-tag מתחלפים → צבעים מתחלפים בין שני גוונים בהירים.
        self.table.setRowCount(len(df))
        self.table.setUpdatesEnabled(False)
        try:
            last_tag = None
            colors = [QColor('#ffffff'), QColor('#fff7e6')]
            color_idx = 0
            for r, (_, row) in enumerate(df.iterrows()):
                tag = str(row['retl_details1'])
                if tag != last_tag:
                    color_idx = 1 - color_idx
                    last_tag = tag
                bg = colors[color_idx]
                for c, (key, _) in enumerate(self.COLUMNS):
                    val = row[key]
                    if hasattr(val, 'strftime'):
                        txt = val.strftime('%Y-%m-%d')
                    elif val is None or (isinstance(val, float) and val != val):
                        txt = ''
                    else:
                        txt = str(val)
                    item = QTableWidgetItem(txt)
                    item.setBackground(bg)
                    self.table.setItem(r, c, item)
        finally:
            self.table.setUpdatesEnabled(True)

        has_rows = len(df) > 0
        self.table.setVisible(has_rows)
        self._empty_label.setVisible(not has_rows)
