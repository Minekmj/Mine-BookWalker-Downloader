from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import QPlainTextEdit

class ColorLogBox(QPlainTextEdit):

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)

    def appendPlainText(self, text: str):
        for line in (text or "").splitlines():
            self._append_colored_line(line)

    def _append_colored_line(self, line: str):
        cursor = self.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()

        low = line.lower()
        if any(k in line for k in ("[오류]", "실패", "오류:", "ERROR")) or "error" in low:
            fmt.setForeground(QColor("#e49090"))
            fmt.setFontWeight(QFont.Weight.Bold)
        elif any(k in line for k in ("완료", "복구", "성공", "추출 완료", "생성 완료")):
            fmt.setForeground(QColor("#81dba2"))
            fmt.setFontWeight(QFont.Weight.Bold)
        elif any(k in line for k in ("Z-score", "재시도", "재번역", "불일치", "경고", "중지", "누락", "부족")):
            fmt.setForeground(QColor("#e0ab81"))
        elif any(k in line for k in ("삽화", "백업", "청크", "EPUB 분석", "번역 진행", "목차")):
            fmt.setForeground(QColor("#819be6"))
        else:
            fmt.setForeground(QColor("#808D9E"))

        if not self.document().isEmpty():
            cursor.insertText("\n")
        cursor.insertText(line, fmt)
        self.setTextCursor(cursor)
        self.ensureCursorVisible()
