# -*- coding: utf-8 -*-
"""
OMR 核心處理模組（雙卡別版）
- card_mode = "OFFICIAL"：正式卡，沿用原本「上下水平錨線＋透視變換＋CSV模板」定位（一字未改）
- card_mode = "PRINTED" ：影印卡（B5 內容掃描在 A4），改用「左側 timing marks＋印刷答案框」定位

兩種模式共用同一套：填塗判定、學號解碼、計分(calculate_points)、畫圖(draw_score_on_img)、
回傳格式 (sid, answers, total_score), debug_img, status，因此 UI 與 Excel 邏輯完全不變。
"""

import cv2
import numpy as np
import pandas as pd
import os


class OMRProcessor:
    """OMR 核心處理器 - 負責答案卡辨識與計分"""

    def __init__(self, assets_dir, log_callback=None):
        self.assets_dir = assets_dir
        self.log_callback = log_callback
        self.identity_csv_path = os.path.join(assets_dir, 'omr_identity_template.csv')
        self.bubbles_csv_path = os.path.join(assets_dir, 'omr_bubbles_grid_perfect.csv')

        # 卡別模式：OFFICIAL（正式卡）/ PRINTED（影印卡）
        self.card_mode = "OFFICIAL"

        # ── 正式卡參數（原樣保留）──
        self.OLD_TEMPLATE_WIDTH = 1773.0
        self.NEW_TEMPLATE_WIDTH = 984.0
        self.REF_ANCHORS_984 = {
            "top_left": (65.0, 498.0), "top_right": (924.0, 498.0),
            "bottom_left": (65.0, 1342.0), "bottom_right": (924.0, 1342.0)
        }
        self.BUBBLE_RADIUS = 5
        self.BIN_TH_BUBBLE = 230
        self.FILL_THRESHOLD = 0.20

        # ── 影印卡參數（200dpi 校準；建議影印卡用 200dpi 渲染）──
        self.PRINTED_REF_W = 2338      # 校準時的影像寬度（200dpi）
        self.PRINTED_FILL_TH = 0.40    # 影印卡填塗門檻
        self.PRINTED_INK = 120         # 墨色判定（像素 < 此值算墨，舊比例法/ID用）
        self.PRINTED_DARK_TH = 80      # 影印卡答案填塗門檻：小窗(7x4)平均暗度(255-mean)
        # 答案 20 欄在「兩黑線四角」標準框(0-1000)內的相對 X（由舊批32頁校準，跨頁std<1.1px）
        # 偏淡掃描偵測不到氣泡框時，改用此幾何法從四角投影定欄（不依賴淡框偵測）
        self.PRINTED_CANON_U = [65.2, 97.9, 131.0, 163.5, 196.0,
                                327.3, 360.2, 393.0, 425.8, 458.6,
                                589.2, 621.6, 654.3, 687.3, 720.2,
                                850.5, 882.9, 915.5, 948.2, 980.7]
        # 學號 10 欄在「兩黑線四角」標準框內的相對 X（ID 區在線上方，v 取負）
        # 偏淡掃描 ID 框也偵測不到時，比照答案欄改幾何法（由舊批31頁校準，跨頁std<0.8px）
        self.ID_CANON_U = [261.0, 293.8, 326.5, 359.1, 391.8,
                           424.3, 457.3, 490.0, 522.8, 555.6]
        self.ID_CANON_V = -253.3   # ID 區代表性 canonical v（線上方；班級個位列），10 欄共用 x
        # 各 ID 列 canonical v（年級/班十/班個/座十/座個）；舊批32頁校準 std<1px
        # 偏淡批 timing 列不足時，列也用四角幾何投影（與答案氣泡同路線）
        self.ID_CANON_V_ROWS = [-320.1, -286.6, -252.9, -219.9, -186.1]

    def set_card_mode(self, mode):
        """設定卡別：'OFFICIAL'（正式卡錨線）/ 'PRINTED'（影印卡動態）/ 'OFFICIAL_DYN'（正式卡動態）"""
        if mode in ("OFFICIAL", "PRINTED", "OFFICIAL_DYN"):
            self.card_mode = mode

    def _log(self, message):
        if self.log_callback:
            self.log_callback(message)

    # ==================================================================
    # 正式卡定位（原樣保留，未改動）
    # ==================================================================
    def get_anchor_points(self, img, debug_img):
        h, w = img.shape[:2]
        scan_zones = [
            {"name": "TOP", "y_min": 0.25, "y_max": 0.49, "color": (0, 255, 0)},
            {"name": "BOTTOM", "y_min": 0.85, "y_max": 0.98, "color": (255, 0, 255)}
        ]
        detected_pts = {}
        for zone in scan_zones:
            y_start, y_end = int(h * zone["y_min"]), int(h * zone["y_max"])
            roi = img[y_start:y_end, :]
            if roi.size == 0:
                continue
            gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY) if len(roi.shape) == 3 else roi
            _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            line_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (w // 5, 1))
            lines = cv2.morphologyEx(thresh, cv2.MORPH_OPEN, line_kernel)
            contours, _ = cv2.findContours(lines, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            if contours:
                best_cnt = max(contours, key=cv2.contourArea)
                # cv2.fitLine 回傳 shape (4,1)；解包後每個是 shape (1,) 陣列。
                # numpy>=2.3 對 1 維陣列 float() 會報「only 0-dimensional arrays...」→ 先 flatten 取純量。
                _line = cv2.fitLine(best_cnt, cv2.DIST_L2, 0, 0.01, 0.01).flatten()
                vx, vy, x0, y0 = float(_line[0]), float(_line[1]), float(_line[2]), float(_line[3])
                slope = vy / vx if vx != 0 else 0
                cnt_xs = best_cnt[:, 0, 0]
                min_x, max_x = np.min(cnt_xs), np.max(cnt_xs)
                y_at_min = (slope * (min_x - x0)) + y0
                y_at_max = (slope * (max_x - x0)) + y0
                pt_start = (float(min_x), float(y_at_min + y_start))
                pt_end = (float(max_x), float(y_at_max + y_start))
                if zone["name"] == "TOP":
                    detected_pts["top_left"] = pt_start
                    detected_pts["top_right"] = pt_end
                else:
                    detected_pts["bottom_left"] = pt_start
                    detected_pts["bottom_right"] = pt_end
        return detected_pts if len(detected_pts) == 4 else None

    def apply_perspective_transform(self, detected_pts, csv_path):
        if not os.path.exists(csv_path):
            return pd.DataFrame()
        src_pts = np.float32([self.REF_ANCHORS_984[k] for k in ["top_left", "top_right", "bottom_left", "bottom_right"]])
        dst_pts = np.float32([detected_pts[k] for k in ["top_left", "top_right", "bottom_left", "bottom_right"]])
        M = cv2.getPerspectiveTransform(src_pts, dst_pts)
        df = pd.read_csv(csv_path)
        scale_factor = self.NEW_TEMPLATE_WIDTH / self.OLD_TEMPLATE_WIDTH
        original_coords = np.array([df['x'] * scale_factor, df['y'] * scale_factor]).T.reshape(-1, 1, 2).astype(np.float32)
        transformed_coords = cv2.perspectiveTransform(original_coords, M)
        df['img_x'] = transformed_coords[:, 0, 0]
        df['img_y'] = transformed_coords[:, 0, 1]
        return df

    # ==================================================================
    # 共用：學號解碼、計分
    # ==================================================================
    def decode_identity(self, filled_ids, mapping):
        data = {'Grade': '?', 'Class_10': '0', 'Class_1': '0', 'Seat_10': '0', 'Seat_1': '0'}
        for bid in filled_ids:
            if bid in mapping:
                cat, val = mapping[bid]
                data[cat] = str(val)
        cls = data['Class_10'] + data['Class_1']
        seat = data['Seat_10'] + data['Seat_1']
        if data['Grade'] == '?' and cls == '00':
            return "Unknown"
        return f"{data['Grade']}{cls.zfill(2)}{seat.zfill(2)}"

    def build_identity_map(self):
        if not os.path.exists(self.identity_csv_path):
            return {}
        df = pd.read_csv(self.identity_csv_path).sort_values(['y', 'x'])
        rows = []
        current_row = []
        if len(df) > 0:
            current_row.append(df.iloc[0].to_dict())
            for i in range(1, len(df)):
                if abs(df.iloc[i]['y'] - current_row[-1]['y']) > 20:
                    rows.append(current_row)
                    current_row = []
                current_row.append(df.iloc[i].to_dict())
            rows.append(current_row)
        mapping = {}
        row_defs = [('Grade', 1), ('Class_10', 0), ('Class_1', 0), ('Seat_10', 0), ('Seat_1', 0)]
        for i, row_bubbles in enumerate(rows):
            if i >= len(row_defs):
                break
            row_bubbles.sort(key=lambda k: k['x'])
            cat, start_v = row_defs[i]
            for idx, bub in enumerate(row_bubbles):
                mapping[bub['id']] = (cat, start_v + idx)
        return mapping

    def calculate_points(self, q_type, full_score, user_ans, key_ans, num_options=5, remark=""):
        if key_ans == "BONUS" or remark == "送分":
            return round(float(full_score), 2)
        if q_type == "STRICT" and remark == "容錯":
            valid_answers = list(key_ans)
            if user_ans in valid_answers:
                return round(float(full_score), 2)
            else:
                return 0.0
        set_u = set(user_ans)
        set_k = set(key_ans)
        diff_count = len(set_u ^ set_k)
        if diff_count == 0:
            return round(float(full_score), 2)
        if q_type == "STRICT" or q_type == "EXACT":
            return 0.0
        elif q_type == "GSAT":
            if diff_count == 1:
                return round(float(full_score) * 0.5, 2)
            else:
                return 0.0
        elif q_type == "NORMAL":
            n = max(1, int(num_options))
            deduction = float(full_score) * (2.0 / n)
            current_score = float(full_score) - (deduction * diff_count)
            return round(max(0.0, current_score), 2)
        return 0.0

    # ==================================================================
    # 影印卡定位（timing marks + 印刷答案框）
    # ==================================================================
    @staticmethod
    def _cluster(vals, gap):
        vals = np.sort(np.asarray(vals, float))
        groups, cur = [], [vals[0]]
        for v in vals[1:]:
            if v - cur[-1] > gap:
                groups.append(cur); cur = []
            cur.append(v)
        groups.append(cur)
        return groups

    def _printed_timing_bars(self, gray):
        _, th = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)
        n, _, stats, cent = cv2.connectedComponentsWithStats(th, 8)
        bars = []
        for i in range(1, n):
            x, y, bw, bh, area = stats[i]
            if 22 <= bw <= 70 and 6 <= bh <= 24 and area / (bw * bh + 1e-6) > 0.75 and area > 140:
                bars.append((cent[i][0], cent[i][1]))
        if not bars:
            return None, []
        from collections import Counter
        xs = np.array([b[0] for b in bars])
        cnt = Counter((xs // 25 * 25).astype(int))
        mainx = max(cnt, key=lambda k: cnt[k])
        col = sorted([b for b in bars if abs(b[0] - mainx) < 35], key=lambda b: b[1])
        return mainx, [b[1] for b in col]

    def _printed_grid(self, gray):
        """回傳 answer rows(25), answer cols(20), id rows(9), id cols(10)。失敗回 None。"""
        mainx, ys = self._printed_timing_bars(gray)
        if mainx is None or len(ys) < 25:
            return None
        # 分出學號列(前段)與答案列(大間隔之後25個)
        ans_rows, id_rows = ys[-25:], ys[:9]
        for i in range(len(ys)):
            if i > 0 and ys[i] - ys[i - 1] > 80:
                ans_rows = ys[i:]
                id_rows = ys[:i]
                break
        ans_rows = ans_rows[:25]
        # 2026/06/09：偏淡批掃描位移時答案列可能漏抓 1~3 條 timing→用等距內插補回
        if len(ans_rows) != 25:
            ans_rows = self._rebuild_even_rows(ans_rows, 25)
        if len(ans_rows) != 25:
            return None
        # 答案 20 欄：先試印刷框過濾分群(舊批/正常掃描走這條)
        band = gray[int(ans_rows[0]) - 20:int(ans_rows[-1]) + 20, 1270:2300]
        _, th = cv2.threshold(band, 140, 255, cv2.THRESH_BINARY_INV)
        cnts, _ = cv2.findContours(th, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        xs = []
        for c in cnts:
            x, y, bw, bh = cv2.boundingRect(c)
            if 22 <= bw <= 46 and 11 <= bh <= 24:
                xs.append(x + bw / 2 + 1270)
        ans_cols = [float(np.median(g)) for g in self._cluster(xs, 18) if len(g) >= 5] if xs else []
        # 2026/06/09：偏淡掃描的氣泡框灰階~200-235、任何門檻都湊不出 20 欄
        # → 改用兩黑線四角幾何投影定欄(欄位相對位置跨批極穩，誤差<3px)
        corners = None   # 兩黑線四角；答案欄/ID欄幾何回退共用，避免重算
        if len(ans_cols) != 20:
            corners = self._printed_border_corners(gray, ans_rows)
            if corners is None:
                return None
            ans_cols = self._printed_cols_from_corners(corners)
        if len(ans_cols) != 20:
            return None
        # 學號 10 欄：用完整 0-9 列(班個/座個/科個)定欄
        id_cols = []
        if len(id_rows) >= 5:
            full = [id_rows[2], id_rows[4]] + ([id_rows[7]] if len(id_rows) > 7 else [])
            ixs = []
            for cy in full:
                roi = gray[int(cy) - 10:int(cy) + 10, 1300:2050]
                _, t2 = cv2.threshold(roi, 140, 255, cv2.THRESH_BINARY_INV)
                cc, _ = cv2.findContours(t2, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
                for c in cc:
                    x, y, bw, bh = cv2.boundingRect(c)
                    if 22 <= bw <= 46 and 9 <= bh <= 24:
                        ixs.append(x + bw / 2 + 1300)
            if ixs:
                cols = [float(np.median(g)) for g in self._cluster(ixs, 18) if len(g) >= 2]
                id_cols = self._rebuild_even_cols(cols, 10)
        # 2026/06/09：偏淡掃描 ID 印刷框也偵測不到(同答案欄)→ 用兩黑線四角往上外推幾何定 10 欄
        # (ID 區在線上方 v<0；id_rows 仍由 timing 提供，故只補 id_cols)
        if len(id_cols) != 10:
            if corners is None:
                corners = self._printed_border_corners(gray, ans_rows)
            if corners is not None:
                id_cols = self._printed_id_cols_from_corners(corners)
        return ans_rows, ans_cols, id_rows, id_cols

    def _rebuild_even_cols(self, cols, n):
        """ID 欄位若偵測到 8~9 欄但跨幅符合 n 欄(等距)，用線性擬合補回缺格→回傳 n 欄；
        否則原樣回傳(交給守門判斷)。"""
        cols = sorted(float(c) for c in cols)
        if len(cols) >= n or len(cols) < 4:
            return cols[:n]
        diffs = np.diff(cols)
        mind = float(min(diffs))
        normal = [d for d in diffs if d < 1.6 * mind]
        sp = float(np.median(normal)) if normal else 0.0
        if sp <= 0:
            return cols
        idx = [int(round((c - cols[0]) / sp)) for c in cols]
        if idx[-1] != n - 1 or len(set(idx)) != len(idx):
            return cols   # 跨幅不符 n 欄 或 有重複索引 → 不重建
        a, b = np.polyfit(idx, cols, 1)
        return [float(a * i + b) for i in range(n)]

    def _rebuild_even_rows(self, rows, n=25):
        """timing 答案列漏偵測少數列時，用規則間距把缺列線性內插補回 n 列。
        2026/06/09：偏淡批 P17 因掃描位移，答案列中段漏抓 1 條 timing bar
        (留下約 2x 間距的缺口)，答案列只剩 24→定位失敗。
        本法：把各列對應到等距網格索引(缺列處索引跳號)，若跨幅剛好對應 n 列
        且無索引碰撞，就線性擬合重建全 n 列；否則原樣回傳交給守門判斷。
        只在缺 1-3 列時啟動，避免硬湊。全 69 頁驗證：P17 救回、其餘 68 頁不受影響。"""
        rows = sorted(float(r) for r in rows)
        if len(rows) >= n or len(rows) < n - 3:
            return rows[:n]
        diffs = np.diff(rows)
        base = float(np.median(diffs))
        if base <= 0:
            return rows
        idx = [0]
        for d in diffs:
            idx.append(idx[-1] + max(1, int(round(d / base))))
        if idx[-1] != n - 1 or len(set(idx)) != len(idx):
            return rows
        a, b = np.polyfit(idx, rows, 1)
        return [float(a * i + b) for i in range(n)]

    def _printed_border_corners(self, gray, ans_rows=None):
        """偵測答案格上下「連續黑色長框線」四角 (TL,TR,BL,BR)；失敗回 None。
        關鍵(老師指出)：答案格上下各有一條【連續不斷】的長橫黑線，是最長的兩條；
        作答區塊的框邊會被切成數段(較短)、表頭/說明框線也較短，皆自然排除。
        以這兩條連續線的四端做透視變換校正旋轉。(ans_rows 參數保留相容，未使用)
        2026/06/09：固定門檻 160 改 Otsu 自適應——偏淡掃描的黑線灰階約 170-200，
        固定 160 撈不到半條線(morphology 90,1 接不起來)，Otsu 依每頁對比自動定門檻。
        新舊兩批驗證：舊批 32/32 不退步、偏淡新批 68/69。"""
        bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
        hk = cv2.getStructuringElement(cv2.MORPH_RECT, (90, 1))
        hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk)
        cnts, _ = cv2.findContours(hor, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        L = []
        for c in cnts:
            x, y, ww, hh = cv2.boundingRect(c)
            if ww > 400 and hh <= 18:    # 高度放寬 14->18，納入較粗的連續框線(P05 框線高約16被舊值濾掉)
                p = c.reshape(-1, 2)
                xl = p[p[:, 0].argmin()]
                xr = p[p[:, 0].argmax()]
                L.append((ww, (float(xl[0]), float(xl[1])), (float(xr[0]), float(xr[1])), y))
        if len(L) < 2:
            return None
        L.sort(key=lambda d: -d[0])               # 取最長兩條連續線
        top, bot = sorted(L[:2], key=lambda d: d[3])   # 依 y 排：上、下
        # 幾何健檢：需夠寬且上下分離夠遠，否則視為失敗→回退 timing 法
        if (top[2][0] - top[1][0]) < 900 or (bot[3] - top[3]) < 800:
            return None
        return top[1], top[2], bot[1], bot[2]      # TL, TR, BL, BR

    def _printed_cols_from_corners(self, corners):
        """偏淡掃描備援：用兩黑線四角(TL,TR,BL,BR)把 20 欄的標準相對位置(PRINTED_CANON_U)
        投影回影像，回傳 20 個欄中心 X(取框中段 v=500)。框太淡偵測不到框時改用此法。"""
        TL, TR, BL, BR = corners
        WC, HC = 1000.0, 1000.0
        H = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [WC, 0], [0, HC], [WC, HC]]),
            np.float32([TL, TR, BL, BR]))

        def proj_x(u, v):
            p = H @ np.array([u, v, 1.0])
            return p[0] / p[2]

        return [proj_x(u, 500.0) for u in self.PRINTED_CANON_U]

    def _printed_id_cols_from_corners(self, corners):
        """偏淡掃描備援：ID 區在兩黑線上方，用四角 homography 往上外推(canonical v<0)
        投影 ID_CANON_U 得 10 個學號欄中心 X。各列共用同一組 x(跨列漂移<2.2px，在14px取樣窗內)。"""
        TL, TR, BL, BR = corners
        H = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [1000.0, 0], [0, 1000.0], [1000.0, 1000.0]]),
            np.float32([TL, TR, BL, BR]))

        def proj_x(u, v):
            p = H @ np.array([u, v, 1.0])
            return p[0] / p[2]

        return [proj_x(u, self.ID_CANON_V) for u in self.ID_CANON_U]

    def _printed_skew_centers(self, gray, ans_rows, ans_cols, corners):
        """以四角 homography 把每顆答案氣泡投影到實際位置（修正旋轉）。
        回傳 {(col,row):(cx,cy)}；失敗回 None。"""
        try:
            TL, TR, BL, BR = corners
            WC, HC = 1000.0, 1000.0
            H = cv2.getPerspectiveTransform(
                np.float32([[0, 0], [WC, 0], [0, HC], [WC, HC]]),
                np.float32([TL, TR, BL, BR]))
            Hinv = np.linalg.inv(H)

            def canon(x, y):
                p = Hinv @ np.array([x, y, 1.0])
                return p[0] / p[2], p[1] / p[2]

            def proj(u, v):
                p = H @ np.array([u, v, 1.0])
                return p[0] / p[2], p[1] / p[2]

            # 欄 u：ans_cols 是答案帶「中段」的中位 X，故對應到中段 y 取 u（用 topY 會隨旋轉產生水平偏移）
            midY = (ans_rows[0] + ans_rows[-1]) / 2.0
            us = [canon(x, midY)[0] for x in ans_cols]       # 欄：X 準（印刷框，中段 y 對應）
            vs = [canon(TL[0], y)[1] for y in ans_rows]      # 列：左側 timing 準
            centers = {}
            for cc in range(4):
                for rr in range(25):
                    for oo in range(5):
                        centers[(cc * 5 + oo, rr)] = proj(us[cc * 5 + oo], vs[rr])
            return centers
        except Exception:
            return None

    def _printed_dark(self, gray, cx, cy, rw=11, rh=6):
        p = gray[int(cy) - rh:int(cy) + rh, int(cx) - rw:int(cx) + rw]
        return float(np.mean(p < self.PRINTED_INK)) if p.size else 0.0

    def _printed_fill_score(self, gray, cx, cy, rw=7, rh=4):
        """填塗強度＝小窗『平均暗度』(255-mean)。
        小窗(14x8)避開氣泡上下印刷框線→空白接近全白(暗度~20)；
        平均能抓到淡塗(暗度~110)，比『比例<墨值』對淡鉛筆敏感得多。"""
        p = gray[int(cy) - rh:int(cy) + rh, int(cx) - rw:int(cx) + rw]
        return (255.0 - float(p.mean())) if p.size else 0.0

    def _process_printed(self, img_array, filename, q_config, ans_key):
        img = img_array.copy()
        h, w = img.shape[:2]
        debug_img = img.copy()
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img

        grid = self._printed_grid(gray)
        if grid is None:
            return None, debug_img, "Locate Fail"
        ans_rows, ans_cols, id_rows, id_cols = grid
        OPTS = ['A', 'B', 'C', 'D', 'E']
        TH = self.PRINTED_FILL_TH

        # ── 兩線透視校正：偵測答案格上下框線四角，修正旋轉造成的右側歪斜 ──
        corners = self._printed_border_corners(gray, ans_rows)
        skew_centers = None
        if corners is not None:
            skew_centers = self._printed_skew_centers(gray, ans_rows, ans_cols, corners)

        # ── 讀答案 + 畫圖（風格比照正式卡）──
        answers = {}
        for c in range(4):
            for r in range(25):
                q_no = c * 25 + r + 1
                cfg = q_config.get(q_no, {})
                q_type = cfg.get('type', 'STRICT')
                correct_ans = str(ans_key.get(q_no, ""))
                box_color = (227, 140, 184) if q_type in ['GSAT', 'NORMAL'] else (0, 255, 0)
                for o in range(5):
                    col = c * 5 + o
                    if skew_centers is not None:                 # 透視校正中心
                        cx, cy = skew_centers[(col, r)]
                    else:                                        # 後備：原 timing 列 + 框欄
                        cx, cy = ans_cols[col], ans_rows[r]
                    filled = self._printed_fill_score(gray, cx, cy) > self.PRINTED_DARK_TH
                    if OPTS[o] in correct_ans and correct_ans != "BONUS":
                        cv2.rectangle(debug_img, (int(cx) - 12, int(cy) - 8), (int(cx) + 12, int(cy) + 8), box_color, 2)
                    draw_color = (0, 0, 255) if filled else (255, 0, 0)
                    cv2.circle(debug_img, (int(cx), int(cy)), self.BUBBLE_RADIUS, draw_color, 2 if filled else 1)
                    if filled:
                        answers[q_no] = answers.get(q_no, "") + OPTS[o]

        # ── 疊上定位框線＋四角（驗收用，沿用討論時的配色）──
        if corners is not None:
            TLp, TRp, BLp, BRp = corners
            cv2.line(debug_img, (int(TLp[0]), int(TLp[1])), (int(TRp[0]), int(TRp[1])), (0, 0, 255), 2)
            cv2.line(debug_img, (int(BLp[0]), int(BLp[1])), (int(BRp[0]), int(BRp[1])), (0, 0, 255), 2)
            for pt in corners:
                cv2.circle(debug_img, (int(pt[0]), int(pt[1])), 14, (19, 69, 139), 3)

        # ── 學號解碼（年級+班級+座號，5碼，與正式卡同格式）──
        sid = self._printed_decode_id(gray, id_rows, id_cols, debug_img, corners)

        # ── 計分（與正式卡共用同一段邏輯）──
        total_score = 0.0
        part_summary = {}
        for q_no, key in ans_key.items():
            cfg = q_config.get(q_no, {'type': 'STRICT', 'score': 0.0, 'part': 'Part1', 'options': 5})
            p_name = cfg.get('part', 'Part1')
            q_type = cfg.get('type', 'STRICT')
            full_pts = float(cfg['score'])
            n_opts = int(cfg.get('options', 5))
            remark = cfg.get('remark', "")
            if p_name not in part_summary:
                part_summary[p_name] = {'earned': 0.0, 'full': 0.0}
            part_summary[p_name]['full'] += full_pts
            u_ans = "".join(sorted(answers.get(q_no, "")))
            c_ans = "".join(sorted(str(key)))
            earned = self.calculate_points(q_type, full_pts, u_ans, c_ans, num_options=n_opts, remark=remark)
            part_summary[p_name]['earned'] += earned
            total_score += earned
        total_score = round(total_score, 2)
        for p in part_summary:
            part_summary[p]['earned'] = round(part_summary[p]['earned'], 2)
            part_summary[p]['full'] = round(part_summary[p]['full'], 2)

        self.draw_score_on_img(debug_img, sid, part_summary, total_score)
        return (sid, answers, total_score), debug_img, "Success"

    def _printed_decode_id(self, gray, id_rows, id_cols, debug_img, corners=None):
        """讀年級(1-3)、班級十/個、座號十/個，回傳 5 碼 grade+class+seat。
        2026/06/09 改：每格位置一律先求出來再畫圈，ID 圈與答案氣泡一樣 100% 出現
        （劃了就讀得到、沒劃才 Unknown），不再因 timing 漏抓而整片空白。
        定位優先序：
          ① timing 充足(id_rows>=5 且 id_cols==10)：列用 timing、欄用印刷框/幾何欄——最準，維持原準度
          ② timing 不足但有兩黑線四角：列(ID_CANON_V_ROWS)+欄(ID_CANON_U)都用四角幾何投影
        註：ID 區在兩線上方屬外插，準度略低於 timing，故只當後備；偏淡掃描位移會被外插放大。"""
        TH = self.PRINTED_DARK_TH   # ID 區與答案區共用：小窗平均暗度門檻
        ID_Y_OFF = 3                # timing 列比 ID 氣泡中心高約 3px，往下補

        use_timing = (len(id_rows) >= 5 and len(id_cols) >= 10)
        H = None
        if not use_timing:
            if corners is None:
                return "Unknown"    # 既無 timing 又無四角（極罕見）→ 無法定位
            TL, TR, BL, BR = corners
            H = cv2.getPerspectiveTransform(
                np.float32([[0, 0], [1000.0, 0], [0, 1000.0], [1000.0, 1000.0]]),
                np.float32([TL, TR, BL, BR]))

        def cell(k, d):
            """第 k 列(0年級..4座個)、第 d 欄(0-9) 的氣泡中心 (x, y)。"""
            if use_timing:
                return id_cols[d], id_rows[k] + ID_Y_OFF
            p = H @ np.array([self.ID_CANON_U[d], self.ID_CANON_V_ROWS[k], 1.0])
            return p[0] / p[2], p[1] / p[2] + ID_Y_OFF

        def draw(x, y, filled):
            cv2.circle(debug_img, (int(x), int(y)), self.BUBBLE_RADIUS,
                       (0, 165, 255) if filled else (255, 0, 255), 2 if filled else 1)

        # ID 列每列只會劃一格：改用「相對判定」取代死門檻——
        # 劃記格暗度遠高於其他格(偏淡掃描仍 75~95，未劃 ~10)，取最深且需明顯勝過第二名。
        # 解決：偏淡的「0」暗度 75~77 差幾分沒過 80 門檻被誤判沒劃 → ID 整欄歸零(如 10000)。
        ID_FLOOR = 40.0   # 絕對下限（容忍偏淡掃描）
        ID_DOM = 2.0      # 最深需 ≥ 第二名的倍數（空白列各格相近 → 判為沒劃）

        def _id_marked(vals):
            srt = sorted(vals, reverse=True)
            best_v = srt[0]
            second_v = srt[1] if len(srt) > 1 else 0.0
            return best_v >= ID_FLOOR and best_v >= second_v * ID_DOM

        def digit(k):
            vals = [self._printed_fill_score(gray, *cell(k, d)) for d in range(10)]
            best = int(np.argmax(vals))
            ok = _id_marked(vals)
            for d in range(10):
                x, y = cell(k, d)
                draw(x, y, d == best and ok)
            return best if ok else None

        # 年級：列0 的欄1/2/3 → 年級1/2/3，相對判定取最深並畫圈
        grade = '?'
        gvals = {d: self._printed_fill_score(gray, *cell(0, d)) for d in (1, 2, 3)}
        gb = max(gvals, key=gvals.get)
        g_ok = _id_marked(list(gvals.values()))
        for d in (1, 2, 3):
            x, y = cell(0, d)
            draw(x, y, d == gb and g_ok)
        if g_ok:
            grade = str(gb)
        c10, c1 = digit(1), digit(2)
        s10, s1 = digit(3), digit(4)
        cls = (f"{c10}{c1}" if None not in (c10, c1) else "??")
        seat = (f"{s10}{s1}" if None not in (s10, s1) else "??")
        if grade == '?' and cls == '??':
            return "Unknown"
        g = grade if grade != '?' else '0'
        cls = cls if cls != '??' else '00'
        seat = seat if seat != '??' else '00'
        return f"{g}{cls.zfill(2)}{seat.zfill(2)}"

    # ==================================================================
    # 正式卡-動態定位版（OFFICIAL_DYN）：把影印卡的動態定位回套正式卡
    # ==================================================================
    def _process_official_dynamic(self, img_array, filename, q_config, ans_key):
        """正式卡-動態定位版（OFFICIAL_DYN）：把影印卡的動態定位回套正式卡。
        同款卡(ANS93002-7A)，以卡片自身特徵定位，與卡在頁面的大小/位置無關：
          ① 左側 timing 黑條 → 25 答案列、ID 列
          ② 答案格上下兩條連續黑框線四角 → homography
          ③ PRINTED_CANON_U / ID_CANON 相對座標投影回影像（同款卡相對幾何一致）
        像素門檻隨影像寬度自適應(REFW=1166=正式卡200dpi寬)，200dpi/4x 皆驗證 33/33。
        填塗、計分、畫圖、回傳格式與正式/影印兩模式共用；OFFICIAL/PRINTED 兩路一字不動。"""
        img = img_array.copy()
        h, w = img.shape[:2]
        debug_img = img.copy()
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
        s = w / 1166.0   # 自適應縮放係數（正式卡 200dpi 寬=1166 為基準）
        TH = self.PRINTED_DARK_TH
        # 正式卡專屬校準值（由正式卡樣本實測印刷框中心反推 canonical 座標，不與影印卡共用）
        OFFDYN_CANON_U = [65.7, 98.7, 131.7, 164.2, 197.0, 327.7, 360.3, 393.0, 425.7, 458.4,
                          589.1, 621.5, 654.1, 686.8, 719.3, 849.5, 882.2, 914.7, 947.2, 979.8]
        OFFDYN_ID_U = [262.8, 295.2, 327.7, 360.0, 392.7, 425.3, 458.0, 490.9, 523.5, 555.9]
        OFFDYN_ID_V = [-321.6, -288.5, -255.1, -221.6, -188.2]
        ANS_V_OFF = 2.2   # 答案列：timing 列中心比印刷框中心低約此 canonical 量，往上修正置中
        ANS_Y_RECENTER = 2.5   # V5.0：投影後再往下校正系統性垂直偏移(×s 像素)，讓取樣窗與綠框對準氣泡中心。
        #                        實測 demo：未校正時有墨氣泡最深處比取樣點低中位 +2~3px；2.5 讓殘餘≈0、多撿回約3%邊緣塗記，
        #                        且純垂直小位移不會跳到隔壁格→零誤判風險。不動門檻、不做 snap。

        # ── 內部工具（自適應；不依賴影印卡那些假設右半邊的寫死範圍）──
        def _cluster(vals, gap):
            vals = np.sort(np.asarray(vals, float)); g = []; cur = [vals[0]]
            for v in vals[1:]:
                if v - cur[-1] > gap: g.append(cur); cur = []
                cur.append(v)
            g.append(cur); return g

        def _timing_bars():
            th = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY_INV)[1]
            n, _, stats, cent = cv2.connectedComponentsWithStats(th, 8)
            bars = []
            for i in range(1, n):
                x, y, bw, bh, area = stats[i]
                if 8*s <= bw <= 60*s and 4*s <= bh <= 20*s and area/(bw*bh+1e-6) > 0.7 and area > 40*s*s:
                    bars.append((cent[i][0], cent[i][1]))
            if not bars: return None, []
            from collections import Counter
            xs = np.array([b[0] for b in bars])
            cnt = Counter((xs // (20*s) * (20*s)).astype(int))
            mainx = max(cnt, key=lambda k: cnt[k])
            col = sorted([b for b in bars if abs(b[0]-mainx) < 35*s], key=lambda b: b[1])
            return mainx, [b[1] for b in col]

        def _border_corners():
            bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)[1]
            hk = cv2.getStructuringElement(cv2.MORPH_RECT, (max(10, int(90*s)), 1))
            hor = cv2.morphologyEx(bw, cv2.MORPH_OPEN, hk)
            cnts, _ = cv2.findContours(hor, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
            L = []
            for c in cnts:
                x, y, ww, hh = cv2.boundingRect(c)
                if ww > w * 0.35 and hh <= 22*s:
                    p = c.reshape(-1, 2); xl = p[p[:, 0].argmin()]; xr = p[p[:, 0].argmax()]
                    L.append((ww, (float(xl[0]), float(xl[1])), (float(xr[0]), float(xr[1])), y))
            if len(L) < 2: return None
            L.sort(key=lambda d: -d[0])
            top, bot = sorted(L[:2], key=lambda d: d[3])
            if (top[2][0]-top[1][0]) < w*0.35 or (bot[3]-top[3]) < h*0.3: return None
            return top[1], top[2], bot[1], bot[2]

        def _fill(cx, cy):
            # V5.1「框內最深區」：用小窗(5s×3s)在框內內縮範圍滑動取最大暗度，
            # 對 partial fill(沒塗滿/塗偏)敏感；滑動範圍小且框定在格內，不會跳到隔壁或抓框線。
            # 沙箱 demo 驗證：空白格最深仍<70(<80門檻零誤判)、答案區純增不減、修正多筆淡塗學號。
            # 答案區與學號區共用此函式，故兩邊一起受惠。
            rw = max(2, int(round(5*s))); rh = max(1, int(round(3*s)))
            best = 0.0
            for ddx in (-5, -2.5, 0, 2.5, 5):
                for ddy in (-3, 0, 3):
                    x = int(cx + ddx*s); y = int(cy + ddy*s)
                    p = gray[y-rh:y+rh, x-rw:x+rw]
                    if p.size:
                        v = 255.0 - float(p.mean())
                        if v > best: best = v
            return best

        # ── 定位 ──
        mainx, ys = _timing_bars()
        if mainx is None or len(ys) < 25:
            return None, debug_img, "Locate Fail (timing<25)"
        ans_rows, id_rows = ys[-25:], ys[:9]
        for i in range(len(ys)):
            if i > 0 and ys[i] - ys[i-1] > 60*s:
                ans_rows = ys[i:]; id_rows = ys[:i]; break
        ans_rows = ans_rows[:25]
        if len(ans_rows) != 25:
            ans_rows2 = self._rebuild_even_rows(ans_rows, 25)
            ans_rows = ans_rows2 if len(ans_rows2) == 25 else ans_rows
        if len(ans_rows) != 25:
            return None, debug_img, "Locate Fail (rows=%d)" % len(ans_rows)
        corners = _border_corners()
        if corners is None:
            return None, debug_img, "Locate Fail (no corners)"
        TL, TR, BL, BR = corners
        Hbox = cv2.getPerspectiveTransform(
            np.float32([[0, 0], [1000, 0], [0, 1000], [1000, 1000]]),
            np.float32([TL, TR, BL, BR]))
        Hinv = np.linalg.inv(Hbox)

        def _proj(u, v):
            p = Hbox @ np.array([u, v, 1.0]); return p[0]/p[2], p[1]/p[2]

        def _canon_v(x, y):
            p = Hinv @ np.array([x, y, 1.0]); return p[1]/p[2]

        # ── 讀答案 + 畫圖（風格比照其他模式）──
        OPTS = ['A', 'B', 'C', 'D', 'E']
        answers = {}
        for c in range(4):
            for r in range(25):
                q_no = c * 25 + r + 1
                cfg = q_config.get(q_no, {})
                q_type = cfg.get('type', 'STRICT')
                correct_ans = str(ans_key.get(q_no, ""))
                box_color = (227, 140, 184) if q_type in ['GSAT', 'NORMAL'] else (0, 255, 0)
                vrow = _canon_v(TL[0], ans_rows[r]) - ANS_V_OFF
                for o in range(5):
                    col = c * 5 + o
                    cx, cy = _proj(OFFDYN_CANON_U[col], vrow)
                    cy += ANS_Y_RECENTER * s   # V5.0 取樣對準
                    filled = _fill(cx, cy) > TH
                    if OPTS[o] in correct_ans and correct_ans != "BONUS":
                        cv2.rectangle(debug_img, (int(cx)-12, int(cy)-8), (int(cx)+12, int(cy)+8), box_color, 2)
                    draw_color = (0, 0, 255) if filled else (255, 0, 0)
                    cv2.circle(debug_img, (int(cx), int(cy)), self.BUBBLE_RADIUS, draw_color, 2 if filled else 1)
                    if filled:
                        answers[q_no] = answers.get(q_no, "") + OPTS[o]

        # ── 疊框線四角（驗收用）──
        cv2.line(debug_img, (int(TL[0]), int(TL[1])), (int(TR[0]), int(TR[1])), (0, 0, 255), 2)
        cv2.line(debug_img, (int(BL[0]), int(BL[1])), (int(BR[0]), int(BR[1])), (0, 0, 255), 2)
        for pt in corners:
            cv2.circle(debug_img, (int(pt[0]), int(pt[1])), 14, (19, 69, 139), 3)

        # ── 學號解碼（年級+班級+座號，5碼，四角幾何投影）──
        ID_Y_OFF = 2.0 * s   # V5.1：學號氣泡系統性偏上，往下校正對齊框中心。
        #                      沙箱 demo 量測有墨 ID 格最佳垂直位移中位數=+2（×s 像素，200dpi=2px/4x≈2.9px），分布集中於 2。
        def _idcell(k, d):
            p = Hbox @ np.array([OFFDYN_ID_U[d], OFFDYN_ID_V[k], 1.0])
            return p[0]/p[2], p[1]/p[2] + ID_Y_OFF
        def _iddraw(x, y, fl):
            cv2.circle(debug_img, (int(x), int(y)), self.BUBBLE_RADIUS,
                       (0, 165, 255) if fl else (255, 0, 255), 2 if fl else 1)
        def _digit(k):
            vals = []
            for d in range(10):
                x, y = _idcell(k, d); v = _fill(x, y); vals.append(v); _iddraw(x, y, v > TH)
            best = int(np.argmax(vals))
            return best if vals[best] > TH else None
        grade = '?'; gvals = {}
        for d in (1, 2, 3):
            x, y = _idcell(0, d); gvals[d] = _fill(x, y); _iddraw(x, y, gvals[d] > TH)
        gb = max(gvals, key=gvals.get)
        if gvals[gb] > TH: grade = str(gb)
        c10, c1 = _digit(1), _digit(2)
        s10, s1 = _digit(3), _digit(4)
        cls = (f"{c10}{c1}" if None not in (c10, c1) else "??")
        seat = (f"{s10}{s1}" if None not in (s10, s1) else "??")
        if grade == '?' and cls == '??':
            sid = "Unknown"
        else:
            g = grade if grade != '?' else '0'
            cls = cls if cls != '??' else '00'
            seat = seat if seat != '??' else '00'
            sid = f"{g}{cls.zfill(2)}{seat.zfill(2)}"

        # ── 計分（與其他模式共用同一段邏輯）──
        total_score = 0.0
        part_summary = {}
        for q_no, key in ans_key.items():
            cfg = q_config.get(q_no, {'type': 'STRICT', 'score': 0.0, 'part': 'Part1', 'options': 5})
            p_name = cfg.get('part', 'Part1')
            q_type = cfg.get('type', 'STRICT')
            full_pts = float(cfg['score'])
            n_opts = int(cfg.get('options', 5))
            remark = cfg.get('remark', "")
            if p_name not in part_summary:
                part_summary[p_name] = {'earned': 0.0, 'full': 0.0}
            part_summary[p_name]['full'] += full_pts
            u_ans = "".join(sorted(answers.get(q_no, "")))
            c_ans = "".join(sorted(str(key)))
            earned = self.calculate_points(q_type, full_pts, u_ans, c_ans, num_options=n_opts, remark=remark)
            part_summary[p_name]['earned'] += earned
            total_score += earned
        total_score = round(total_score, 2)
        for p in part_summary:
            part_summary[p]['earned'] = round(part_summary[p]['earned'], 2)
            part_summary[p]['full'] = round(part_summary[p]['full'], 2)

        self.draw_score_on_img(debug_img, sid, part_summary, total_score)
        return (sid, answers, total_score), debug_img, "Success"

    # ==================================================================
    # 主入口：依卡別分流
    # ==================================================================
    def process_image(self, img_array, filename, id_map, q_config, ans_key):
        if self.card_mode == "OFFICIAL_DYN":
            return self._process_official_dynamic(img_array, filename, q_config, ans_key)
        if self.card_mode == "PRINTED":
            return self._process_printed(img_array, filename, q_config, ans_key)

        # ───────── 以下為正式卡原樣流程（未改動）─────────
        img = img_array.copy()
        h, w = img.shape[:2]
        debug_img = img.copy()

        anchors = self.get_anchor_points(img, debug_img)
        if anchors is None:
            return None, debug_img, "Anchor Fail"

        try:
            df_id = self.apply_perspective_transform(anchors, self.identity_csv_path)
            df_ans = self.apply_perspective_transform(anchors, self.bubbles_csv_path)
        except Exception as e:
            return None, debug_img, f"Transform Fail: {e}"

        id_results = []
        answers = {}

        for df, mode in [(df_id, "ID"), (df_ans, "ANS")]:
            if df.empty:
                continue
            for _, row in df.iterrows():
                fx, fy = int(row['img_x']), int(row['img_y'])
                if fx < 5 or fx >= w - 5 or fy < 5 or fy >= h - 5:
                    continue
                roi = img[fy - 5:fy + 5, fx - 5:fx + 5]
                filled = False
                if roi.size > 0:
                    if (np.sum(roi[:,:,0] < self.BIN_TH_BUBBLE) / roi.size) > self.FILL_THRESHOLD:
                        filled = True

                if mode == "ANS":
                    q_no, opt = row['q_no'], row['option']
                    cfg = q_config.get(q_no, {})
                    q_type = cfg.get('type', 'STRICT')
                    
                    box_color = (227, 140, 184) if q_type in ['GSAT', 'NORMAL'] else (0, 255, 0)
                    correct_ans = str(ans_key.get(q_no, ""))
                    
                    if opt in correct_ans and correct_ans != "BONUS":
                        cv2.rectangle(debug_img, (fx-9, fy-9), (fx+9, fy+9), box_color, 2)
                    
                    draw_color = (0, 0, 255) if filled else (255, 0, 0)
                    cv2.circle(debug_img, (fx, fy), self.BUBBLE_RADIUS, draw_color, 2 if filled else 1)
                    if filled: 
                        answers[q_no] = answers.get(q_no, "") + opt
                else:
                    draw_color = (0, 165, 255) if filled else (255, 0, 255)
                    cv2.circle(debug_img, (fx, fy), self.BUBBLE_RADIUS, draw_color, 2 if filled else 1)
                    if filled: 
                        id_results.append(row['id'])

        # 解碼學號
        sid = self.decode_identity(id_results, id_map)
        
        # 計算分數
        total_score = 0.0
        part_summary = {}

        for q_no, key in ans_key.items():
            cfg = q_config.get(q_no, {'type': 'STRICT', 'score': 0.0, 'part': 'Part1', 'options': 5})
            p_name = cfg.get('part', 'Part1')
            q_type = cfg.get('type', 'STRICT')
            full_pts = float(cfg['score'])
            n_opts = int(cfg.get('options', 5))
            remark = cfg.get('remark', "")
            
            if p_name not in part_summary: 
                part_summary[p_name] = {'earned': 0.0, 'full': 0.0}
            part_summary[p_name]['full'] += full_pts
            
            u_ans = "".join(sorted(answers.get(q_no, "")))
            c_ans = "".join(sorted(str(key)))
            
            earned = self.calculate_points(q_type, full_pts, u_ans, c_ans, num_options=n_opts, remark=remark)
            
            part_summary[p_name]['earned'] += earned
            total_score += earned

        # 四捨五入
        total_score = round(total_score, 2)
        for p in part_summary:
            part_summary[p]['earned'] = round(part_summary[p]['earned'], 2)
            part_summary[p]['full'] = round(part_summary[p]['full'], 2)

        # 在影像上繪製分數
        self.draw_score_on_img(debug_img, sid, part_summary, total_score)
        
        return (sid, answers, total_score), debug_img, "Success"

    def draw_score_on_img(self, img, sid, part_summary, total_score):
        """在影像右上角繪製學號與分數"""
        h, w = img.shape[:2]
        curr_y = 45
        right_margin = 350
        cv2.putText(img, f"ID: {sid}", (w - right_margin, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        curr_y += 20
        cv2.putText(img, "-----------", (w - right_margin, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        for p_name in sorted(part_summary.keys()):
            curr_y += 35
            e, f = part_summary[p_name]['earned'], part_summary[p_name]['full']
            cv2.putText(img, f"{p_name}: {e:g}/{f:g}", (w - right_margin, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        curr_y += 20
        cv2.putText(img, "-----------", (w - right_margin, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        curr_y += 40
        total_full = sum(v['full'] for v in part_summary.values())
        cv2.putText(img, f"Total: {total_score:g}/{total_full:g}", (w - right_margin, curr_y), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (0, 0, 255), 3)
