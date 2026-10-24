
import os
import json
import requests
import xml.etree.ElementTree as ET

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTextEdit, QFileDialog, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QMessageBox, QSplitter,
    QGroupBox
)

API = "http://127.0.0.1:11434"


def parse_nmap_xml(xml_text):
    """استخراج میزبان‌ها و پورت‌ها از خروجی XML ابزار Nmap."""
    root = ET.fromstring(xml_text)
    findings = []

    for host in root.findall("host"):
        address = "نامشخص"

        for addr in host.findall("address"):
            if addr.get("addrtype") in ("ipv4", "ipv6"):
                address = addr.get("addr")
                break

        status_element = host.find("status")
        host_status = (
            status_element.get("state", "unknown")
            if status_element is not None else "unknown"
        )

        for port in host.findall(".//port"):
            state_element = port.find("state")
            service_element = port.find("service")

            state = (
                state_element.get("state", "unknown")
                if state_element is not None else "unknown"
            )

            service_name = (
                service_element.get("name", "unknown")
                if service_element is not None else "unknown"
            )

            product = (
                service_element.get("product", "")
                if service_element is not None else ""
            )

            version = (
                service_element.get("version", "")
                if service_element is not None else ""
            )

            findings.append({
                "host": address,
                "host_status": host_status,
                "protocol": port.get("protocol", "unknown"),
                "port": port.get("portid", "?"),
                "state": state,
                "service": service_name,
                "product": product,
                "version": version,
            })

    return findings


class AnalysisWorker(QThread):
    completed = Signal(str)
    failed = Signal(str)

    def __init__(self, model, prompt):
        super().__init__()
        self.model = model
        self.prompt = prompt

    def run(self):
        try:
            response = requests.post(
                f"{API}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "تو دستیار تحلیل امنیت دفاعی هستی. "
                                "گزارش‌ها را به فارسی تحلیل کن. "
                                "صرف باز بودن یک پورت را آسیب‌پذیری قطعی "
                                "اعلام نکن. بین شواهد، احتمال و واقعیت "
                                "تأییدشده تفاوت بگذار. "
                                "برای ریسک، دلیل و میزان اطمینان را ذکر کن. "
                                "راهکارهای اصلاحی و اعتبارسنجی مجاز پیشنهاد بده."
                            )
                        },
                        {"role": "user", "content": self.prompt}
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 2048
                    }
                },
                timeout=(10, 300)
            )

            response.raise_for_status()
            data = response.json()
            answer = data.get("message", {}).get("content", "")
            self.completed.emit(answer or "مدل پاسخی برنگرداند.")

        except Exception as exc:
            self.failed.emit(f"{type(exc).__name__}: {exc}")


class SecurityLabDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)

        self.setWindowTitle("HackBot | آزمایشگاه تحلیل امنیتی")
        self.resize(1050, 760)
        self.setLayoutDirection(Qt.RightToLeft)

        self.scan1_text = ""
        self.scan2_text = ""
        self.scan1_findings = []
        self.scan2_findings = []
        self.worker = None

        self.build_ui()
        self.load_models()

    def build_ui(self):
        root_layout = QVBoxLayout(self)

        intro = QLabel(
            "گزارش‌های اسکن را وارد کن، یافته‌ها را بررسی کن "
            "و با مدل محلی Ollama تحلیل دفاعی بگیر."
        )
        intro.setWordWrap(True)
        root_layout.addWidget(intro)

        model_row = QHBoxLayout()
        model_row.addWidget(QLabel("مدل محلی:"))

        self.model_combo = QComboBox()
        model_row.addWidget(self.model_combo, 1)

        refresh_button = QPushButton("بارگذاری مدل‌ها")
        refresh_button.clicked.connect(self.load_models)
        model_row.addWidget(refresh_button)

        root_layout.addLayout(model_row)

        files_row = QHBoxLayout()

        self.file1_button = QPushButton("بارگذاری اسکن اول")
        self.file1_button.clicked.connect(lambda: self.load_scan(1))
        files_row.addWidget(self.file1_button)

        self.file2_button = QPushButton("بارگذاری اسکن دوم")
        self.file2_button.clicked.connect(lambda: self.load_scan(2))
        files_row.addWidget(self.file2_button)

        root_layout.addLayout(files_row)

        splitter = QSplitter(Qt.Vertical)

        findings_group = QGroupBox("یافته‌های اسکن اول")
        findings_layout = QVBoxLayout(findings_group)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([
            "میزبان", "پورت", "پروتکل",
            "وضعیت", "سرویس", "نسخه"
        ])
        self.table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)

        findings_layout.addWidget(self.table)
        splitter.addWidget(findings_group)

        result_group = QGroupBox("تحلیل و مقایسه")
        result_layout = QVBoxLayout(result_group)

        action_row = QHBoxLayout()

        self.analyze_button = QPushButton("تحلیل اسکن اول با هوش مصنوعی")
        self.analyze_button.clicked.connect(self.analyze_scan)
        action_row.addWidget(self.analyze_button)

        self.compare_button = QPushButton("مقایسه دو اسکن")
        self.compare_button.clicked.connect(self.compare_scans)
        action_row.addWidget(self.compare_button)

        result_layout.addLayout(action_row)

        self.result = QTextEdit()
        self.result.setReadOnly(True)
        self.result.setPlaceholderText("نتیجه تحلیل اینجا نمایش داده می‌شود...")
        result_layout.addWidget(self.result)

        splitter.addWidget(result_group)
        splitter.setSizes([300, 400])

        root_layout.addWidget(splitter)

        self.status_label = QLabel("آماده")
        root_layout.addWidget(self.status_label)

    def load_models(self):
        try:
            response = requests.get(f"{API}/api/tags", timeout=5)
            response.raise_for_status()
            models = response.json().get("models", [])

            self.model_combo.clear()

            for model in models:
                name = model.get("name")
                if name:
                    self.model_combo.addItem(name)

            if not models:
                self.status_label.setText(
                    "هیچ مدلی پیدا نشد؛ ابتدا یک مدل در Ollama نصب کن."
                )
            else:
                self.status_label.setText(
                    f"{len(models)} مدل محلی پیدا شد."
                )

        except Exception as exc:
            self.status_label.setText(
                f"اتصال به Ollama برقرار نشد: {exc}"
            )

    def load_scan(self, number):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "انتخاب گزارش اسکن",
            "",
            "گزارش‌ها (*.xml *.txt *.nmap *.log);;همه فایل‌ها (*)"
        )

        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8-sig") as file:
                content = file.read()

            findings = []

            if path.lower().endswith(".xml"):
                findings = parse_nmap_xml(content)

            if number == 1:
                self.scan1_text = content
                self.scan1_findings = findings
                self.file1_button.setText(
                    f"اسکن اول: {os.path.basename(path)}"
                )

                self.table.setRowCount(0)

                for item in findings:
                    row = self.table.rowCount()
                    self.table.insertRow(row)

                    values = [
                        item["host"],
                        item["port"],
                        item["protocol"],
                        item["state"],
                        item["service"],
                        " ".join(
                            x for x in [
                                item["product"], item["version"]
                            ] if x
                        ) or "-"
                    ]

                    for column, value in enumerate(values):
                        self.table.setItem(
                            row, column,
                            QTableWidgetItem(str(value))
                        )

            else:
                self.scan2_text = content
                self.scan2_findings = findings
                self.file2_button.setText(
                    f"اسکن دوم: {os.path.basename(path)}"
                )

            self.status_label.setText(
                f"فایل اسکن {number} بارگذاری شد."
            )

        except Exception as exc:
            QMessageBox.critical(
                self, "خطا در خواندن فایل", str(exc)
            )

    def analyze_scan(self):
        if not self.scan1_text.strip():
            QMessageBox.warning(
                self, "گزارش موجود نیست",
                "ابتدا گزارش اسکن اول را بارگذاری کن."
            )
            return

        model = self.model_combo.currentText()

        if not model:
            QMessageBox.warning(
                self, "مدل موجود نیست",
                "ابتدا Ollama را اجرا و یک مدل نصب کن."
            )
            return

        prompt = f"""
گزارش اسکن زیر را برای ارزیابی دفاعی تحلیل کن.

خروجی را به فارسی و با این بخش‌ها بنویس:
1. خلاصه مدیریتی
2. میزبان‌ها، پورت‌ها و سرویس‌های مشاهده‌شده
3. یافته‌های مهم و درجه ریسک اولیه: بحرانی، بالا، متوسط، پایین یا نامشخص
4. شواهد و دلیل هر درجه‌بندی
5. محدودیت‌های گزارش و مواردی که هنوز تأیید نشده‌اند
6. راهکارهای اصلاحی
7. روش اعتبارسنجی مجدد در محیط مجاز

قواعد:
- پورت باز به‌تنهایی اثبات آسیب‌پذیری نیست.
- بدون شواهد کافی، نسخه نرم‌افزار را آسیب‌پذیر قطعی اعلام نکن.
- در صورت نبود اطلاعات لازم، آن را صریحاً بیان کن.
- از پیشنهاد بهره‌برداری مخرب خودداری کن.

گزارش اسکن:
{self.scan1_text[:50000]}
"""

        self.run_analysis(model, prompt)

    def compare_scans(self):
        if not self.scan1_text.strip() or not self.scan2_text.strip():
            QMessageBox.warning(
                self, "دو گزارش لازم است",
                "برای مقایسه، هر دو اسکن را بارگذاری کن."
            )
            return

        if self.scan1_findings and self.scan2_findings:
            def key(item):
                return (
                    item["host"], item["protocol"],
                    item["port"], item["service"]
                )

            first = {key(x): x for x in self.scan1_findings}
            second = {key(x): x for x in self.scan2_findings}

            added = sorted(set(second) - set(first))
            removed = sorted(set(first) - set(second))

            diff = (
                "موارد موجود در اسکن دوم و غایب از اسکن اول:\n"
                + "\n".join(map(str, added))
                + "\n\nموارد موجود در اسکن اول و غایب از اسکن دوم:\n"
                + "\n".join(map(str, removed))
            )

        else:
            diff = (
                "مقایسه ساختاری خودکار در دسترس نیست؛ "
                "حداقل یکی از گزارش‌ها XML معتبر Nmap نیست."
            )

        prompt = f"""
دو گزارش اسکن را برای مقایسه دفاعی بررسی کن.

تفاوت‌های گزارش‌شده توسط برنامه:
{diff}

اسکن اول:
{self.scan1_text[:20000]}

اسکن دوم:
{self.scan2_text[:20000]}

به فارسی توضیح بده:
- چه تغییراتی دیده می‌شود؟
- کدام پورت‌ها یا سرویس‌ها اضافه یا حذف شده‌اند؟
- آیا شواهدی از بهبود وضعیت وجود دارد؟
- چه مواردی نیاز به بررسی بیشتر دارند؟

توجه: حذف یک پورت از گزارش لزوماً اثبات رفع آسیب‌پذیری نیست.
تفاوت پارامترهای اسکن نیز می‌تواند روی نتیجه اثر بگذارد.
"""

        model = self.model_combo.currentText()

        if not model:
            QMessageBox.warning(
                self, "مدل موجود نیست",
                "ابتدا یک مدل Ollama انتخاب کن."
            )
            return

        self.run_analysis(model, prompt)

    def run_analysis(self, model, prompt):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(
                self, "تحلیل در حال اجراست",
                "صبر کن تحلیل فعلی تمام شود."
            )
            return

        self.analyze_button.setEnabled(False)
        self.compare_button.setEnabled(False)
        self.status_label.setText("در حال تحلیل با Ollama...")
        self.result.setPlainText("در حال دریافت پاسخ مدل محلی...")

        self.worker = AnalysisWorker(model, prompt)
        self.worker.completed.connect(self.on_analysis_completed)
        self.worker.failed.connect(self.on_analysis_failed)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_analysis_completed(self, answer):
        self.result.setPlainText(answer)
        self.status_label.setText("تحلیل تکمیل شد.")

    def on_analysis_failed(self, error):
        self.result.setPlainText(f"تحلیل ناموفق بود:\n{error}")
        self.status_label.setText("خطا در تحلیل.")

    def on_worker_finished(self):
        self.analyze_button.setEnabled(True)
        self.compare_button.setEnabled(True)

