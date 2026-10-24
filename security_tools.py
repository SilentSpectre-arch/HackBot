import ipaddress
import json
import os
import shutil
import sqlite3
import subprocess
from datetime import datetime

from PySide6.QtCore import QThread, Signal, Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QListWidget, QTextEdit, QMessageBox, QGroupBox,
    QFormLayout, QComboBox
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "security_tools.db")


def db_connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    with db_connect() as con:
        con.execute("""
            CREATE TABLE IF NOT EXISTS scopes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                network TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL
            )
        """)
        con.execute("""
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                target TEXT NOT NULL,
                profile TEXT NOT NULL,
                command_json TEXT NOT NULL,
                exit_code INTEGER,
                status TEXT NOT NULL,
                stdout TEXT,
                stderr TEXT
            )
        """)


def normalize_network(value):
    try:
        return str(ipaddress.ip_network(value.strip(), strict=False))
    except ValueError:
        raise ValueError(
            "Scope باید IP یا شبکه معتبر باشد؛ مثل 192.168.1.10 یا 192.168.1.0/24."
        )


def validate_target_in_scope(target, networks):
    try:
        address = ipaddress.ip_address(target.strip())
    except ValueError:
        raise ValueError("در این نسخه هدف باید IP معتبر باشد؛ نام دامنه پشتیبانی نمی‌شود.")

    for network_text in networks:
        network = ipaddress.ip_network(network_text, strict=False)
        if address.version == network.version and address in network:
            return str(address)

    raise ValueError("هدف داخل هیچ Scope ثبت‌شده‌ای نیست؛ اجرا مسدود شد.")


class ScanWorker(QThread):
    result_ready = Signal(dict)

    def __init__(self, target, profile):
        super().__init__()
        self.target = target
        self.profile = profile

    def run(self):
        started_at = datetime.now().astimezone().isoformat(timespec="seconds")

        if self.profile != "tcp_top100":
            self.result_ready.emit({
                "started_at": started_at, "target": self.target,
                "profile": self.profile, "command": [], "exit_code": None,
                "status": "rejected", "stdout": "",
                "stderr": "پروفایل اسکن ناشناخته است."
            })
            return

        command = [
            "nmap", "-sT", "-T3", "--top-ports", "100",
            "--reason", "-oN", "-", self.target
        ]

        try:
            completed = subprocess.run(
                command, capture_output=True, text=True,
                timeout=180, check=False, shell=False
            )
            result = {
                "started_at": started_at, "target": self.target,
                "profile": self.profile, "command": command,
                "exit_code": completed.returncode,
                "status": "completed" if completed.returncode == 0 else "failed",
                "stdout": completed.stdout, "stderr": completed.stderr
            }
        except subprocess.TimeoutExpired as exc:
            result = {
                "started_at": started_at, "target": self.target,
                "profile": self.profile, "command": command,
                "exit_code": None, "status": "timeout",
                "stdout": exc.stdout or "",
                "stderr": "اسکن پس از ۱۸۰ ثانیه متوقف شد."
            }
        except Exception as exc:
            result = {
                "started_at": started_at, "target": self.target,
                "profile": self.profile, "command": command,
                "exit_code": None, "status": "error", "stdout": "",
                "stderr": f"{type(exc).__name__}: {exc}"
            }

        self.result_ready.emit(result)


class SecurityToolsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("HackBot | ابزارهای امنیتی کنترل‌شده")
        self.resize(900, 720)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.worker = None
        init_db()
        self.build_ui()
        self.refresh_scopes()
        self.refresh_history()
        self.check_nmap()

    def build_ui(self):
        root = QVBoxLayout(self)

        warning = QLabel(
            "فقط سامانه‌هایی را اضافه کن که مالک آن‌ها هستی یا مجوز روشن برای ارزیابی‌شان داری. "
            "هدف خارج از Scope ثبت‌شده اجرا نمی‌شود."
        )
        warning.setWordWrap(True)
        warning.setStyleSheet("color: #d97706; padding: 6px;")
        root.addWidget(warning)

        scope_group = QGroupBox("۱. محدوده مجاز (Scope)")
        scope_layout = QVBoxLayout(scope_group)
        add_row = QHBoxLayout()
        self.scope_input = QLineEdit()
        self.scope_input.setPlaceholderText("مثال: 192.168.1.0/24 یا 192.168.1.10")
        add_row.addWidget(self.scope_input, 1)
        add_scope_btn = QPushButton("افزودن Scope")
        add_scope_btn.clicked.connect(self.add_scope)
        add_row.addWidget(add_scope_btn)
        scope_layout.addLayout(add_row)

        self.scope_list = QListWidget()
        scope_layout.addWidget(self.scope_list)
        remove_scope_btn = QPushButton("حذف Scope انتخاب‌شده")
        remove_scope_btn.clicked.connect(self.remove_scope)
        scope_layout.addWidget(remove_scope_btn)
        root.addWidget(scope_group)

        scan_group = QGroupBox("۲. اجرای ابزار")
        scan_layout = QFormLayout(scan_group)
        self.target_input = QLineEdit()
        self.target_input.setPlaceholderText("IP هدف؛ باید داخل Scope باشد")
        scan_layout.addRow("هدف:", self.target_input)

        self.profile_combo = QComboBox()
        self.profile_combo.addItem("Nmap TCP — ۱۰۰ پورت پرتکرار (محدود)", "tcp_top100")
        scan_layout.addRow("پروفایل:", self.profile_combo)

        buttons = QHBoxLayout()
        self.run_btn = QPushButton("بررسی و اجرای اسکن")
        self.run_btn.clicked.connect(self.confirm_and_run)
        buttons.addWidget(self.run_btn)
        history_btn = QPushButton("تازه‌سازی سوابق")
        history_btn.clicked.connect(self.refresh_history)
        buttons.addWidget(history_btn)
        scan_layout.addRow(buttons)
        root.addWidget(scan_group)

        output_group = QGroupBox("۳. خروجی اجرا")
        output_layout = QVBoxLayout(output_group)
        self.output = QTextEdit()
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("خروجی Nmap اینجا نمایش داده می‌شود.")
        output_layout.addWidget(self.output)
        root.addWidget(output_group, 1)

        history_group = QGroupBox("سوابق اخیر اجرا")
        history_layout = QVBoxLayout(history_group)
        self.history = QTextEdit()
        self.history.setReadOnly(True)
        self.history.setMaximumHeight(130)
        history_layout.addWidget(self.history)
        root.addWidget(history_group)

        self.status = QLabel("آماده")
        root.addWidget(self.status)

    def check_nmap(self):
        if shutil.which("nmap") is None:
            self.status.setText("Nmap نصب نیست. در Kali با sudo apt install nmap نصبش کن.")
            self.run_btn.setEnabled(False)
        else:
            self.status.setText("Nmap پیدا شد؛ ابتدا Scope مجاز را ثبت کن.")

    def get_scopes(self):
        with db_connect() as con:
            rows = con.execute("SELECT network FROM scopes ORDER BY network").fetchall()
        return [row[0] for row in rows]

    def refresh_scopes(self):
        self.scope_list.clear()
        self.scope_list.addItems(self.get_scopes())

    def add_scope(self):
        value = self.scope_input.text().strip()
        if not value:
            return
        try:
            network = normalize_network(value)
            with db_connect() as con:
                con.execute(
                    "INSERT OR IGNORE INTO scopes(network, created_at) VALUES (?, ?)",
                    (network, datetime.now().astimezone().isoformat(timespec="seconds"))
                )
            self.scope_input.clear()
            self.refresh_scopes()
            self.status.setText(f"Scope ثبت شد: {network}")
        except Exception as exc:
            QMessageBox.warning(self, "Scope نامعتبر", str(exc))

    def remove_scope(self):
        item = self.scope_list.currentItem()
        if item is None:
            QMessageBox.information(self, "انتخاب لازم است", "ابتدا یک Scope را انتخاب کن.")
            return
        network = item.text()
        answer = QMessageBox.question(
            self, "تأیید حذف", f"Scope حذف شود؟\n{network}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        with db_connect() as con:
            con.execute("DELETE FROM scopes WHERE network = ?", (network,))
        self.refresh_scopes()
        self.status.setText(f"Scope حذف شد: {network}")

    def confirm_and_run(self):
        if self.worker is not None and self.worker.isRunning():
            QMessageBox.information(self, "در حال اجرا", "یک اسکن در حال اجراست.")
            return
        if shutil.which("nmap") is None:
            QMessageBox.warning(self, "Nmap پیدا نشد", "ابتدا Nmap را نصب کن.")
            return

        try:
            target = validate_target_in_scope(self.target_input.text(), self.get_scopes())
        except ValueError as exc:
            QMessageBox.warning(self, "هدف خارج از Scope", str(exc))
            return

        profile = self.profile_combo.currentData()
        preview = f"nmap -sT -T3 --top-ports 100 --reason -oN - {target}"
        answer = QMessageBox.question(
            self, "تأیید اجرای ابزار",
            "پیش از اجرا بررسی کن:\n\n"
            f"هدف: {target}\nپروفایل: TCP، ۱۰۰ پورت پرتکرار\n\n"
            f"دستور ساخته‌شده:\n{preview}\n\n"
            "تأیید می‌کنی این اسکن مجاز اجرا شود؟",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if answer != QMessageBox.StandardButton.Yes:
            self.status.setText("اجرا توسط کاربر لغو شد.")
            return

        self.run_btn.setEnabled(False)
        self.output.setPlainText("اسکن در حال اجراست...")
        self.status.setText(f"در حال اسکن {target} ...")
        self.worker = ScanWorker(target, profile)
        self.worker.result_ready.connect(self.on_result)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_result(self, result):
        command = result.get("command", [])
        stdout = result.get("stdout") or ""
        stderr = result.get("stderr") or ""
        display = [
            f"وضعیت: {result['status']}",
            f"هدف: {result['target']}",
            f"زمان شروع: {result['started_at']}",
            f"کد خروج: {result['exit_code']}",
            f"دستور: {' '.join(command) if command else '(اجرا نشد)'}",
            "", "خروجی استاندارد:", stdout, "", "خطاها / پیام‌های ابزار:", stderr
        ]
        self.output.setPlainText("\n".join(display))

        with db_connect() as con:
            con.execute("""
                INSERT INTO runs (
                    started_at, target, profile, command_json,
                    exit_code, status, stdout, stderr
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                result["started_at"], result["target"], result["profile"],
                json.dumps(command, ensure_ascii=False), result["exit_code"],
                result["status"], stdout, stderr
            ))

        self.status.setText(f"اجرا تمام شد: {result['status']}")
        self.refresh_history()

    def on_worker_finished(self):
        self.run_btn.setEnabled(True)

    def refresh_history(self):
        with db_connect() as con:
            rows = con.execute("""
                SELECT started_at, target, profile, status, exit_code
                FROM runs ORDER BY id DESC LIMIT 20
            """).fetchall()
        if not rows:
            self.history.setPlainText("هنوز اجرایی ثبت نشده است.")
            return
        self.history.setPlainText("\n".join(
            f"{started} | هدف: {target} | پروفایل: {profile} | "
            f"وضعیت: {status} | کد خروج: {exit_code}"
            for started, target, profile, status, exit_code in rows
        ))
