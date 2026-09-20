# -*- coding: utf-8 -*-
"""
PyQt6 版本的自動閱卷小助手主程式
Design by 楊智琨 20260201
"""

import sys
import os
from datetime import datetime

# --windowed（無 console）模式下 sys.stdout/stderr 會是 None，
# 任何輸出（含第三方庫）都可能 crash → 預先導向 devnull 防呆。
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass
if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QTextEdit, QFileDialog,
    QMessageBox, QFrame, QSizePolicy, QComboBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QTextCursor, QPalette, QColor
import cv2
import numpy as np
import pandas as pd
import fitz  # PyMuPDF
import openpyxl
from openpyxl.styles import Font as XlFont, PatternFill

# 匯入核心模組
from omr_upgrade import OMRProcessor
from config_manager import ConfigManager
from classsheet import build_class_grade_sheet


# ==========================================
# 批改執行緒（QThread）
# ==========================================

class GradingThread(QThread):
    """批改執行緒 - 使用 QThread 避免 UI 阻塞"""
    
    # 定義 signals
    log_signal = pyqtSignal(str)  # 發送 log 訊息
    progress_signal = pyqtSignal(int, int)  # 發送進度 (current, total)
    finished_signal = pyqtSignal(bool, str)  # 完成信號 (success, message)
    
    def __init__(self, pdf_path, output_dir, omr_processor, config_manager, card_mode="OFFICIAL"):
        super().__init__()
        self.pdf_path = pdf_path
        self.output_dir = output_dir
        self.omr = omr_processor
        self.config_mgr = config_manager
        self.card_mode = card_mode  # "OFFICIAL"=正式卡 / "PRINTED"=影印卡
        self.is_running = True
    
    def run(self):
        """執行批改流程"""
        try:
            # 依卡別設定定位模式與渲染解析度
            self.omr.set_card_mode(self.card_mode)
            if self.card_mode in ("PRINTED", "PRINTED_0914"):
                self.render_mat = fitz.Matrix(200 / 72.0, 200 / 72.0)  # 影印卡：200dpi（定位校準值）
                self.log_signal.emit("卡別：影印卡（timing marks 定位，200dpi）")
            elif self.card_mode == "OFFICIAL_DYN":
                self.render_mat = fitz.Matrix(4, 4)  # 正式卡-動態定位版：4x 渲染
                self.log_signal.emit("卡別：正式卡-動態定位版（timing+四角動態定位，4x）")
            else:
                self.render_mat = fitz.Matrix(4, 4)  # 正式卡：原渲染
                self.log_signal.emit("卡別：正式卡（錨線透視定位）")

            self.log_signal.emit(f"開啟 PDF: {os.path.basename(self.pdf_path)}")
            doc = fitz.open(self.pdf_path)
            total_pages = len(doc)
            
            img_out_dir = os.path.join(self.output_dir, "Graded_Images")
            if not os.path.exists(img_out_dir):
                os.makedirs(img_out_dir)
            
            id_map = self.omr.build_identity_map()
            q_config, ans_key, _ = self.config_mgr.get_config()
            all_grades = []
            audit_rows = []
            
            for page_num, page in enumerate(doc):
                if not self.is_running:
                    self.log_signal.emit("批改已取消")
                    self.finished_signal.emit(False, "批改已取消")
                    return
                
                self.log_signal.emit(f"正在處理第 {page_num+1}/{total_pages} 頁...")
                self.progress_signal.emit(page_num + 1, total_pages)
                
                # 轉換 PDF 頁面為影像（解析度依卡別）
                mat = self.render_mat
                pix = page.get_pixmap(matrix=mat)
                
                img_data = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, pix.n)
                if pix.n == 4:
                    img_bgr = cv2.cvtColor(img_data, cv2.COLOR_RGBA2BGR)
                else:
                    img_bgr = cv2.cvtColor(img_data, cv2.COLOR_RGB2BGR)
                
                filename = f"Page_{page_num+1}.jpg"
                result, debug_img, status = self.omr.process_image(
                    img_bgr, filename, id_map, q_config, ans_key
                )
                
                audit = dict(getattr(self.omr, "last_audit", {}))
                audit.update(page=page_num + 1, status=status)
                audit_rows.append(audit)
                if result:
                    sid, ans, score = result
                    save_name = f"{sid}_{score}pts_P{page_num+1}.jpg".replace("?", "X")
                    full_save_path = os.path.join(img_out_dir, save_name)
                    
                    # 支援中文路徑
                    cv2.imencode('.jpg', debug_img)[1].tofile(full_save_path)
                    
                    all_grades.append({
                        "頁碼": page_num + 1,
                        "學號": sid,
                        "總分": score,
                        "檔名": save_name,
                        "時間": datetime.now().strftime("%H:%M:%S"),
                        "_review": "; ".join(audit.get("flags", [])),
                        "_answers": ans,  # 每題作答記錄（不寫進 DataFrame，用 openpyxl 處理）
                    })
                    self.log_signal.emit(f"-> 成功: 學號 {sid}, 分數 {score}")
                else:
                    fail_path = os.path.join(img_out_dir, f"FAIL_Page_{page_num+1}.jpg")
                    cv2.imencode('.jpg', debug_img)[1].tofile(fail_path)
                    self.log_signal.emit(f"-> 失敗: {status}")
            
            # Keep failures and uncertain observations visible independently of grades.
            import json
            with open(os.path.join(self.output_dir, "讀卡檢查.json"), "w", encoding="utf-8") as f:
                json.dump(audit_rows, f, ensure_ascii=False, indent=2)
            # 儲存成績單
            if all_grades:
                # 學號從小到大排序
                all_grades.sort(key=lambda g: str(g.get("學號", "")))

                excel_name = f"Grades_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx"
                excel_path = os.path.join(self.output_dir, excel_name)

                # 排序題號（數字題號照數字排，非數字照字串排）
                def q_sort_key(q):
                    s = str(q)
                    return (int(s) if s.isdigit() else float('inf'), s)
                all_q_nos = sorted(ans_key.keys(), key=q_sort_key)

                blue_font  = XlFont(color="2E75B6", bold=True)   # 答對 → 藍色粗體
                black_font = XlFont(color="000000")               # 答錯 → 黑色

                def write_sheet(ws, grades_list):
                    """將成績寫入指定 worksheet"""
                    # 標題列
                    headers = ["頁碼", "學號", "班級", "座號", "總分（初判）"] + [f"Q{q}" for q in all_q_nos] + ["檔名", "時間", "待核原因"]
                    ws.append(headers)

                    # 第二列：各題正確答案
                    ans_row = ["", "正確答案", "", "", ""] + [
                        str(ans_key.get(q, "")) for q in all_q_nos
                    ] + ["", ""]
                    ws.append(ans_row)

                    # 第三列：各題答對率
                    n_stu = len(grades_list)
                    q_ok = {}
                    for g in grades_list:
                        sa = g.get("_answers", {})
                        for q_no in all_q_nos:
                            stu_ans = "".join(sorted(str(sa.get(q_no, ""))))
                            correct_raw = str(ans_key.get(q_no, ""))
                            if correct_raw == "BONUS" or (stu_ans and stu_ans == "".join(sorted(correct_raw))):
                                q_ok[q_no] = q_ok.get(q_no, 0) + 1
                    rate_row = ["", "答對率", "", "", ""] + [
                        f"{100*q_ok.get(q,0)//n_stu}%" if n_stu > 0 else ""
                        for q in all_q_nos
                    ] + ["", ""]
                    ws.append(rate_row)

                    # 學生資料列
                    for grade in grades_list:
                        stu_answers = grade.get("_answers", {})
                        stu_id = str(grade["學號"])
                        # 學號為純數字才拆班級/座號並轉 int；辨識失敗（如 "Unknown"）保留原字串、班級座號留空
                        # （apply_flags 會把非五碼學號標橘底提醒人工核對）
                        if stu_id.isdigit() and len(stu_id) >= 3:
                            ban_ji  = int(stu_id[:3])
                            zuo_hao = int(stu_id[3:]) if len(stu_id) > 3 else 0
                            id_cell = int(stu_id)
                        else:
                            ban_ji  = ""
                            zuo_hao = ""
                            id_cell = stu_id

                        row_data = [grade["頁碼"], id_cell, ban_ji, zuo_hao, grade["總分"]]
                        for q_no in all_q_nos:
                            raw = stu_answers.get(q_no, "")
                            row_data.append("".join(sorted(str(raw))) if raw else "")
                        row_data += [grade["檔名"], grade["時間"], grade.get("_review", "")]
                        ws.append(row_data)

                        # 頁碼欄加超連結 → 批改圖
                        # 用「產檔當下的實際輸出資料夾」即時算絕對路徑(不寫死任何機器路徑)，
                        # 避免檔案放 OneDrive/雲端同步夾時，相對路徑被 Excel 接到雲端網址 → 點了跳登入頁。
                        # 絕對本機路徑可攜到任何機器(同事跑 EXE 存到自己資料夾也正確)。
                        abs_url = "Graded_Images/" + grade['檔名']
                        page_cell = ws.cell(row=ws.max_row, column=1)
                        page_cell.hyperlink = abs_url
                        page_cell.style = "Hyperlink"

                        # 逐題標色
                        row_idx = ws.max_row
                        q_col_start = 6  # 頁碼/學號/班級/座號/總分 共5欄，第6欄起是題目
                        for offset, q_no in enumerate(all_q_nos):
                            cell = ws.cell(row=row_idx, column=q_col_start + offset)
                            stu_ans = "".join(sorted(str(stu_answers.get(q_no, ""))))
                            correct_raw = str(ans_key.get(q_no, ""))
                            if correct_raw == "BONUS" or (stu_ans and stu_ans == "".join(sorted(correct_raw))):
                                cell.font = blue_font
                            else:
                                cell.font = black_font

                # ── 建立活頁簿 ──
                wb = openpyxl.Workbook()

                # 主分頁：全部學生
                ws_all = wb.active
                ws_all.title = "成績單"
                write_sheet(ws_all, all_grades)

                # ── 共用：建立全域重複學號計數表 ──
                from collections import Counter, defaultdict as _dd
                all_sid_list = [str(g["學號"]) for g in all_grades]
                global_sid_count = Counter(all_sid_list)
                orange_fill = PatternFill(start_color="FFA500", end_color="FFA500", fill_type="solid")

                def apply_flags(ws, grades_list):
                    """計算異常列並在該 worksheet 上橘色底色"""
                    sid_list = [str(g["學號"]) for g in grades_list]
                    flagged = set()

                    # 規則①：全域重複學號（兩筆都標）
                    # 規則②：非五碼數字
                    # 規則③：座號末兩碼為 00
                    for idx, sid in enumerate(sid_list):
                        if global_sid_count[sid] > 1:
                            flagged.add(idx)
                        if not (sid.isdigit() and len(sid) == 5):
                            flagged.add(idx)
                        elif sid[3:] == "00":
                            flagged.add(idx)

                    # 規則④：同班座號跳號（前後兩筆）
                    class_seat_map = _dd(list)
                    for idx, sid in enumerate(sid_list):
                        if sid.isdigit() and len(sid) == 5 and sid[3:] != "00":
                            class_seat_map[sid[:3]].append((int(sid[3:]), idx))

                    for seats in class_seat_map.values():
                        seats.sort()
                        for i in range(1, len(seats)):
                            prev_seat, prev_idx = seats[i - 1]
                            curr_seat, curr_idx = seats[i]
                            if curr_seat - prev_seat > 1:
                                flagged.add(prev_idx)
                                flagged.add(curr_idx)

                    if flagged:
                        data_row_start = 4
                        total_cols = ws.max_column
                        for idx in flagged:
                            for col in range(1, total_cols + 1):
                                ws.cell(row=idx + data_row_start, column=col).fill = orange_fill
                    return len(flagged)

                # ── 主分頁套用異常標記 ──
                n_flagged = apply_flags(ws_all, all_grades)
                if n_flagged:
                    self.log_signal.emit(f"⚠️ 發現 {n_flagged} 筆學號異常（橘色標記），請人工確認！")

                # 各班分頁：依班級（前三碼）分組
                class_groups = _dd(list)
                for grade in all_grades:
                    stu_id = str(grade["學號"])
                    ban_ji = stu_id[:3] if len(stu_id) >= 3 else stu_id
                    class_groups[ban_ji].append(grade)

                # 工作表名稱防呆：過濾 openpyxl 非法字元、限長 31、避免重複/空白
                import re as _re_sheet
                _used_titles = set()
                def _safe_sheet_title(name):
                    t = _re_sheet.sub(r'[:\\/?*\[\]]', '_', str(name)).strip()[:31]
                    if not t:
                        t = "未命名"
                    base = t
                    n = 1
                    while t in _used_titles:
                        n += 1
                        suffix = f"_{n}"
                        t = base[:31 - len(suffix)] + suffix
                    _used_titles.add(t)
                    return t

                for ban_ji in sorted(class_groups.keys()):
                    ws_class = wb.create_sheet(title=_safe_sheet_title(ban_ji))
                    write_sheet(ws_class, class_groups[ban_ji])
                    apply_flags(ws_class, class_groups[ban_ji])   # ← 班級分頁也套用

                # ── 班級成績表分頁（比照讀卡機格式，每班一頁）──
                try:
                    meta = self.config_mgr.get_meta()
                    for ban_ji in sorted(class_groups.keys()):
                        if not str(ban_ji).isdigit():
                            self.log_signal.emit("未知班級保留於總表與待核表，不建立班級成績表。")
                            continue
                        students = []
                        for g in class_groups[ban_ji]:
                            sid = str(g["學號"])
                            seat = sid[3:] if (sid.isdigit() and len(sid) >= 5) else sid
                            students.append({
                                "座號": seat,
                                "姓名": "",
                                "選擇": g.get("總分", 0),
                                "非選": 0,
                                "answers": g.get("_answers", {}),
                            })
                        build_class_grade_sheet(wb, ban_ji, students, ans_key, q_config, meta)
                except Exception as _e_cs:
                    self.log_signal.emit(f"班級成績表產生略過: {_e_cs}")

                review_sheet = wb.create_sheet("讀卡待核")
                review_sheet.append(["頁碼", "狀態", "需人工核對（分數為初判）"])
                for audit in audit_rows:
                    review_sheet.append([audit["page"], audit["status"], "; ".join(audit.get("flags", []))])
                review_sheet.column_dimensions['A'].width = 10
                review_sheet.column_dimensions['B'].width = 30
                review_sheet.column_dimensions['C'].width = 100
                review_sheet.freeze_panes = 'A2'
                wb.save(excel_path)
                self.log_signal.emit(f"批改完成！成績單已存至: {excel_name}")

                # 產出讀卡結果 PDF（把所有標記圖合併成一個 PDF）
                try:
                    pdf_name = f"讀卡結果_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                    pdf_path = os.path.join(self.output_dir, pdf_name)
                    n_pdf = self._build_result_pdf(img_out_dir, pdf_path)
                    if n_pdf:
                        self.log_signal.emit(f"讀卡結果 PDF 已存至: {pdf_name}（{n_pdf} 頁）")
                except Exception as e:
                    self.log_signal.emit(f"PDF 產生失敗（不影響 Excel）: {e}")

                self.finished_signal.emit(True, f"批改完成：{len(all_grades)}/{total_pages} 頁有成績；請查看「讀卡待核」與批閱圖，分數為初判。")
            else:
                self.log_signal.emit("未產生任何有效成績。")
                self.finished_signal.emit(False, "未產生任何有效成績")
        
        except Exception as e:
            self.log_signal.emit(f"發生嚴重錯誤: {str(e)}")
            import traceback
            traceback.print_exc()
            self.finished_signal.emit(False, f"錯誤: {str(e)}")
    
    def _build_result_pdf(self, img_dir, pdf_path):
        """把 Graded_Images 內所有標記圖依頁碼合併成一個 PDF。回傳頁數。"""
        import glob
        import re
        files = glob.glob(os.path.join(img_dir, "*.jpg"))
        if not files:
            return 0

        def pnum(p):
            m = re.search(r'P(\d+)\.jpg$', os.path.basename(p))
            return int(m.group(1)) if m else 999999
        files.sort(key=pnum)

        out = fitz.open()
        for fp in files:
            with open(fp, 'rb') as fh:          # open() 支援中文路徑
                data = fh.read()
            imgdoc = fitz.open(stream=data, filetype="jpg")
            rect = imgdoc[0].rect
            pdfbytes = imgdoc.convert_to_pdf()
            imgdoc.close()
            src = fitz.open("pdf", pdfbytes)
            page = out.new_page(width=rect.width, height=rect.height)
            page.show_pdf_page(page.rect, src, 0)
            src.close()
        out.save(pdf_path)
        out.close()
        return len(files)

    def stop(self):
        """停止執行緒"""
        self.is_running = False


