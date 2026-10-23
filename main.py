import sys
import requests
import html
from PySide6.QtCore import QThread, Signal,Qt
from PySide6.QtWidgets import (
    QApplication, QMainWindow,QWidget,QVBoxLayout,
    QHBoxLayout, QLabel, QPushButton, QTextEdit,
    QLineEdit,QComboBox,QFrame,QMessageBox
)

API = 'http://127.0.0.1:11434'

class AIWorker(QThread):
    finished_text = Signal(str)
    failed = Signal(str)

    def __init__(self, model, messages):
        super().__init__()
        self.model = model
        self.messages = messages

    def run(self):
        try:
            response = requests.post(
                f"{API}/api/chat",
                json={
                    "model": self.model,
                    "messages": self.messages,
                    "stream": False,
                    "options": {"temperature": 0.3}
                },
                timeout=300)

            response.raise_for_status()
            answer = response.json()['message']['content']
            self.finished_text.emit(answer)

        # except Exception as exc:
        #     self.failed.emit(str(exc))

        except requests.exceptions.Timeout:
            self.failed.emit("زمان انتظار برای پاسخ به پایان رسید.")
        except Exception as exc:
            self.failed.emit(f"خطا در دریافت پاسخ:\n{exc}")


class Hackbot(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("هک‌بات | دستیار هوش مصنوعی امنیت سایبری")

        self.resize(1150, 750)
        self.setMinimumSize(850,600)
        self.history = [{
            "role": "system",
            "content": (
                "You are HackBot, a cybersecurity assistant. "
                "Always respond in Persian unless requested otherwise. "
                "Help with authorized security assessments, defensive "
                "analysis, lab exercises, and interpreting tool output. "
                "Ask for scope when necessary. Do not assume a target "
                "is authorized. Explain risks and recommend safe "
                "validation steps. Format code clearly."
            )
        }]
        self.worker = None
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #10151b;
                color: #d9e2ec;
                font-size: 14px;
                font-family: "Vazirmatn", "Tahoma", sans-serif;
            }

            QFrame#sidebar {
                background-color: #151e27;
                border: 1px solid #293746;
                border-radius: 12px;
            }

            QFrame#header {
                background-color: #18212b;
                border: 1px solid #293746;
                border-radius: 10px;
            }

            QLabel {
                background: transparent;
                border: none;
            }

            QTextEdit, QLineEdit, QComboBox {
                background-color: #0d1218;
                color: #e2fbe8;
                border: 1px solid #344454;
                border-radius: 8px;
                padding: 10px;
                selection-background-color: #167d55;
            }

            QTextEdit {
                font-size: 14px;
            }

            QComboBox QAbstractItemView {
                background-color: #18212b;
                color: #e2fbe8;
                selection-background-color: #167d55;
            }

            QPushButton {
                background-color: #167d55;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 11px 14px;
                font-weight: bold;
            }

            QPushButton:hover {
                background-color: #219568;
            }

            QPushButton:disabled {
                background-color: #39434d;
                color: #a0aab4;
            }

            QPushButton#secondary {
                background-color: #263442;
                color: #d9e2ec;
            }

            QPushButton#secondary:hover {
                background-color: #34485a;
            }
        """)
        root = QWidget()
        self.setCentralWidget(root)

        layout = QHBoxLayout(root)
        layout.setContentsMargins(14,14,14,14)
        layout.setSpacing(14)

        #Side-bar
        sidebar = QFrame()
        sidebar.setObjectName('sidebar')
        sidebar.setFixedWidth(255)

        side = QVBoxLayout(sidebar)
        side.setContentsMargins(16,20,16,16)
        side.setSpacing(12)

        logo = QLabel("⚡ هک‌بات")
        logo.setAlignment(Qt.AlignmentFlag.AlignRight)
        logo.setStyleSheet("""
            font-size: 27px;
            font-weight: bold;
            color: #45e69a;
        """)
        side.addWidget(logo)

        subtitle = QLabel("دستیار هوشمند امنیت سایبری")
        subtitle.setWordWrap(True)
        subtitle.setAlignment(Qt.AlignmentFlag.AlignRight)
        subtitle.setStyleSheet("color: #94a3b8;")
        side.addWidget(subtitle)

        side.addSpacing(8)

        self.status = QLabel("● در حال بررسی اتصال...")
        self.status.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.status.setWordWrap(True)
        side.addWidget(self.status)
        side.addSpacing(8)

        model_label = QLabel("مدل هوش مصنوعی")
        model_label.setAlignment(Qt.AlignmentFlag.AlignRight)
        side.addWidget(model_label)

        self.models = QComboBox()
        self.models.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
        )
        self.models.setEditable(False)
        self.models.addItem("در حال دریافت مدل‌ها...")
        side.addWidget(self.models)

        self.check_btn = QPushButton("↻  به‌روزرسانی مدل‌ها")
        self.check_btn.setObjectName('secondary')
        self.check_btn.clicked.connect(self.load_models)
        side.addWidget(self.check_btn)

        side.addSpacing(15)

        workspace = QLabel("بخش‌های برنامه")
        workspace.setAlignment(Qt.AlignmentFlag.AlignRight)
        workspace.setStyleSheet(
            "color: #45e69a; font-weight: bold;"
        )

        side.addWidget(workspace)

        for item in (
            "💬  گفت‌وگوی هوشمند",
            "🔍  تحلیل یافته‌های امنیتی",
            "📄  تهیه گزارش امنیتی",
        ):
            label = QLabel(item)
            label.setAlignment(Qt.AlignmentFlag.AlignRight)
            label.setStyleSheet("padding: 7px 2px;")
            side.addWidget(label)

        note = QLabel(
             "این دستیار برای تحلیل امنیتی، "
            "آزمایشگاه‌ها و ارزیابی‌های مجاز طراحی شده است."
        )

        note.setWordWrap(True)
        note.setAlignment(Qt.AlignmentFlag.AlignRight)
        note.setStyleSheet(
            "color: #94a3b8; padding: 8px 2px;"
        )
        side.addWidget(note)
        side.addStretch()

        clear_btn = QPushButton("＋  گفت‌وگوی جدید")
        clear_btn.clicked.connect(self.clear_chat)
        side.addWidget(clear_btn)

        layout.addWidget(sidebar)

        # Main panel

        panel = QWidget()
        content = QVBoxLayout(panel)
        content.setContentsMargins(0,0,0,0)
        content.setSpacing(12)

        header = QFrame()
        header.setObjectName('header')

        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18,14,18,14)

        title = QLabel("دستیار هوشمند امنیت سایبری")
        title.setAlignment(Qt.AlignmentFlag.AlignRight)
        title.setStyleSheet("""
            font-size: 23px;
            font-weight: bold;
            color: #45e69a;
        """)
        header_layout.addWidget(title)

        description = QLabel(
            "تحلیل امنیتی • بررسی خروجی ابزارها • آموزش دفاعی"
        )
        description.setAlignment(Qt.AlignmentFlag.AlignRight)
        description.setStyleSheet("color: #94a3b8;")
        header_layout.addWidget(description)

        content.addWidget(header)

        self.chat = QTextEdit()
        self.chat.setReadOnly(True)
        self.chat.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
        )
        self.chat.setPlaceholderText(
            "گفت‌وگوی شما با دستیار در این قسمت نمایش داده می‌شود..."
        )

        content.addWidget(self.chat,1)

        # Message input box

        row = QHBoxLayout()
        row.setSpacing(10)

        self.prompt = QLineEdit()
        self.prompt.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft
        )
        self.prompt.setPlaceholderText(
            "سؤال خود را درباره امنیت، آسیب‌پذیری یا گزارش وارد کنید..."
        )

        self.prompt.returnPressed.connect(self.send_message)
        row.addWidget(self.prompt,1)

        self.send_btn = QPushButton("ارسال پیام  ➤")
        self.send_btn.setMinimumWidth(125)
        self.send_btn.clicked.connect(self.send_message)
        row.addWidget(self.send_btn)

        content.addLayout(row)
        layout.addWidget(panel,1)

        self.append_message(
            "سیستم",
            "به هک‌بات خوش آمدید! سؤال خود را وارد کنید.",
            "#45e69a"
        )

        self.load_models()

    def append_message(self, sender, message, color):
        # preverting html interpretation within messages
        safe_sender = html.escape(sender)
        safe_message = html.escape(message).replace(
            '\n', '<br>'
        )

        self.chat.append(
            f"""
            <div dir="rtl" style="margin-top: 12px;">
                <span style="color:{color}; font-weight:bold;">
                    {safe_sender}
                </span>
                <div style="
                    color:#d9e2ec;
                    margin-top:6px;
                    line-height:1.8;
                ">
                    {safe_message}
                </div>
            </div>
            <br>
            """
            )

    def load_models(self):
        self.check_btn.setEnabled(False)

        try:
            response = requests.get(
                f'{API}/api/tags',
                    timeout=5
                    )
            response.raise_for_status()

            names = [
                        model['name']
                        for model in response.json().get('models',[])
                    ]

            current = self.models.currentText()
            self.models.clear()
            self.models.addItems(names)

            preferred = self.models.findText(current)

            if preferred < 0:
                preferred = self.models.findText(
                            'llama3.2:latest'
                        )
            if preferred >=0:
                self.models.setCurrentIndex(preferred)

            if names:
                self.status.setText("● اتصال به Ollama برقرار است")
                self.status.setStyleSheet("color: #45e69a;")
            else:
                self.status.setText(
                            "● اتصال برقرار است؛ مدلی نصب نشده"
                        )
                self.status.setStyleSheet("color: #f6c85f;")

        except Exception:
            self.models.clear()
            self.status.setText("● اتصال به Ollama برقرار نیست")
            self.status.setStyleSheet("color: #ff7272;")

        finally:
            self.check_btn.setEnabled(True)

    def clear_chat(self):
        if self.worker and self.worker.isRunning():
            return

        self.history = self.history[:1]
        self.chat.clear()

        self.append_message(
            "سیستم",
            "گفت‌وگوی جدید آغاز شد. چطور می‌توانم کمک کنم؟",
            "#45e69a"
        )

    def send_message(self):
        prompt = self.prompt.text().strip()

        if not prompt:
            return

        if self.worker and self.worker.isRunning():
            return

        model = self.models.currentText()

        if not model:
            QMessageBox.warning(
                self,
                "انتخاب مدل",
                "ابتدا یک مدل نصب‌شده در Ollama انتخاب کنید."
            )
            return

        self.history.append({
            'role':'user',
            'content': prompt
        })

        self.append_message("شما",prompt,"#45e69a")
        self.prompt.clear()

        self.send_btn.setEnabled(False)
        self.check_btn.setEnabled(False)
        self.status.setText("● هوش مصنوعی در حال پاسخ‌گویی است...")
        self.status.setStyleSheet("color: #f6c85f;")

        self.worker = AIWorker(
            model,
            self.history.copy()
        )
        self.worker.finished_text.connect(self.on_answer)
        self.worker.failed.connect(self.on_error)
        self.worker.finished.connect(self.on_worker_finished)
        self.worker.start()

    def on_answer(self, answer):
        self.history.append({
            'role': 'assistant',
            'content': answer
        })

        self.append_message(
            "هک‌بات",
            answer,
            "#45e69a"
        )

        self.status.setText("● پاسخ دریافت شد")
        self.status.setStyleSheet("color: #45e69a;")

    def on_error(self,error):
        self.append_message(
            "خطا",
            error,
            "#ff7272"
        )

        self.status.setText("● خطا در دریافت پاسخ")
        self.status.setStyleSheet("color: #ff7272;")

    def on_worker_finished(self):
        self.send_btn.setEnabled(True)
        self.check_btn.setEnabled(True)

    def closeEvent(self, event):
        if self.worker and self.worker.isRunning():
            QMessageBox.information(
                self,
                "درخواست در حال اجرا",
                "لطفاً تا پایان درخواست جاری صبر کنید."
            )
            event.ignore()
            return
        event.accept()

if __name__=='__main__':
    app = QApplication(sys.argv)

    app.setLayoutDirection(
        Qt.LayoutDirection.RightToLeft
    )
    app.setApplicationName("هک‌بات")

    window = Hackbot()
    window.show()

    sys.exit(app.exec())