
import sys
import json
import sqlite3
import html
import threading
import time
import uuid
from datetime import datetime

import requests
import markdown

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QFont, QTextOption
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QTextBrowser,
    QLineEdit, QComboBox, QListWidget, QListWidgetItem,
    QFrame, QSplitter, QMessageBox, QProgressBar,
    QSizePolicy, QInputDialog
)

API = "http://127.0.0.1:11434"
DB_PATH = "hackbot.db"


# --------------------------------------------------
# پایگاه داده محلی
# --------------------------------------------------

class ChatDatabase:
    def __init__(self, path=DB_PATH):
        self.path = path
        self.init_db()

    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        return db

    def init_db(self):
        with self.connect() as db:
            db.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            db.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id)
                        REFERENCES conversations(id)
                        ON DELETE CASCADE
                )
            """)
            db.commit()

    def create_conversation(self, title="گفت‌وگوی جدید"):
        conversation_id = str(uuid.uuid4())
        now = datetime.now().isoformat(timespec="seconds")

        with self.connect() as db:
            db.execute(
                """INSERT INTO conversations
                   (id, title, created_at, updated_at)
                   VALUES (?, ?, ?, ?)""",
                (conversation_id, title, now, now)
            )
            db.commit()

        return conversation_id

    def list_conversations(self):
        with self.connect() as db:
            return db.execute("""
                SELECT id, title, created_at, updated_at
                FROM conversations
                ORDER BY updated_at DESC
            """).fetchall()

    def get_messages(self, conversation_id):
        with self.connect() as db:
            rows = db.execute("""
                SELECT role, content, created_at
                FROM messages
                WHERE conversation_id = ?
                ORDER BY id ASC
            """, (conversation_id,)).fetchall()

        return [
            {
                "role": row["role"],
                "content": row["content"]
            }
            for row in rows
        ]

    def add_message(self, conversation_id, role, content):
        now = datetime.now().isoformat(timespec="seconds")

        with self.connect() as db:
            db.execute("""
                INSERT INTO messages
                    (conversation_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
            """, (conversation_id, role, content, now))

            db.execute("""
                UPDATE conversations
                SET updated_at = ?
                WHERE id = ?
            """, (now, conversation_id))

            db.commit()

    def rename_conversation(self, conversation_id, title):
        now = datetime.now().isoformat(timespec="seconds")

        with self.connect() as db:
            db.execute("""
                UPDATE conversations
                SET title = ?, updated_at = ?
                WHERE id = ?
            """, (title, now, conversation_id))
            db.commit()

    def delete_conversation(self, conversation_id):
        with self.connect() as db:
            db.execute("PRAGMA foreign_keys = ON")
            db.execute(
                "DELETE FROM messages WHERE conversation_id = ?",
                (conversation_id,)
            )
            db.execute(
                "DELETE FROM conversations WHERE id = ?",
                (conversation_id,)
            )
            db.commit()


# --------------------------------------------------
# تبدیل Markdown به HTML برای نمایش متن و کد
# --------------------------------------------------

def render_markdown(text):
    safe_text = html.escape(text)

    rendered = markdown.markdown(
        safe_text,
        extensions=[
            "fenced_code",
            "tables",
            "nl2br",
            "sane_lists"
        ]
    )

    return f"""
    <html>
    <head>
    <meta charset="utf-8">
    <style>
        body {{
            background: transparent;
            color: #d9e2ec;
            font-family: Vazirmatn, Tahoma, sans-serif;
            font-size: 14px;
            line-height: 1.9;
            direction: rtl;
            text-align: right;
            overflow-wrap: anywhere;
        }}
        p {{ margin: 5px 0 10px 0; }}
        h1, h2, h3, h4 {{ color: #45e69a; }}
        ul, ol {{ padding-right: 25px; }}
        blockquote {{
            border-right: 3px solid #45e69a;
            margin-right: 4px;
            padding-right: 12px;
            color: #aebdca;
        }}
        pre {{
            background: #0a1016;
            border: 1px solid #344454;
            border-radius: 8px;
            padding: 12px;
            direction: ltr;
            text-align: left;
            white-space: pre-wrap;
            overflow-wrap: anywhere;
        }}
        code {{
            font-family: monospace;
            color: #8be9fd;
            background: #111b24;
        }}
        pre code {{
            background: transparent;
            color: #d9e2ec;
        }}
        table {{
            border-collapse: collapse;
            width: 100%;
        }}
        th, td {{
            border: 1px solid #344454;
            padding: 7px;
        }}
        th {{ background: #18212b; }}
        a {{ color: #45e69a; }}
    </style>
    </head>
    <body>{rendered}</body>
    </html>
    """


# --------------------------------------------------
# نخ جداگانه برای پاسخ جریانی Ollama
# --------------------------------------------------

class AIWorker(QThread):
    token_received = Signal(str)
    completed = Signal(str)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, model, messages):
        super().__init__()
        self.model = model
        self.messages = messages
        self.stop_event = threading.Event()
        self.response = None

    def stop(self):
        self.stop_event.set()

        # تلاش برای قطع اتصال HTTP
        response = self.response
        if response is not None:
            try:
                response.close()
            except Exception:
                pass

    def run(self):
        full_answer = ""
        response = None

        try:
            response = requests.post(
                f"{API}/api/chat",
                json={
                    "model": self.model,
                    "messages": self.messages,
                    "stream": True,
                    "options": {"temperature": 0.3}
                },
                stream=True,
                timeout=(10, 120)
            )

            self.response = response
            response.raise_for_status()

            for line in response.iter_lines(decode_unicode=True):
                if self.stop_event.is_set():
                    self.stopped.emit()
                    return

                if not line:
                    continue

                if isinstance(line, bytes):
                    line = line.decode("utf-8")

                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if "error" in data:
                    raise RuntimeError(str(data["error"]))

                token = data.get("message", {}).get("content", "")

                if token:
                    full_answer += token
                    self.token_received.emit(token)

                if data.get("done", False):
                    break

            if self.stop_event.is_set():
                self.stopped.emit()
            else:
                self.completed.emit(full_answer)

        except Exception as exc:
            if self.stop_event.is_set():
                self.stopped.emit()
            else:
                self.failed.emit(
                    f"{type(exc).__name__}: {exc}"
                )

        finally:
            self.response = None
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass


# --------------------------------------------------
# ویجت نمایش پیام
# --------------------------------------------------

class MessageBubble(QFrame):
    def __init__(self, role, content=""):
        super().__init__()

        self.role = role
        self.content = content

        self.setObjectName(
            "userBubble" if role == "user" else "assistantBubble"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(13, 11, 13, 10)
        layout.setSpacing(7)

        top = QHBoxLayout()

        name = QLabel("شما" if role == "user" else "هک‌بات")
        name.setStyleSheet(
            "color: #45e69a; font-weight: bold;"
            if role == "assistant"
            else "color: #8be9fd; font-weight: bold;"
        )
        top.addWidget(name)
        top.addStretch()

        self.copy_btn = QPushButton("کپی متن")
        self.copy_btn.setObjectName("smallButton")
        self.copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.copy_btn.clicked.connect(self.copy_content)
        top.addWidget(self.copy_btn)

        layout.addLayout(top)

        self.viewer = QTextBrowser()
        self.viewer.setOpenLinks(False)
        self.viewer.setOpenExternalLinks(False)
        self.viewer.setReadOnly(True)
        self.viewer.setFrameShape(QFrame.Shape.NoFrame)
        self.viewer.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.viewer.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        self.viewer.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Minimum
        )
        self.viewer.setStyleSheet("""
            QTextBrowser {
                background: transparent;
                border: none;
                padding: 0;
            }
        """)

        layout.addWidget(self.viewer)
        self.set_content(content)

    def set_content(self, content):
        self.content = content
        self.viewer.setHtml(render_markdown(content))

        document = self.viewer.document()
        document.setTextWidth(max(300, self.viewer.viewport().width()))
        self.viewer.setMinimumHeight(
            min(600, max(55, int(document.size().height()) + 12))
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "viewer"):
            self.viewer.document().setTextWidth(
                max(300, self.viewer.viewport().width())
            )
            self.viewer.setMinimumHeight(
                min(
                    600,
                    max(
                        55,
                        int(self.viewer.document().size().height()) + 12
                    )
                )
            )

    def copy_content(self):
        QApplication.clipboard().setText(self.content)
        self.copy_btn.setText("کپی شد")

    def set_copy_label(self, label):
        self.copy_btn.setText(label)


# --------------------------------------------------
# پنجره اصلی
# --------------------------------------------------

class Hackbot(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("هک‌بات | دستیار هوشمند امنیت سایبری")
        self.resize(1250, 820)
        self.setMinimumSize(900, 620)

        self.db = ChatDatabase()
        self.conversation_id = None
        self.history = []
        self.worker = None
        self.current_bubble = None
        self.current_answer = ""
        self.started_at = None

        self.setStyleSheet("""
            QMainWindow, QWidget {
                background: #10151b;
                color: #d9e2ec;
                font-family: Vazirmatn, Tahoma, sans-serif;
                font-size: 13px;
            }

            QFrame#sidebar {
                background: #151e27;
                border: 1px solid #293746;
                border-radius: 12px;
            }

            QFrame#header {
                background: #18212b;
                border: 1px solid #293746;
                border-radius: 10px;
            }

            QFrame#userBubble {
                background: #1b3039;
                border: 1px solid #285263;
                border-radius: 12px;
            }

            QFrame#assistantBubble {
                background: #18212b;
                border: 1px solid #293746;
                border-radius: 12px;
            }

            QLineEdit, QComboBox {
                background: #0d1218;
                color: #e2fbe8;
                border: 1px solid #344454;
                border-radius: 8px;
                padding: 10px;
            }

            QListWidget {
                background: #0d1218;
                border: 1px solid #293746;
                border-radius: 8px;
                padding: 5px;
                outline: none;
            }

            QListWidget::item {
                padding: 10px;
                border-radius: 6px;
            }

            QListWidget::item:selected {
                background: #214738;
                color: #ffffff;
            }

            QListWidget::item:hover {
                background: #1b2a35;
            }

            QPushButton {
                background: #167d55;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px 13px;
                font-weight: bold;
            }

            QPushButton:hover {
                background: #219568;
            }

            QPushButton:disabled {
                background: #39434d;
                color: #9ba8b4;
            }

            QPushButton#secondary, QPushButton#smallButton {
                background: #263442;
                color: #d9e2ec;
            }

            QPushButton#secondary:hover,
            QPushButton#smallButton:hover {
                background: #34485a;
            }

            QPushButton#smallButton {
                padding: 5px 9px;
                font-size: 11px;
            }

            QProgressBar {
                background: #0d1218;
                border: none;
                border-radius: 3px;
                max-height: 5px;
            }

            QProgressBar::chunk {
                background: #45e69a;
                border-radius: 3px;
            }
        """)

        self.build_ui()
        self.refresh_models()
        self.refresh_conversations()
        self.new_conversation()

    def build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)

        outer = QHBoxLayout(root)
        outer.setContentsMargins(12, 12, 12, 12)
        outer.setSpacing(12)

        # نوار کناری
        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(285)

        side = QVBoxLayout(sidebar)
        side.setContentsMargins(13, 17, 13, 13)
        side.setSpacing(10)

        logo = QLabel("⚡ هک‌بات")
        logo.setAlignment(Qt.AlignmentFlag.AlignRight)
        logo.setStyleSheet(
            "font-size: 26px; font-weight: bold; color: #45e69a;"
        )
        side.addWidget(logo)

        sub = QLabel("دستیار محلی امنیت سایبری")
        sub.setAlignment(Qt.AlignmentFlag.AlignRight)
        sub.setStyleSheet("color: #94a3b8;")
        side.addWidget(sub)

        self.status = QLabel("● در حال بررسی اتصال...")
        self.status.setWordWrap(True)
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight)
        side.addWidget(self.status)

        side.addWidget(QLabel("مدل هوش مصنوعی"))

        self.models = QComboBox()
        self.models.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        side.addWidget(self.models)

        self.refresh_btn = QPushButton("↻  تازه‌سازی مدل‌ها")
        self.refresh_btn.setObjectName("secondary")
        self.refresh_btn.clicked.connect(self.refresh_models)
        side.addWidget(self.refresh_btn)

        side.addSpacing(8)

        side.addWidget(QLabel("گفتگوهای ذخیره‌شده"))

        self.conversation_list = QListWidget()
        self.conversation_list.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
        )
        self.conversation_list.currentItemChanged.connect(
            self.on_conversation_selected
        )
        side.addWidget(self.conversation_list, 1)

        new_btn = QPushButton("＋  گفت‌وگوی جدید")
        new_btn.clicked.connect(self.new_conversation)
        side.addWidget(new_btn)

        actions = QHBoxLayout()

        rename_btn = QPushButton("تغییر نام")
        rename_btn.setObjectName("secondary")
        rename_btn.clicked.connect(self.rename_conversation)
        actions.addWidget(rename_btn)

        delete_btn = QPushButton("حذف")
        delete_btn.setObjectName("secondary")
        delete_btn.clicked.connect(self.delete_conversation)
        actions.addWidget(delete_btn)

        side.addLayout(actions)

        outer.addWidget(sidebar)

        # پنل چت
        panel = QWidget()
        content = QVBoxLayout(panel)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(10)

        header = QFrame()
        header.setObjectName("header")
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(16, 12, 16, 12)

        title = QLabel("گفت‌وگوی هوشمند")
        title.setAlignment(Qt.AlignmentFlag.AlignRight)
        title.setStyleSheet(
            "font-size: 21px; font-weight: bold; color: #45e69a;"
        )
        header_layout.addWidget(title)

        self.subtitle = QLabel(
            "پاسخ جریانی • ذخیره خودکار • پردازش محلی"
        )
        self.subtitle.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.subtitle.setStyleSheet("color: #94a3b8;")
        header_layout.addWidget(self.subtitle)

        content.addWidget(header)

        # ناحیه پیام‌ها
        self.chat_area = QTextBrowser()
        self.chat_area.hide()

        from PySide6.QtWidgets import QScrollArea

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll.setStyleSheet("""
            QScrollArea {
                background: #10151b;
                border: none;
            }
            QScrollArea > QWidget > QWidget {
                background: #10151b;
            }
        """)

        self.messages_widget = QWidget()
        self.messages_layout = QVBoxLayout(self.messages_widget)
        self.messages_layout.setContentsMargins(6, 6, 6, 6)
        self.messages_layout.setSpacing(12)
        self.messages_layout.addStretch()

        self.scroll.setWidget(self.messages_widget)
        content.addWidget(self.scroll, 1)

        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setRange(0, 0)
        self.progress.hide()
        content.addWidget(self.progress)

        self.status_detail = QLabel("آماده")
        self.status_detail.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status_detail.setStyleSheet("color: #94a3b8;")
        content.addWidget(self.status_detail)

        # ورودی پیام
        input_row = QHBoxLayout()
        input_row.setSpacing(8)

        self.prompt = QLineEdit()
        self.prompt.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.prompt.setPlaceholderText(
            "پیام خود را بنویسید... (Enter برای ارسال)"
        )
        self.prompt.returnPressed.connect(self.send_message)
        input_row.addWidget(self.prompt, 1)

        self.send_btn = QPushButton("ارسال  ➤")
        self.send_btn.clicked.connect(self.send_message)
        input_row.addWidget(self.send_btn)

        self.stop_btn = QPushButton("توقف ■")
        self.stop_btn.setObjectName("secondary")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self.stop_generation)
        input_row.addWidget(self.stop_btn)

        content.addLayout(input_row)

        outer.addWidget(panel, 1)

    # --------------------------------------------------
    # مدیریت گفتگوها
    # --------------------------------------------------

    def refresh_conversations(self, select_id=None):
        self.conversation_list.blockSignals(True)
        self.conversation_list.clear()

        selected_item = None

        for row in self.db.list_conversations():
            item = QListWidgetItem(row["title"])
            item.setData(Qt.ItemDataRole.UserRole, row["id"])
            item.setToolTip(row["updated_at"])

            self.conversation_list.addItem(item)

            if row["id"] == select_id:
                selected_item = item

        if selected_item:
            self.conversation_list.setCurrentItem(selected_item)

        self.conversation_list.blockSignals(False)

    def new_conversation(self):
        if self.is_generating():
            return

        self.conversation_id = self.db.create_conversation()
        self.history = []

        self.clear_messages()
        self.refresh_conversations(self.conversation_id)

        self.add_message(
            "assistant",
            "سلام! من هک‌بات هستم. سؤال امنیتی خود را مطرح کنید."
        )

        self.status_detail.setText("گفت‌وگوی جدید آماده است.")

    def on_conversation_selected(self, current, previous):
        if current is None or self.is_generating():
            return

        conversation_id = current.data(Qt.ItemDataRole.UserRole)

        if not conversation_id or conversation_id == self.conversation_id:
            return

        self.conversation_id = conversation_id
        self.history = self.db.get_messages(conversation_id)

        self.clear_messages()

        if self.history:
            for message in self.history:
                self.add_message(
                    message["role"],
                    message["content"]
                )
        else:
            self.add_message(
                "assistant",
                "این گفتگو هنوز پیامی ندارد."
            )

        self.status_detail.setText("گفتگوی ذخیره‌شده بارگذاری شد.")

    def rename_conversation(self):
        if self.is_generating() or not self.conversation_id:
            return

        current_title = ""

        for row in self.db.list_conversations():
            if row["id"] == self.conversation_id:
                current_title = row["title"]
                break

        title, ok = QInputDialog.getText(
            self,
            "تغییر نام گفتگو",
            "عنوان جدید:",
            text=current_title
        )

        if ok and title.strip():
            self.db.rename_conversation(
                self.conversation_id,
                title.strip()
            )
            self.refresh_conversations(self.conversation_id)

    def delete_conversation(self):
        if self.is_generating() or not self.conversation_id:
            return

        answer = QMessageBox.question(
            self,
            "حذف گفتگو",
            "این گفتگو و پیام‌های آن حذف شوند؟",
            QMessageBox.StandardButton.Yes
            | QMessageBox.StandardButton.No
        )

        if answer != QMessageBox.StandardButton.Yes:
            return

        deleted_id = self.conversation_id
        self.db.delete_conversation(deleted_id)

        self.conversation_id = None
        self.history = []

        self.refresh_conversations()

        if self.conversation_list.count() > 0:
            self.conversation_list.setCurrentRow(0)
        else:
            self.new_conversation()

    # --------------------------------------------------
    # پیام‌ها
    # --------------------------------------------------

    def clear_messages(self):
        while self.messages_layout.count():
            item = self.messages_layout.takeAt(0)
            widget = item.widget()

            if widget:
                widget.deleteLater()

        self.messages_layout.addStretch()
        self.current_bubble = None

    def add_message(self, role, content):
        bubble = MessageBubble(role, content)

        # پیام کاربر در سمت راست، پاسخ مدل در سمت چپ
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)

        if role == "user":
            row.addStretch(1)
            row.addWidget(bubble, 7)
        else:
            row.addWidget(bubble, 7)
            row.addStretch(1)

        container = QWidget()
        container.setLayout(row)

        self.messages_layout.insertWidget(
            self.messages_layout.count() - 1,
            container
        )

        self.scroll_to_bottom()
        return bubble

    def scroll_to_bottom(self):
        bar = self.scroll.verticalScrollBar()
        bar.setValue(bar.maximum())

    def is_generating(self):
        return self.worker is not None and self.worker.isRunning()

    # --------------------------------------------------
    # اتصال به Ollama
    # --------------------------------------------------

    def refresh_models(self):
        self.refresh_btn.setEnabled(False)
        self.status.setText("● در حال دریافت فهرست مدل‌ها...")
        self.status.setStyleSheet("color: #f6c85f;")

        try:
            response = requests.get(
                f"{API}/api/tags",
                timeout=5
            )
            response.raise_for_status()

            models = [
                model["name"]
                for model in response.json().get("models", [])
            ]

            previous = self.models.currentText()

            self.models.clear()
            self.models.addItems(models)

            if previous:
                index = self.models.findText(previous)
                if index >= 0:
                    self.models.setCurrentIndex(index)
            elif models:
                index = self.models.findText("llama3.2:latest")
                self.models.setCurrentIndex(
                    index if index >= 0 else 0
                )

            if models:
                self.status.setText("● Ollama متصل است")
                self.status.setStyleSheet("color: #45e69a;")
            else:
                self.status.setText("● هیچ مدلی نصب نشده است")
                self.status.setStyleSheet("color: #f6c85f;")

        except Exception as exc:
            self.status.setText("● خطای اتصال به Ollama")
            self.status.setStyleSheet("color: #ff7272;")
            self.status_detail.setText(str(exc))

        finally:
            self.refresh_btn.setEnabled(True)

    # --------------------------------------------------
    # ارسال، دریافت و توقف
    # --------------------------------------------------

    def send_message(self):
        if self.is_generating():
            return

        prompt = self.prompt.text().strip()

        if not prompt:
            return

        model = self.models.currentText()

        if not model:
            QMessageBox.warning(
                self,
                "مدل انتخاب نشده",
                "ابتدا یک مدل نصب‌شده در Ollama انتخاب کنید."
            )
            return

        if not self.conversation_id:
            self.conversation_id = self.db.create_conversation()

        self.history.append({
            "role": "user",
            "content": prompt
        })

        self.db.add_message(
            self.conversation_id,
            "user",
            prompt
        )

        # عنوان گفتگو از اولین پیام گرفته می‌شود
        messages_in_db = self.db.get_messages(self.conversation_id)

        if len(messages_in_db) == 1:
            title = prompt.replace("\n", " ").strip()[:45]
            if len(prompt) > 45:
                title += "…"

            self.db.rename_conversation(
                self.conversation_id,
                title or "گفت‌وگوی جدید"
            )

        self.add_message("user", prompt)
        self.prompt.clear()

        self.current_answer = ""
        self.current_bubble = self.add_message("assistant", "")

        self.send_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.refresh_btn.setEnabled(False)
        self.models.setEnabled(False)
        self.progress.show()

        self.started_at = time.monotonic()
        self.status_detail.setText("در حال دریافت پاسخ از Ollama...")

        self.refresh_conversations(self.conversation_id)

        system_message = {
    "role": "system",
    "content": (
        "You are HackBot, a cybersecurity assistant. "
        "Always answer in Persian unless requested otherwise. "
        "Help with authorized security testing, defensive analysis, "
        "lab exercises, and security report writing. "
        "Explain technical concepts clearly and recommend safe "
        "validation and remediation steps."
    )
}   
        self.worker = AIWorker(
    model=model,
    messages=[system_message] + self.history.copy()
)

        self.worker.token_received.connect(self.on_token)
        self.worker.completed.connect(self.on_completed)
        self.worker.failed.connect(self.on_failed)
        self.worker.stopped.connect(self.on_stopped)
        self.worker.finished.connect(self.on_worker_finished)

        self.worker.start()

    def on_token(self, token):
        self.current_answer += token

        if self.current_bubble:
            self.current_bubble.set_content(self.current_answer)

        self.scroll_to_bottom()

        elapsed = time.monotonic() - self.started_at
        self.status_detail.setText(
            f"در حال تولید پاسخ... {elapsed:.1f} ثانیه"
        )

    def on_completed(self, answer):
        self.current_answer = answer

        if self.current_bubble:
            self.current_bubble.set_content(answer)

        if answer.strip():
            self.history.append({
                "role": "assistant",
                "content": answer
            })

            self.db.add_message(
                self.conversation_id,
                "assistant",
                answer
            )

        elapsed = time.monotonic() - self.started_at
        self.status_detail.setText(
            f"پاسخ کامل شد • زمان: {elapsed:.1f} ثانیه"
        )

        self.refresh_conversations(self.conversation_id)
        self.scroll_to_bottom()

    def on_failed(self, error):
        message = f"خطا در دریافت پاسخ:\n{error}"

        if self.current_bubble:
            self.current_bubble.set_content(message)
        else:
            self.add_message("assistant", message)

        self.status_detail.setText("درخواست با خطا مواجه شد.")
        self.status.setText("● خطا در درخواست")
        self.status.setStyleSheet("color: #ff7272;")

    def on_stopped(self):
        if self.current_answer.strip():
            self.history.append({
                "role": "assistant",
                "content": self.current_answer
            })

            self.db.add_message(
                self.conversation_id,
                "assistant",
                self.current_answer + "\n\n[تولید پاسخ متوقف شد]"
            )

            if self.current_bubble:
                self.current_bubble.set_content(
                    self.current_answer
                    + "\n\n_تولید پاسخ متوقف شد._"
                )
        elif self.current_bubble:
            self.current_bubble.set_content(
                "تولید پاسخ توسط کاربر متوقف شد."
            )

        self.status_detail.setText("تولید پاسخ متوقف شد.")

    def stop_generation(self):
        if self.worker and self.worker.isRunning():
            self.status_detail.setText(
                "در حال تلاش برای توقف پاسخ..."
            )
            self.stop_btn.setEnabled(False)
            self.worker.stop()

    def on_worker_finished(self):
        self.send_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.refresh_btn.setEnabled(True)
        self.models.setEnabled(True)
        self.progress.hide()

        if self.status.text() != "● خطا در درخواست":
            self.status.setText("● آماده")
            self.status.setStyleSheet("color: #45e69a;")

        self.worker = None

    def closeEvent(self, event):
        if self.is_generating():
            answer = QMessageBox.question(
                self,
                "درخواست در حال اجرا",
                "پاسخ هنوز در حال تولید است. برنامه بسته شود؟",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
            )

            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return

            self.worker.stop()
            self.worker.wait(3000)

            if self.worker.isRunning():
                QMessageBox.warning(
                    self,
                    "درخواست فعال",
                    "اتصال هنوز در حال بسته شدن است. "
                    "لطفاً کمی بعد دوباره تلاش کنید."
                )
                event.ignore()
                return

        event.accept()


# --------------------------------------------------
# اجرای برنامه
# --------------------------------------------------

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("هک‌بات")
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)

    window = Hackbot()
    window.show()

    sys.exit(app.exec())