# ==========================================
# PyQt6 主視窗
# ==========================================

class MainWindow(QMainWindow):
    """主視窗 - PyQt6 版本"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自動閱卷小助手 V5.2 試用版 班級成績表+ID判定 (PyQt6)")
        self.setMinimumSize(900, 700)
        
        # 初始化核心模組
        if getattr(sys, 'frozen', False):
            self.base_dir = sys._MEIPASS
        else:
            self.base_dir = os.path.dirname(os.path.abspath(__file__))
        
        # 設定應用程式圖示
        icon_path = os.path.join(self.base_dir, 'my_icon.ico')
        if os.path.exists(icon_path):
            from PyQt6.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))
        
        self.assets_dir = os.path.join(self.base_dir, 'assets')
        self.omr = OMRProcessor(self.assets_dir)
        self.user_dir = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) else self.base_dir
        self.config_mgr = ConfigManager(os.path.join(self.user_dir, "exam_config.xlsx"))
        
        # 批改執行緒
        self.grading_thread = None
        
        # 設定 UI
        self.setup_ui()
        
        # 載入配置
        self.load_config()
    
    def setup_ui(self):
        """設定 UI 介面"""
        # 主容器
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # ===== 標題區 =====
        header_frame = QFrame()
        header_frame.setStyleSheet("background-color: #E0F7FA; border-radius: 8px;")
        header_frame.setFixedHeight(80)
        header_layout = QVBoxLayout(header_frame)
        
        title_label = QLabel("自動閱卷小助手")
        title_font = QFont("Microsoft JhengHei", 20, QFont.Weight.Bold)
        title_label.setFont(title_font)
        title_label.setStyleSheet("color: #006064;")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title_label)
        
        version_label = QLabel("Design by 楊智琨 20260201 | Version 5.2 試用版 2026-09-20 班級成績表+ID判定 (PyQt6)")
        version_label.setStyleSheet("color: #00838F; font-size: 10pt;")
        version_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(version_label)
        
        main_layout.addWidget(header_frame)
        
        # ===== 檔案選擇區 =====
        file_frame = QFrame()
        file_frame.setStyleSheet("background-color: #FAFAFA; border-radius: 8px; padding: 15px;")
        file_layout = QVBoxLayout(file_frame)
        
        # PDF 檔案
        pdf_layout = QHBoxLayout()
        pdf_label = QLabel("PDF 檔案:")
        pdf_label.setFont(QFont("Microsoft JhengHei", 11))
        pdf_label.setFixedWidth(100)
        self.pdf_path_edit = QLineEdit()
        self.pdf_path_edit.setFont(QFont("Microsoft JhengHei", 10))
        self.pdf_path_edit.setPlaceholderText("請選擇 PDF 檔案...")
        pdf_browse_btn = QPushButton("瀏覽...")
        pdf_browse_btn.setFont(QFont("Microsoft JhengHei", 10))
        pdf_browse_btn.setFixedWidth(100)
        pdf_browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #64B5F6;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #42A5F5;
            }
        """)
        pdf_browse_btn.clicked.connect(self.browse_pdf)
        pdf_layout.addWidget(pdf_label)
        pdf_layout.addWidget(self.pdf_path_edit)
        pdf_layout.addWidget(pdf_browse_btn)
        file_layout.addLayout(pdf_layout)
        
        # 儲存位置
        output_layout = QHBoxLayout()
        output_label = QLabel("儲存位置:")
        output_label.setFont(QFont("Microsoft JhengHei", 11))
        output_label.setFixedWidth(100)
        self.output_dir_edit = QLineEdit()
        self.output_dir_edit.setFont(QFont("Microsoft JhengHei", 10))
        self.output_dir_edit.setPlaceholderText("請選擇儲存位置...")
        output_browse_btn = QPushButton("瀏覽...")
        output_browse_btn.setFont(QFont("Microsoft JhengHei", 10))
        output_browse_btn.setFixedWidth(100)
        output_browse_btn.setStyleSheet("""
            QPushButton {
                background-color: #64B5F6;
                color: white;
                border: none;
                border-radius: 4px;
                padding: 6px;
            }
            QPushButton:hover {
                background-color: #42A5F5;
            }
        """)
        output_browse_btn.clicked.connect(self.browse_output)
        output_layout.addWidget(output_label)
        output_layout.addWidget(self.output_dir_edit)
        output_layout.addWidget(output_browse_btn)
        file_layout.addLayout(output_layout)

        # 答案卡類型（正式卡 / 影印卡）
        card_layout = QHBoxLayout()
        card_label = QLabel("答案卡類型:")
        card_label.setFont(QFont("Microsoft JhengHei", 11))
        card_label.setFixedWidth(100)
        self.card_combo = QComboBox()
        self.card_combo.setFont(QFont("Microsoft JhengHei", 11))
        self.card_combo.addItem("影印卡－9/14 改良版（試用／需覆核）", "PRINTED_0914")
        self.card_combo.addItem("正式卡-動態定位版（timing+四角）", "OFFICIAL_DYN")
        self.card_combo.addItem("影印卡（列印版，B5 掃成 A4）", "PRINTED")
        self.card_combo.addItem("正式卡（電腦閱卷標準卡）", "OFFICIAL")
        self.card_combo.setStyleSheet(
            "QComboBox { padding: 6px; border: 1px solid #B0BEC5; border-radius: 4px;"
            " color: black; background-color: white; }"
            "QComboBox::drop-down { border: none; width: 24px; }"
            "QComboBox QAbstractItemView {"
            " border: 1px solid #B0BEC5; background-color: white; outline: none;"
            " selection-background-color: #E3F2FD; selection-color: black; }"
            "QComboBox QAbstractItemView::item {"
            " min-height: 28px; padding: 4px 8px; color: black; background-color: white; }"
        )
        card_layout.addWidget(card_label)
        card_layout.addWidget(self.card_combo)
        file_layout.addLayout(card_layout)

        main_layout.addWidget(file_frame)
        
        # ===== 功能按鈕區 =====
        btn_frame = QFrame()
        btn_frame.setStyleSheet("background-color: #FAFAFA; border-radius: 8px; padding: 10px;")
        btn_layout = QVBoxLayout(btn_frame)
        
        # 設定題型按鈕
        config_btn = QPushButton("⚙️ 設定題型、配分與答案")
        config_btn.setFont(QFont("Microsoft JhengHei", 12, QFont.Weight.Bold))
        config_btn.setStyleSheet("""
            QPushButton {
                background-color: #FFF9C4;
                border: none;
                border-radius: 6px;
                padding: 12px;
                color: #333;
            }
            QPushButton:hover {
                background-color: #FFF59D;
            }
        """)
        config_btn.clicked.connect(self.open_config_window)
        btn_layout.addWidget(config_btn)
        
        # 參數設定與使用說明
        sub_btn_layout = QHBoxLayout()
        
        param_btn = QPushButton("⚙️ 參數設定")
        param_btn.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
        param_btn.setStyleSheet("""
            QPushButton {
                background-color: #E1BEE7;
                border: none;
                border-radius: 6px;
                padding: 10px;
                color: #333;
            }
            QPushButton:hover {
                background-color: #CE93D8;
            }
        """)
        param_btn.clicked.connect(self.open_param_settings)
        sub_btn_layout.addWidget(param_btn)
        
        guide_btn = QPushButton("📖 使用說明")
        guide_btn.setFont(QFont("Microsoft JhengHei", 11, QFont.Weight.Bold))
        guide_btn.setStyleSheet("""
            QPushButton {
                background-color: #C5E1A5;
                border: none;
                border-radius: 6px;
                padding: 10px;
                color: #333;
            }
            QPushButton:hover {
                background-color: #AED581;
            }
        """)
        guide_btn.clicked.connect(self.show_user_guide)
        sub_btn_layout.addWidget(guide_btn)
        
        btn_layout.addLayout(sub_btn_layout)
        main_layout.addWidget(btn_frame)
        
        # ===== 開始批改按鈕 =====
        self.start_btn = QPushButton("🚀 開始批改")
        self.start_btn.setFont(QFont("Microsoft JhengHei", 14, QFont.Weight.Bold))
        self.start_btn.setFixedHeight(50)
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #0277BD;
                color: white;
                border: none;
                border-radius: 8px;
                padding: 10px;
            }
            QPushButton:hover {
                background-color: #01579B;
            }
            QPushButton:disabled {
                background-color: #B0BEC5;
            }
        """)
        self.start_btn.clicked.connect(self.start_grading)
        main_layout.addWidget(self.start_btn)
        
        # ===== Log 區域 =====
        log_label = QLabel("執行紀錄:")
        log_label.setFont(QFont("Microsoft JhengHei", 10))
        main_layout.addWidget(log_label)
        
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.log_text.setStyleSheet("""
            QTextEdit {
                background-color: #1E1E1E;
                color: #00FF00;
                border: 1px solid #555;
                border-radius: 4px;
                padding: 8px;
            }
        """)
        main_layout.addWidget(self.log_text, 1)  # stretch factor = 1
        
        # 初始 log
        self.log("--- 執行系統就緒，等待指令 ---")
    
    def log(self, message):
        """輸出 log 訊息"""
        timestamp = datetime.now().strftime('%H:%M:%S')
        self.log_text.append(f"[{timestamp}] {message}")
        # 自動捲動到底部
        cursor = self.log_text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_text.setTextCursor(cursor)
    
    def browse_pdf(self):
        """瀏覽 PDF 檔案"""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "選擇 PDF 檔案", "", "PDF Files (*.pdf)"
        )
        if file_path:
            self.pdf_path_edit.setText(file_path)
    
    def browse_output(self):
        """瀏覽輸出目錄"""
        dir_path = QFileDialog.getExistingDirectory(self, "選擇儲存位置")
        if dir_path:
            self.output_dir_edit.setText(dir_path)
    
    def load_config(self):
        """載入配置檔案"""
        success, message = self.config_mgr.load_config()
        if success:
            self.log(message)
        else:
            self.log("尚未建立設定檔，請點擊設定按鈕。")
    
    def open_config_window(self):
        """開啟設定視窗"""
        from config_dialog import ConfigDialog
        dialog = ConfigDialog(self, self.config_mgr)
        if dialog.exec():
            self.log(f"設定更新：共 {len(self.config_mgr.ans_key)} 題")
    
    def open_param_settings(self):
        """開啟參數設定視窗"""
        if self.card_combo.currentData() == "PRINTED_0914":
            QMessageBox.information(self, "改良版參數", "9/14 改良模式使用固定已驗證參數，限 Q1～Q10。\n原參數面板只適用舊模式；新模式請依讀卡待核表覆核。")
            return
        from param_dialog import ParamDialog
        dialog = ParamDialog(self, self.omr)
        dialog.exec()
    
    def show_user_guide(self):
        """顯示使用說明"""
        from guide_dialog import GuideDialog
        dialog = GuideDialog(self)
        dialog.exec()
    
    def start_grading(self):
        """開始批改"""
        pdf_path = self.pdf_path_edit.text()
        output_dir = self.output_dir_edit.text()
        
        # 驗證輸入
        if not os.path.exists(pdf_path):
            QMessageBox.critical(self, "錯誤", "找不到 PDF 檔案")
            return
        if not os.path.exists(output_dir):
            QMessageBox.critical(self, "錯誤", "輸出路徑無效")
            return
        if not self.config_mgr.has_config():
            reply = QMessageBox.warning(
                self, "警告", "尚未設定答案，將僅進行閱卷但不計分\n是否繼續？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.No:
                return
        
        # 停用按鈕
        self.start_btn.setEnabled(False)
        self.start_btn.setText("批改中...")
        
        # 取得卡別選擇
        output_dir = os.path.join(output_dir, datetime.now().strftime("批改_%Y%m%d_%H%M%S_%f"))
        os.makedirs(output_dir, exist_ok=False)
        card_mode = self.card_combo.currentData()

        # 建立並啟動執行緒
        self.grading_thread = GradingThread(
            pdf_path, output_dir, self.omr, self.config_mgr, card_mode
        )
        self.grading_thread.log_signal.connect(self.log)
        self.grading_thread.finished_signal.connect(self.on_grading_finished)
        self.grading_thread.start()
    
    def on_grading_finished(self, success, message):
        """批改完成回調"""
        self.start_btn.setEnabled(True)
        self.start_btn.setText("🚀 開始批改")
        
        if success:
            QMessageBox.information(self, "完成", message)
        else:
            QMessageBox.warning(self, "注意", message)
    
    def closeEvent(self, event):
        """視窗關閉事件"""
        if self.grading_thread and self.grading_thread.isRunning():
            reply = QMessageBox.question(
                self, "確認", "批改正在進行中，確定要關閉嗎？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
            )
            if reply == QMessageBox.StandardButton.Yes:
                self.grading_thread.stop()
                self.grading_thread.wait()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()


# ==========================================
# 主程式入口
# ==========================================

def main():
    app = QApplication(sys.argv)

    # 設定應用程式樣式
    app.setStyle("Fusion")

    # 設定字體
    font = QFont("Microsoft JhengHei", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()

    # 關閉 PyInstaller 啟動畫面（splash）— 主視窗一出現就關掉
    # pyi_splash 只在打包後存在，開發直接跑時 import 失敗就略過
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:
        pass

    sys.exit(app.exec())


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # --windowed 無 console，把例外寫到 exe 旁的 crash_log.txt 方便除錯
        import traceback
        try:
            import pyi_splash
            pyi_splash.close()
        except Exception:
            pass
        if getattr(sys, "frozen", False):
            _base = os.path.dirname(sys.executable)
        else:
            _base = os.path.dirname(os.path.abspath(__file__))
        try:
            with open(os.path.join(_base, "crash_log.txt"), "a", encoding="utf-8") as _f:
                _f.write("\n==== %s ====\n" % datetime.now())
                traceback.print_exc(file=_f)
        except Exception:
            pass
        raise
