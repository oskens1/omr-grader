# -*- coding: utf-8 -*-
"""
參數設定對話框 - PyQt6 版本
用於調整 OMR 辨識參數
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QSlider, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont


class ParamDialog(QDialog):
    """參數設定對話框"""
    
    def __init__(self, parent, omr_processor):
        super().__init__(parent)
        self.omr = omr_processor
        self.setWindowTitle("進階參數設定")
        self.setMinimumSize(550, 450)  # 改為最小尺寸而非固定尺寸
        self.resize(550, 450)
        
        self.setup_ui()
    
    def setup_ui(self):
        """設定 UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(30, 30, 30, 30)
        
        # 標題
        title_frame = QFrame()
        title_frame.setStyleSheet("background-color: #E1BEE7; border-radius: 8px; padding: 15px;")
        title_layout = QVBoxLayout(title_frame)
        
        title_label = QLabel("OMR 識別參數調整")
        title_label.setFont(QFont("Microsoft JhengHei", 16, QFont.Weight.Bold))
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_layout.addWidget(title_label)
        
        layout.addWidget(title_frame)
        
        # 說明文字
        info_label = QLabel(
            "調整以下參數可改善不同掃描品質的辨識效果\n"
            "建議先使用預設值，若辨識不佳再微調"
        )
        info_label.setStyleSheet("color: #555; font-size: 10pt;")
        info_label.setWordWrap(True)
        layout.addWidget(info_label)
        
        # 參數1: 判定閾值
        param1_frame = QFrame()
        param1_frame.setStyleSheet("background-color: #F5F5F5; border-radius: 6px; padding: 15px;")
        param1_layout = QVBoxLayout(param1_frame)
        
        threshold_title = QLabel("判定閾值 (Threshold)")
        threshold_title.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
        param1_layout.addWidget(threshold_title)
        
        threshold_desc = QLabel("控制多黑才算有塗 (數值越小越敏感，越容易判定為已塗)")
        threshold_desc.setStyleSheet("color: #666; font-size: 9pt;")
        threshold_desc.setWordWrap(True)
        param1_layout.addWidget(threshold_desc)
        
        self.threshold_value_label = QLabel(f"目前值: {self.omr.BIN_TH_BUBBLE}")
        self.threshold_value_label.setFont(QFont("Microsoft JhengHei", 10, QFont.Weight.Bold))
        self.threshold_value_label.setStyleSheet("color: #0277BD; margin-top: 5px;")
        param1_layout.addWidget(self.threshold_value_label)
        
        self.threshold_slider = QSlider(Qt.Orientation.Horizontal)
        self.threshold_slider.setMinimum(150)
        self.threshold_slider.setMaximum(255)
        self.threshold_slider.setValue(self.omr.BIN_TH_BUBBLE)
        self.threshold_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.threshold_slider.setTickInterval(10)
        self.threshold_slider.valueChanged.connect(self.update_threshold_label)
        param1_layout.addWidget(self.threshold_slider)
        
        layout.addWidget(param1_frame)
        
        # 參數2: 填滿比例
        param2_frame = QFrame()
        param2_frame.setStyleSheet("background-color: #F5F5F5; border-radius: 6px; padding: 15px;")
        param2_layout = QVBoxLayout(param2_frame)
        
        fill_title = QLabel("填滿比例 (Fill Percentage)")
        fill_title.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
        param2_layout.addWidget(fill_title)
        
        fill_desc = QLabel("控制塗滿多少面積才算有效 (數值越小越容易判定為已塗)")
        fill_desc.setStyleSheet("color: #666; font-size: 9pt;")
        fill_desc.setWordWrap(True)
        param2_layout.addWidget(fill_desc)
        
        self.fill_value_label = QLabel(f"目前值: {self.omr.FILL_THRESHOLD:.2f}")
        self.fill_value_label.setFont(QFont("Microsoft JhengHei", 10, QFont.Weight.Bold))
        self.fill_value_label.setStyleSheet("color: #0277BD; margin-top: 5px;")
        param2_layout.addWidget(self.fill_value_label)
        
        self.fill_slider = QSlider(Qt.Orientation.Horizontal)
        self.fill_slider.setMinimum(5)  # 0.05
        self.fill_slider.setMaximum(50)  # 0.50
        self.fill_slider.setValue(int(self.omr.FILL_THRESHOLD * 100))
        self.fill_slider.setTickPosition(QSlider.TickPosition.TicksBelow)
        self.fill_slider.setTickInterval(5)
        self.fill_slider.valueChanged.connect(self.update_fill_label)
        param2_layout.addWidget(self.fill_slider)
        
        layout.addWidget(param2_frame)
        
        layout.addStretch()
        
        # 按鈕區
        btn_layout = QHBoxLayout()
        
        apply_btn = QPushButton("套用設定")
        apply_btn.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
        apply_btn.setFixedHeight(40)
        apply_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #45A049;
            }
        """)
        apply_btn.clicked.connect(self.apply_settings)
        btn_layout.addWidget(apply_btn)
        
        reset_btn = QPushButton("恢復預設")
        reset_btn.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
        reset_btn.setFixedHeight(40)
        reset_btn.setStyleSheet("""
            QPushButton {
                background-color: #FF9800;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #F57C00;
            }
        """)
        reset_btn.clicked.connect(self.reset_defaults)
        btn_layout.addWidget(reset_btn)
        
        cancel_btn = QPushButton("取消")
        cancel_btn.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
        cancel_btn.setFixedHeight(40)
        cancel_btn.setStyleSheet("""
            QPushButton {
                background-color: #9E9E9E;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #757575;
            }
        """)
        cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(cancel_btn)
        
        layout.addLayout(btn_layout)
    
    def update_threshold_label(self, value):
        """更新閾值標籤"""
        self.threshold_value_label.setText(f"目前值: {value}")
    
    def update_fill_label(self, value):
        """更新填滿比例標籤"""
        fill_value = value / 100.0
        self.fill_value_label.setText(f"目前值: {fill_value:.2f}")
    
    def apply_settings(self):
        """套用設定"""
        self.omr.BIN_TH_BUBBLE = self.threshold_slider.value()
        self.omr.FILL_THRESHOLD = self.fill_slider.value() / 100.0
        
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.information(
            self, "成功",
            f"參數已套用！\n"
            f"閾值: {self.omr.BIN_TH_BUBBLE}\n"
            f"填滿比例: {self.omr.FILL_THRESHOLD:.2f}\n\n"
            f"下次批改時將使用新參數。"
        )
        self.accept()
    
    def reset_defaults(self):
        """恢復預設值"""
        self.threshold_slider.setValue(230)
        self.fill_slider.setValue(20)  # 0.20
