# -*- coding: utf-8 -*-
"""
配置管理模組
負責讀取、解析、儲存 exam_config.xlsx
與 UI 層解耦
"""

import pandas as pd
import os
import json


class ConfigManager:
    """配置管理器 - 負責題型、答案、配分的管理"""

    # 試卷資訊預設值（班級成績表表頭用）
    DEFAULT_META = {
        "學校": "",
        "學年度": "",
        "學期": "",
        "次數": "",
        "科目": "物理",
    }
    
    # 題型映射
    TYPE_MAP = {
        "-": "NONE",
        "單選題": "STRICT",
        "複選題": "EXACT",
        "學測多選": "GSAT",
        "一般多選": "NORMAL"
    }
    
    REVERSE_TYPE_MAP = {v: k for k, v in TYPE_MAP.items()}
    TYPE_KEYS = ["-", "單選題", "複選題", "學測多選", "一般多選"]
    
    def __init__(self, config_path="exam_config.xlsx"):
        """
        初始化配置管理器
        
        Args:
            config_path: 配置檔案路徑
        """
        self.config_path = config_path
        self.q_config = {}  # 題目配置 {q_no: {type, score, part, options, remark}}
        self.ans_key = {}   # 標準答案 {q_no: answer}
        self.cached_part_rows = []  # UI 快取資料

        # 試卷資訊（科目/學年度/學期/次數/學校）旁存於 exam_meta.json
        cfg_dir = os.path.dirname(os.path.abspath(config_path)) or "."
        self.meta_path = os.path.join(cfg_dir, "exam_meta.json")
        self.meta = dict(self.DEFAULT_META)
        self.load_meta()
    
    def load_config(self):
        """
        載入配置檔案
        
        Returns:
            tuple: (success, message)
        """
        if not os.path.exists(self.config_path):
            return False, "設定檔不存在"
        
        try:
            df = pd.read_excel(self.config_path)
            self.q_config, self.ans_key, self.cached_part_rows = self.parse_config_from_df(df)
            return True, f"✅ 已成功載入外部設定檔 ({self.config_path})"
        except Exception as e:
            return False, f"⚠️ 設定檔讀取失敗: {e}"
    
    def parse_config_from_df(self, df):
        """
        從 DataFrame 解析配置
        
        Args:
            df: pandas DataFrame
        
        Returns:
            tuple: (q_config, ans_key, cached_rows)
        """
        new_q_config = {}
        new_ans_key = {}
        cached_rows = []
        
        req_cols = ['Question', 'Type', 'Score', 'Options']
        if not all(col in df.columns for col in req_cols):
            raise ValueError("Excel 格式不符 (缺少必要欄位)")

        df = df.sort_values('Question')
        current_block = None

        for _, row in df.iterrows():
            q = int(row['Question'])
            p_type = row['Type']
            score = float(row['Score'])
            
            opts = 5
            if 'Options' in row and not pd.isna(row['Options']):
                opts = int(row['Options'])
                
            ans = ""
            if 'Answer' in row and not pd.isna(row['Answer']):
                ans = str(row['Answer'])
                
            rem = ""
            if 'Remark' in row and not pd.isna(row['Remark']):
                rem = str(row['Remark'])

            new_ans_key[q] = ans
            new_q_config[q] = {
                'type': p_type,
                'score': score,
                'part': row.get('Part', 'Part1'),
                'options': opts,
                'remark': rem
            }

            type_str = self.REVERSE_TYPE_MAP.get(p_type, "-")
            
            is_continuous = False
            if current_block:
                if (current_block['type'] == type_str and 
                    float(current_block['score']) == score and 
                    int(current_block['options']) == opts and
                    q == current_block['end'] + 1):
                    is_continuous = True
                    
            if is_continuous:
                current_block['end'] = q
            else:
                if current_block: 
                    cached_rows.append(current_block)
                current_block = {
                    'type': type_str, 'start': q, 'end': q, 
                    'score': score, 'options': opts
                }
        
        if current_block: 
            cached_rows.append(current_block)
        
        return new_q_config, new_ans_key, cached_rows
    
    def save_config(self, q_config, ans_key, cached_rows):
        """
        儲存配置到檔案
        
        Args:
            q_config: 題目配置
            ans_key: 標準答案
            cached_rows: UI 快取資料
        
        Returns:
            tuple: (success, message)
        """
        try:
            self.q_config = q_config
            self.ans_key = ans_key
            self.cached_part_rows = cached_rows
            
            # 轉換為 Excel 格式
            excel_data = []
            for q_no, key in ans_key.items():
                cfg = q_config.get(q_no, {})
                excel_data.append({
                    'Question': q_no,
                    'Answer': key,
                    'Score': cfg.get('score', 0),
                    'Type': cfg.get('type', 'STRICT'),
                    'Part': cfg.get('part', 'Part1'),
                    'Options': cfg.get('options', 5),
                    'Remark': cfg.get('remark', '')
                })
            
            pd.DataFrame(excel_data).to_excel(self.config_path, index=False)
            return True, "設定已儲存！"
        except PermissionError:
            return False, f"無法寫入 '{self.config_path}'，請先關閉該檔案。"
        except Exception as e:
            return False, f"存檔錯誤: {e}"
    
    def get_config(self):
        """取得當前配置"""
        return self.q_config, self.ans_key, self.cached_part_rows
    
    def has_config(self):
        """檢查是否有配置"""
        return len(self.ans_key) > 0

    # ── 試卷資訊（班級成績表表頭）──
    def load_meta(self):
        """從 exam_meta.json 載入試卷資訊；缺檔則用預設。"""
        try:
            if os.path.exists(self.meta_path):
                with open(self.meta_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                merged = dict(self.DEFAULT_META)
                merged.update({k: str(v) for k, v in data.items()})
                self.meta = merged
        except Exception:
            self.meta = dict(self.DEFAULT_META)
        return self.meta

    def save_meta(self, meta):
        """儲存試卷資訊到 exam_meta.json。"""
        try:
            merged = dict(self.DEFAULT_META)
            merged.update({k: str(v) for k, v in (meta or {}).items()})
            self.meta = merged
            with open(self.meta_path, "w", encoding="utf-8") as f:
                json.dump(self.meta, f, ensure_ascii=False, indent=2)
            return True, "試卷資訊已儲存！"
        except Exception as e:
            return False, f"試卷資訊存檔錯誤: {e}"

    def get_meta(self):
        """取得當前試卷資訊。"""
        return dict(self.meta)
