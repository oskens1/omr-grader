# -*- coding: utf-8 -*-
"""
配置對話框 - PyQt6 版本
用於設定題型、配分與答案
"""

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QLabel, QLineEdit, QPushButton, QComboBox, QTableWidget,
    QTableWidgetItem, QMessageBox, QFileDialog, QHeaderView,
    QScrollArea, QFrame
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QFont
import pandas as pd


class ConfigDialog(QDialog):
    """配置對話框"""
    
    def __init__(self, parent, config_manager):
        super().__init__(parent)
        self.config_mgr = config_manager
        self.setWindowTitle("試卷詳細設定 (V3.5)")
        self.setMinimumSize(800, 600)
        
        # 資料結構
        self.part_rows = []  # 配分設定的 UI 元件
        self.ans_rows = {}   # 答案設定的 UI 元件 {q_no: (line_edit, combo_box)}
        self.MAX_PARTS = 10
        
        self.setup_ui()
        self.restore_cached_data()
    
    def setup_ui(self):
        """設定 UI"""
        layout = QVBoxLayout(self)
        
        # Tab Widget
        self.tab_widget = QTabWidget()
        
        # Tab 1: 配分與題型設定
        tab1 = QWidget()
        self.setup_tab1(tab1)
        self.tab_widget.addTab(tab1, "1. 配分與題型設定")
        
        # Tab 2: 標準答案填寫
        tab2 = QWidget()
        self.setup_tab2(tab2)
        self.tab_widget.addTab(tab2, "2. 標準答案填寫")

        # Tab 3: 試卷資訊（班級成績表表頭）
        tab3 = QWidget()
        self.setup_tab3(tab3)
        self.tab_widget.addTab(tab3, "3. 試卷資訊")

        layout.addWidget(self.tab_widget)
    
    def setup_tab1(self, tab):
        """設定 Tab 1 - 配分與題型"""
        layout = QVBoxLayout(tab)
        
        # 工具列
        toolbar = QHBoxLayout()
        
        clear_btn = QPushButton("🗑️ 清空重置")
        clear_btn.setStyleSheet("background-color: #FFCDD2; padding: 8px;")
        clear_btn.clicked.connect(self.clear_all_forms)
        toolbar.addWidget(clear_btn)
        
        import_btn = QPushButton("📂 匯入 Excel")
        import_btn.setStyleSheet("padding: 8px;")
        import_btn.clicked.connect(self.import_excel)
        toolbar.addWidget(import_btn)
        
        export_btn = QPushButton("💾 匯出 Excel")
        export_btn.setStyleSheet("padding: 8px;")
        export_btn.clicked.connect(self.export_excel)
        toolbar.addWidget(export_btn)
        
        toolbar.addStretch()
        layout.addLayout(toolbar)
        
        # 表格
        self.part_table = QTableWidget(self.MAX_PARTS, 5)
        self.part_table.setHorizontalHeaderLabels([
            "題型 (下拉選擇)", "開始題號", "結束題號", "每題配分", "選項數 (N)"
        ])
        self.part_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        # 填充表格
        type_keys = ["-", "單選題", "複選題", "學測多選", "一般多選"]
        for i in range(self.MAX_PARTS):
            # 題型下拉選單
            type_combo = QComboBox()
            type_combo.addItems(type_keys)
            type_combo.currentTextChanged.connect(lambda text, row=i: self.on_type_change(row, text))
            self.part_table.setCellWidget(i, 0, type_combo)
            
            # 開始題號
            start_edit = QLineEdit()
            start_edit.setEnabled(i == 0)
            self.part_table.setCellWidget(i, 1, start_edit)
            
            # 結束題號
            end_edit = QLineEdit()
            end_edit.setEnabled(i == 0)
            self.part_table.setCellWidget(i, 2, end_edit)
            
            # 每題配分
            score_edit = QLineEdit()
            score_edit.setEnabled(i == 0)
            self.part_table.setCellWidget(i, 3, score_edit)
            
            # 選項數
            options_combo = QComboBox()
            options_combo.addItems(["2", "3", "4", "5"])
            options_combo.setCurrentText("5")
            options_combo.setEnabled(False)
            self.part_table.setCellWidget(i, 4, options_combo)
            
            self.part_rows.append((type_combo, start_edit, end_edit, score_edit, options_combo))
        
        layout.addWidget(self.part_table)
        
        # 提示
        hint_label = QLabel(
            "💡 提示說明：\n"
            "• 學測多選：錯一個選項扣一半分數，錯兩個以上不給分\n"
            "• 一般多選：依選項數量 N 倒扣，每錯一個扣 (題分 × 2/N)，僅此題型需設定選項數 (預設為 5)"
        )
        hint_label.setStyleSheet("color: #555; padding: 10px; background-color: #FFF9C4; border-radius: 4px;")
        hint_label.setWordWrap(True)
        layout.addWidget(hint_label)
    
    def setup_tab2(self, tab):
        """設定 Tab 2 - 標準答案"""
        layout = QVBoxLayout(tab)
        
        # 工具列
        toolbar = QHBoxLayout()
        
        refresh_btn = QPushButton("🔄 依照配分設定生成答案格")
        refresh_btn.setStyleSheet("background-color: #B3E5FC; padding: 8px;")
        refresh_btn.clicked.connect(self.generate_answer_sheet)
        toolbar.addWidget(refresh_btn)
        
        toolbar.addStretch()
        
        save_btn = QPushButton("💾 儲存並應用")
        save_btn.setStyleSheet("background-color: #C8E6C9; padding: 8px; font-weight: bold;")
        save_btn.clicked.connect(self.save_all_config)
        toolbar.addWidget(save_btn)
        
        layout.addLayout(toolbar)
        
        # 捲動區域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        
        self.ans_frame = QWidget()
        self.ans_layout = QVBoxLayout(self.ans_frame)
        
        scroll.setWidget(self.ans_frame)
        layout.addWidget(scroll)
    
    def setup_tab3(self, tab):
        """設定 Tab 3 - 試卷資訊（班級成績表表頭，會記憶）"""
        layout = QVBoxLayout(tab)

        hint = QLabel(
            "📋 這裡填的資訊會出現在「班級成績表」分頁的表頭，並自動記憶（存於 exam_meta.json），"
            "下次開啟沿用。每次考試通常只需改「次數」。"
        )
        hint.setStyleSheet("color: #555; padding: 10px; background-color: #E1F5FE; border-radius: 4px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.meta_edits = {}
        fields = [
            ("學校", "學校名稱", "例：新北市立永平高中"),
            ("學年度", "學年度", "例：114"),
            ("學期", "第幾學期", "例：1 或 2"),
            ("次數", "第幾次段考", "例：1（第一次定期評量）"),
            ("科目", "科目", "例：物理"),
        ]
        meta = self.config_mgr.get_meta()
        for key, label_txt, placeholder in fields:
            row = QHBoxLayout()
            lbl = QLabel(label_txt + "：")
            lbl.setFixedWidth(110)
            lbl.setFont(QFont("Microsoft JhengHei", 11))
            edit = QLineEdit()
            edit.setFont(QFont("Microsoft JhengHei", 11))
            edit.setPlaceholderText(placeholder)
            edit.setText(str(meta.get(key, "")))
            row.addWidget(lbl)
            row.addWidget(edit)
            layout.addLayout(row)
            self.meta_edits[key] = edit

        # 預覽
        self.meta_preview = QLabel("")
        self.meta_preview.setStyleSheet("color: #00696B; padding: 8px; background-color: #F1F8E9; border-radius: 4px;")
        self.meta_preview.setWordWrap(True)
        layout.addWidget(self.meta_preview)
        for edit in self.meta_edits.values():
            edit.textChanged.connect(self.update_meta_preview)
        self.update_meta_preview()

        # 儲存按鈕
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_meta_btn = QPushButton("💾 儲存試卷資訊")
        save_meta_btn.setStyleSheet("background-color: #C8E6C9; padding: 8px; font-weight: bold;")
        save_meta_btn.clicked.connect(self.save_meta_only)
        btn_row.addWidget(save_meta_btn)
        layout.addLayout(btn_row)

        layout.addStretch()

    def get_meta_from_ui(self):
        """從 Tab3 收集試卷資訊。"""
        return {k: e.text().strip() for k, e in getattr(self, "meta_edits", {}).items()}

    def update_meta_preview(self):
        """更新表頭預覽。"""
        if not hasattr(self, "meta_preview"):
            return
        m = self.get_meta_from_ui()
        parts = []
        if m.get("學校"):
            parts.append(m["學校"])
        if m.get("學年度"):
            parts.append(f"{m['學年度']}學年度")
        if m.get("學期"):
            parts.append(f"第{m['學期']}學期")
        if m.get("次數"):
            parts.append(f"第{m['次數']}次定期評量")
        line1 = "  ".join(parts) if parts else "（未填）"
        subj = m.get("科目", "")
        self.meta_preview.setText(f"表頭預覽：\n{line1}\n○年級○○班({subj})班級成績表(座號排序)")

    def save_meta_only(self):
        """只儲存試卷資訊。"""
        success, message = self.config_mgr.save_meta(self.get_meta_from_ui())
        if success:
            QMessageBox.information(self, "成功", message)
        else:
            QMessageBox.warning(self, "失敗", message)

    def _refresh_meta_fields(self):
        """用 config_mgr 目前的 meta 更新第3頁欄位（匯入後呼叫）。"""
        if not hasattr(self, "meta_edits"):
            return
        meta = self.config_mgr.get_meta()
        for k, e in self.meta_edits.items():
            e.setText(str(meta.get(k, "")))
        self.update_meta_preview()

    def on_type_change(self, row_idx, text):
        """題型改變事件"""
        widgets = self.part_rows[row_idx]
        type_combo, start_edit, end_edit, score_edit, options_combo = widgets
        
        # 選項數控制
        if text == "一般多選":
            options_combo.setEnabled(True)
        elif text != "-":
            options_combo.setCurrentText("5")
            options_combo.setEnabled(False)
        else:
            options_combo.setEnabled(False)
        
        # 啟用下一行
        if text != "-" and row_idx + 1 < len(self.part_rows):
            next_widgets = self.part_rows[row_idx + 1]
            for i in range(4):  # 不包含選項數
                next_widgets[i].setEnabled(True)
    
    def generate_answer_sheet(self):
        """生成答案格"""
        max_q = 0
        q_type_map = {}
        
        try:
            for widgets in self.part_rows:
                type_combo, start_edit, end_edit, score_edit, options_combo = widgets
                t_str = type_combo.currentText()
                if t_str == "-" or t_str == "":
                    continue
                
                s = int(start_edit.text())
                e = int(end_edit.text())
                for q in range(s, e+1):
                    q_type_map[q] = t_str
                if e > max_q:
                    max_q = e
        except ValueError:
            QMessageBox.warning(self, "錯誤", "請確認題號與配分為有效數字")
            return
        
        if max_q == 0:
            QMessageBox.warning(self, "提示", "請先在 Tab 1 設定題型與題號範圍")
            return
        
        # 清空舊的答案格
        while self.ans_layout.count():
            child = self.ans_layout.takeAt(0)
            if child.widget():
                child.widget().deleteLater()
        
        self.ans_rows.clear()
        
        # 建立表格
        ans_table = QTableWidget(max_q, 3)
        ans_table.setHorizontalHeaderLabels(["題號", "標準答案", "備註"])
        ans_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        
        q_config, ans_key, _ = self.config_mgr.get_config()
        
        for q in range(1, max_q + 1):
            # 題號
            ans_table.setItem(q-1, 0, QTableWidgetItem(str(q)))
            
            # 標準答案
            ans_edit = QLineEdit()
            if q in ans_key:
                ans_edit.setText(ans_key[q])
            ans_table.setCellWidget(q-1, 1, ans_edit)
            
            # 備註
            curr_type = q_type_map.get(q, "")
            remark_values = ["", "送分", "容錯"] if curr_type == "單選題" else ["", "送分"]
            remark_combo = QComboBox()
            remark_combo.addItems(remark_values)
            
            if q in q_config:
                prev_remark = q_config[q].get("remark", "")
                if prev_remark:
                    remark_combo.setCurrentText(prev_remark)
                    if prev_remark == "送分":
                        ans_edit.clear()
                elif ans_key.get(q) == "BONUS":
                    remark_combo.setCurrentText("送分")
                    ans_edit.clear()
            
            ans_table.setCellWidget(q-1, 2, remark_combo)
            
            self.ans_rows[q] = (ans_edit, remark_combo)
        
        self.ans_layout.addWidget(ans_table)
    
    def gather_all_data_for_save(self):
        """收集所有資料準備儲存"""
        new_config = {}
        new_key = {}
        temp_cache = []
        q_rules = {}
        
        TYPE_MAP = {
            "-": "NONE", "單選題": "STRICT", "複選題": "EXACT",
            "學測多選": "GSAT", "一般多選": "NORMAL"
        }
        
        part_counter = 1
        for widgets in self.part_rows:
            type_combo, start_edit, end_edit, score_edit, options_combo = widgets
            t_str = type_combo.currentText()
            s_str = start_edit.text()
            e_str = end_edit.text()
            score_str = score_edit.text()
            opt_str = options_combo.currentText()
            
            temp_cache.append({
                "type": t_str, "start": s_str, "end": e_str,
                "score": score_str, "options": opt_str
            })
            
            if t_str == "-" or t_str == "":
                continue
            
            try:
                p_type = TYPE_MAP[t_str]
                start = int(s_str)
                end = int(e_str)
                score = float(score_str)
                n_opts = int(opt_str) if opt_str.isdigit() else 5
            except ValueError:
                raise ValueError("配分設定頁面有非數字輸入")
            
            auto_part_name = f"Part{part_counter}"
            part_counter += 1
            
            for q in range(start, end + 1):
                q_rules[q] = {
                    'type': p_type, 'score': score,
                    'part': auto_part_name, 'options': n_opts
                }
        
        if not self.ans_rows:
            raise ValueError("請先在 Tab 2 生成答案格")
        
        for q, (ans_edit, remark_combo) in self.ans_rows.items():
            raw_ans = ans_edit.text().strip().upper()
            remark = remark_combo.currentText()
            final_ans = "BONUS" if remark == "送分" else raw_ans
            
            if q not in q_rules:
                continue
            
            rule = q_rules[q]
            new_key[q] = final_ans
            new_config[q] = {
                'type': rule['type'], 'score': rule['score'],
                'part': rule['part'], 'options': rule['options'],
                'remark': remark
            }
        
        return new_config, new_key, temp_cache
    
    def save_all_config(self):
        """儲存所有配置"""
        try:
            new_config, new_key, temp_cache = self.gather_all_data_for_save()
            success, message = self.config_mgr.save_config(new_config, new_key, temp_cache)

            # 一併儲存試卷資訊（Tab3）
            if hasattr(self, "meta_edits"):
                self.config_mgr.save_meta(self.get_meta_from_ui())

            if success:
                QMessageBox.information(self, "成功", message)
                self.accept()  # 關閉對話框並返回 True
            else:
                QMessageBox.warning(self, "失敗", message)
        except Exception as e:
            QMessageBox.critical(self, "錯誤", str(e))
    
    def import_excel(self):
        """匯入 Excel 設定"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "匯入設定檔", "", "Excel Files (*.xlsx)"
        )
        if not file_path:
            return
        
        try:
            df = pd.read_excel(file_path)
            new_q_config, new_ans_key, new_cached_rows = self.config_mgr.parse_config_from_df(df)

            self.config_mgr.q_config = new_q_config
            self.config_mgr.ans_key = new_ans_key
            self.config_mgr.cached_part_rows = new_cached_rows

            # 清空 UI
            for widgets in self.part_rows:
                type_combo, start_edit, end_edit, score_edit, options_combo = widgets
                type_combo.setCurrentText("-")
                start_edit.clear()
                end_edit.clear()
                score_edit.clear()
                options_combo.setCurrentText("5")

            self.restore_cached_data()

            # 讀「試卷資訊」分頁（若有）→ 套用並更新第3頁
            meta_loaded = False
            try:
                meta_df = pd.read_excel(file_path, sheet_name="試卷資訊")
                meta = {str(r["欄位"]): ("" if pd.isna(r["值"]) else str(r["值"]))
                        for _, r in meta_df.iterrows() if not pd.isna(r.get("欄位"))}
                if meta:
                    self.config_mgr.save_meta(meta)
                    self._refresh_meta_fields()
                    meta_loaded = True
            except Exception:
                pass

            msg = "設定匯入成功！" + ("（含試卷資訊）" if meta_loaded else "")
            QMessageBox.information(self, "成功", msg)
        except Exception as e:
            QMessageBox.critical(self, "匯入失敗", str(e))
    
    def export_excel(self):
        """匯出 Excel 設定"""
        try:
            new_config, new_key, temp_cache = self.gather_all_data_for_save()
            
            excel_data = []
            for q_no, key in new_key.items():
                cfg = new_config.get(q_no, {})
                excel_data.append({
                    'Question': q_no, 'Answer': key,
                    'Score': cfg.get('score', 0), 'Type': cfg.get('type', 'STRICT'),
                    'Part': cfg.get('part', 'Part1'), 'Options': cfg.get('options', 5),
                    'Remark': cfg.get('remark', '')
                })
            
            file_path, _ = QFileDialog.getSaveFileName(
                self, "匯出設定檔", "", "Excel Files (*.xlsx)"
            )
            if not file_path:
                return
            
            # 試卷資訊（第3頁）一併寫成「試卷資訊」分頁，一個檔帶走全部設定
            meta = self.get_meta_from_ui() if hasattr(self, "meta_edits") else self.config_mgr.get_meta()
            meta_df = pd.DataFrame([{"欄位": k, "值": v} for k, v in meta.items()])

            with pd.ExcelWriter(file_path) as writer:
                pd.DataFrame(excel_data).to_excel(writer, sheet_name="設定", index=False)
                meta_df.to_excel(writer, sheet_name="試卷資訊", index=False)
            QMessageBox.information(self, "成功", "匯出成功！（含「試卷資訊」分頁）")
        except Exception as e:
            QMessageBox.critical(self, "匯出錯誤", str(e))
    
    def clear_all_forms(self):
        """清空所有表單"""
        reply = QMessageBox.question(
            self, "確認", "確定要清空所有設定嗎？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.config_mgr.cached_part_rows = []
            self.config_mgr.q_config = {}
            self.config_mgr.ans_key = {}
            
            # 重新初始化
            for widgets in self.part_rows:
                type_combo, start_edit, end_edit, score_edit, options_combo = widgets
                type_combo.setCurrentText("-")
                start_edit.clear()
                end_edit.clear()
                score_edit.clear()
                options_combo.setCurrentText("5")
            
            while self.ans_layout.count():
                child = self.ans_layout.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self.ans_rows.clear()
    
    def restore_cached_data(self):
        """恢復快取資料"""
        _, _, cached_rows = self.config_mgr.get_config()
        
        if cached_rows:
            for i, data in enumerate(cached_rows):
                if i >= self.MAX_PARTS:
                    break
                
                widgets = self.part_rows[i]
                type_combo, start_edit, end_edit, score_edit, options_combo = widgets
                
                type_combo.setCurrentText(data["type"])
                start_edit.setText(str(data["start"]))
                end_edit.setText(str(data["end"]))
                score_edit.setText(str(data["score"]))
                options_combo.setCurrentText(str(data["options"]))
                
                if i > 0:
                    for j in range(4):
                        widgets[j].setEnabled(True)
                
                self.on_type_change(i, data["type"])
                
                if data["type"] != "-" and i + 1 < self.MAX_PARTS:
                    next_widgets = self.part_rows[i + 1]
                    for j in range(4):
                        next_widgets[j].setEnabled(True)
            
            # 自動生成答案格
            if cached_rows:
                self.generate_answer_sheet()
