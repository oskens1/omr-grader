# -*- coding: utf-8 -*-
"""
使用說明對話框 - PyQt6 版本
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QTextEdit, QPushButton, QFrame, QLabel
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class GuideDialog(QDialog):
    """使用說明對話框"""
    
    def __init__(self, parent):
        super().__init__(parent)
        self.setWindowTitle("使用說明")
        self.setMinimumSize(650, 600)
        
        self.setup_ui()
    
    def setup_ui(self):
        """設定 UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 標題
        title_frame = QFrame()
        title_frame.setStyleSheet("background-color: #C5E1A5; border-radius: 8px; padding: 15px;")
        title_layout = QVBoxLayout(title_frame)
        
        title_label = QLabel("📖 自動閱卷小助手 - 使用說明")
        title_label.setFont(QFont("Microsoft JhengHei", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(title_label)
        
        layout.addWidget(title_frame)
        
        # 內容區
        content_text = QTextEdit()
        content_text.setReadOnly(True)
        content_text.setFont(QFont("Microsoft JhengHei", 11))
        content_text.setStyleSheet("""
            QTextEdit {
                background-color: #FAFAFA;
                border: 1px solid #DDD;
                border-radius: 6px;
                padding: 15px;
            }
        """)
        
        guide_content = """
【V5.2 試用版／2026-09-20】
新增「影印卡－9/14 改良版」，目前限 Q1～Q10、同款卡 A4 橫向 200dpi。
原有三模式仍保留；正式卡與超過10題請選原模式。
新模式有淡痕、學號不明等情況時，成績僅供初判；務必看 Excel「讀卡待核」。
定位失敗頁不計分，保留 FAIL 圖及「讀卡檢查.json」。
每批另存新資料夾。完整格式與限制請看分享包「使用說明.html」。

【操作流程】

1. 準備工作：將全班的答案卡掃描成一個 PDF 檔案。

2. 匯入檔案：點擊程式中的『瀏覽...』按鈕，匯入該 PDF。

3. 設定題型與答案：點擊『⚙️ 設定題型、配分與答案』按鈕，
   設定試卷的題型、配分和標準答案。

4. 開始評改：點擊『🚀 開始批改』，系統將自動辨識。


【輸出說明】

1. 圖片檔 (Images)：
   用於讓老師確認讀卡狀況，學生也能檢查自己是否畫記清楚。
   檔名格式：學號_分數_頁碼.jpg

2. Excel 檔：
   包含學號與分數，供成績登錄使用。
   檔名格式：Grades_日期時間.xlsx


【進階功能】

• 參數設定：若掃描品質不佳導致辨識錯誤，可透過『⚙️ 參數設定』
  調整判定閾值和填滿比例，以改善辨識效果。

• 題型支援：
  - 單選題：完全正確才給分
  - 複選題：完全正確才給分
  - 學測多選：錯一個給一半分，錯兩個以上不給分
  - 一般多選：依錯誤選項數量扣分（可設定選項數 2-5）
  - 送分題：所有人都給分
  - 容錯題：單選題可設定多個正確答案（例如 A 或 B 皆可）

• 匯入/匯出設定：可將題型配置匯出為 Excel，方便備份與分享。


【注意事項】

• 請確保答案卡掃描清晰，避免模糊或傾斜。
• 學生需使用 2B 鉛筆完整塗滿圓圈。
• 建議先用少量樣本測試，確認辨識正常後再大量批改。
• 批改過程中請勿關閉程式，以免中斷處理。


【技術支援】

• 本程式使用 PyQt6 開發，支援 Windows 作業系統。
• 核心辨識引擎基於 OpenCV 與透視變換技術。
• 如遇問題，請檢查：
  1. PDF 檔案是否正常開啟
  2. assets 資料夾是否包含必要的 CSV 模板
  3. exam_config.xlsx 是否正確設定


【版本資訊】

• 版本：V3.5 (PyQt6)
• 設計者：楊智琨
• 日期：2026/02/01
• 框架：PyQt6 + OpenCV + PyMuPDF
        """
        
        content_text.setPlainText(guide_content)
        layout.addWidget(content_text)
        
        # 關閉按鈕
        close_btn = QPushButton("關閉")
        close_btn.setFont(QFont("Microsoft JhengHei", 12, QFont.Weight.Bold))
        close_btn.setFixedHeight(45)
        close_btn.setStyleSheet("""
            QPushButton {
                background-color: #2196F3;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #1976D2;
            }
        """)
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)
