# -*- coding: utf-8 -*-
"""
班級成績表分頁產生器（比照讀卡機輸出格式）。

提供 build_class_grade_sheet()：在既有 workbook 中，為一個班級新增一個
「班級成績表」分頁，內容包含：題號尺規、標準答案列、各生作答（代碼壓縮、
答對以「.」表示、空白以「=」表示）、選擇/非選/合計成績、班級名次、
五標統計、配分資料、代碼說明。

數值（選擇成績/合計）來自讀卡系統自身的計分結果。
"""
import math
from openpyxl.styles import Font, Alignment, Border, Side

# ── 複選組合 → 代碼（完全比照讀卡機代碼表）──
COMBO2CODE = {
    "AB": "F", "AC": "G", "AD": "H", "AE": "I", "BC": "J", "BD": "K", "BE": "L",
    "CD": "M", "CE": "N", "DE": "O",
    "ABC": "P", "ABD": "Q", "ABE": "R", "ACD": "S", "ACE": "T", "ADE": "U",
    "BCD": "V", "BCE": "W", "BDE": "X", "CDE": "Y",
    "ABCD": "Z", "ABCE": "*", "ABDE": "$", "ACDE": "%", "BCDE": "<", "ABCDE": "#",
}
BLANK = "="   # 空白
SAME = "."    # 與標準答案相同（ASCII 句點，比照讀卡機資料格）
MULTI = "?"   # 單選多畫記 / 超出組合範圍

FONT = "細明體"
TYPE_ZH = {"STRICT": "單選    ", "EXACT": "複選    ", "GSAT": "學測多選",
           "NORMAL": "一般多選", "NONE": "未計分  "}

LEGEND = [
    "答案代碼說明:F:AB   /G:AC   /H:AD   /I:AE   /J:BC   /K:BD    /L:BE  /M:CD  /N:CE  /O:DE ",
    "　　　　　　 P:ABC  /Q:ABD  /R:ABE  /S:ACD  /T:ACE  /U:ADE   /V:BCD /W:BCE /X:BDE /Y:CDE",
    "　　　　　　 Z:ABCD /*:ABCE /$:ABDE /%:ACDE /<:BCDE /#:ABCDE /=:空白",
    "　　　　　　 設定單選題的狀況下，如果讀到2個或2個以上畫記時會以\" ? \"呈現",
    "　　　　　　 設定複選或選填題的狀況下，如果讀到畫記組合超過組合範圍時會以\" ? \"呈現",
    "學生答案與標準答案相同者，以\"．\"表示,特殊答案:s:送分 n:不計分",
    "以上答案代碼僅適用於選項A-E之複選或多選題;較詳細的答案代碼及頂,前,均,後,底標數據說明,請參考複選答案代碼表.",
]


def norm_set(ans):
    """作答字串 → 排序後大寫字串（只保留 A-E），如 'b a' → 'AB'。"""
    if ans is None:
        return ""
    return "".join(sorted(set(c.upper() for c in str(ans) if c.upper() in "ABCDE")))


def encode_answer(ans_set):
    """單題作答 → 代碼字元（給標準答案列用，不比對）。"""
    s = norm_set(ans_set)
    if s == "":
        return BLANK
    if len(s) == 1:
        return s
    return COMBO2CODE.get(s, MULTI)


def encode_answer_or_bonus(raw):
    """標準答案列用：送分(BONUS)顯示 's'，否則一般編碼。"""
    if str(raw).upper() == "BONUS":
        return "s"
    return encode_answer(raw)


def encode_student_cell(stu_ans, correct_ans):
    """學生單題 → 顯示字元：送分'.'、相同'.'、空白'='、否則代碼。"""
    if str(correct_ans).upper() == "BONUS":
        return SAME  # 送分題：每人視為答對
    su = norm_set(stu_ans)
    co = norm_set(correct_ans)
    if su == co and co != "":
        return SAME
    if su == "":
        return BLANK
    if su == co:
        return SAME
    if len(su) == 1:
        return su
    return COMBO2CODE.get(su, MULTI)


def build_ruler(n):
    """題號尺規兩列（十位/個位），每 10 題一組空格分隔。回傳 (tens, units)。"""
    units, tens = [], []
    for q in range(1, n + 1):
        units.append(str(q % 10))
        tens.append(str(q // 10) if (q % 10 == 0) else " ")
        if q % 10 == 0 and q != n:
            units.append(" ")
            tens.append(" ")
    return "".join(tens), "".join(units)


def build_answer_string(per_q_chars, n):
    """逐題字元 list → 分組字串（每 10 題空格分隔）。"""
    out = []
    for i, ch in enumerate(per_q_chars):
        out.append(ch)
        if (i + 1) % 10 == 0 and (i + 1) != n:
            out.append(" ")
    return "".join(out)


def five_marks(scores):
    """五標：由高到低排序，取第 floor(n*p)+1 名（1-indexed）。p=12/25/50/75/88%。"""
    n = len(scores)
    if n == 0:
        return {"頂": 0, "前": 0, "均": 0, "後": 0, "底": 0}
    sd = sorted(scores, reverse=True)

    def at(p):
        return sd[min(math.floor(n * p), n - 1)]
    return {"頂": at(0.12), "前": at(0.25), "均": at(0.50), "後": at(0.75), "底": at(0.88)}


def pop_std(scores):
    """母體標準差。"""
    n = len(scores)
    if n == 0:
        return 0.0
    m = sum(scores) / n
    return math.sqrt(sum((x - m) ** 2 for x in scores) / n)


def _blocks(q_nos, q_config):
    """連續同 (type,score,options) 題目併成大題區塊。"""
    blocks, cur = [], None
    for q in q_nos:
        cfg = q_config.get(q, {})
        key = (cfg.get('type', 'STRICT'), float(cfg.get('score', 0)), int(cfg.get('options', 5)))
        if cur and cur['key'] == key and q == cur['end'] + 1:
            cur['end'] = q
        else:
            if cur:
                blocks.append(cur)
            cur = {'key': key, 'start': q, 'end': q}
    if cur:
        blocks.append(cur)
    return blocks


def _f(size=9, bold=False):
    return Font(name=FONT, size=size, bold=bold)


def class_label_from_code(ban_code):
    """班級碼3碼 → 標題：首碼=年級、後2碼=班號。如 '105' → '1年級05班'。"""
    s = str(ban_code)
    if len(s) >= 3 and s[:1].isdigit():
        return f"{s[0]}年級{s[1:3]}班"
    return f"{s}班"


def build_title_line(meta):
    """由 meta 組第1列表頭。"""
    school = meta.get("學校", "").strip()
    year = meta.get("學年度", "").strip()
    term = meta.get("學期", "").strip()
    seq = meta.get("次數", "").strip()
    parts = []
    if school:
        parts.append(school)
    if year:
        parts.append(f"{year}學年度")
    if term:
        parts.append(f"第{term}學期")
    if seq:
        parts.append(f"第{seq}次定期評量")
    return "  ".join(parts) if parts else "班級成績表"


def build_class_grade_sheet(wb, ban_code, students, ans_key, q_config, meta):
    """
    在 wb 新增一個班級成績表分頁。

    ban_code : 班級碼（如 '105'），用來推班級標題
    students : list of dict {'座號','姓名','選擇','非選','answers':{q:作答字串}}
    ans_key  : {q: 正解字串}
    q_config : {q: {type,score,options,part}}
    meta     : {'學校','學年度','學期','次數','科目'}
    回傳 worksheet
    """
    q_nos = sorted(ans_key.keys(), key=lambda x: int(x))
    N = len(q_nos)
    subject = meta.get("科目", "").strip()
    class_label = class_label_from_code(ban_code)

    title = f"{class_label}班級成績表"
    sheet_title = title[:31]
    base = sheet_title
    k = 1
    while sheet_title in wb.sheetnames:
        k += 1
        sheet_title = f"{base[:28]}_{k}"
    ws = wb.create_sheet(title=sheet_title)

    thin = Side(style="thin")
    ctr = Alignment(horizontal="center", vertical="center")
    ctrw = Alignment(horizontal="center", vertical="center", wrap_text=True)
    vmid = Alignment(vertical="center")

    widths = {'A': 3.4, 'B': 9.0, 'C': 6.75, 'D': 6.75, 'E': 0.9,
              'F': 6.75, 'G': 4.4, 'H': 2.0, 'I': max(48.6, N * 1.4 + 10)}
    for col, w in widths.items():
        ws.column_dimensions[col].width = w

    # Row1/2 標題
    ws.merge_cells("A1:I1")
    ws["A1"] = build_title_line(meta)
    ws["A1"].font = _f(11, True)
    ws["A1"].alignment = ctr
    ws.merge_cells("A2:I2")
    ws["A2"] = f"{class_label}({subject})班級成績表(座號排序)" if subject else f"{class_label}班級成績表(座號排序)"
    ws["A2"].font = _f(11, True)
    ws["A2"].alignment = ctr
    ws.row_dimensions[1].height = 15.75
    ws.row_dimensions[2].height = 15.75

    # Row3-7 尺規 / 欄頭 / 標準答案
    tens, units = build_ruler(N)
    std_str = build_answer_string([encode_answer_or_bonus(ans_key[q]) for q in q_nos], N)
    ws["H3"] = "題"
    ws["I3"] = tens
    ws["H4"] = "號"
    ws["I4"] = units
    ws.merge_cells("H5:H6")
    ws["H5"] = "特"
    ws["H7"] = "標"
    ws["I7"] = std_str
    for ref in ("H3", "H4", "H5", "H7"):
        ws[ref].font = _f(9)
        ws[ref].alignment = ctr
    for ref in ("I3", "I4", "I7"):
        ws[ref].font = _f(9)
        ws[ref].alignment = vmid
        ws[ref].data_type = "s"  # 強制文字，避免以 =/+/-/@ 開頭被 Excel 當公式

    headers = [("A", "座\n號"), ("B", "姓名"), ("C", "選擇\n成績"), ("D", "非選\n成績"),
               ("E", ""), ("F", "合計\n成績"), ("G", "班級\n名次")]
    for col, txt in headers:
        ws.merge_cells(f"{col}6:{col}7")
        c = ws[f"{col}6"]
        c.value = txt
        c.font = _f(9)
        c.alignment = ctrw
        c.border = Border(bottom=thin)
    ws.row_dimensions[6].height = 24

    # 名次：合計降序，同分同名次
    def total_of(s):
        return (s.get('選擇', 0) or 0) + (s.get('非選', 0) or 0)
    order = sorted(range(len(students)), key=lambda i: -total_of(students[i]))
    rank_of, seen = {}, {}
    for pos, i in enumerate(order):
        t = total_of(students[i])
        if t not in seen:
            seen[t] = pos + 1
        rank_of[i] = seen[t]

    # 學生列（座號排序）
    idx_sorted = sorted(range(len(students)), key=lambda i: str(students[i].get('座號', '')))
    r = 8
    scores = []
    for i in idx_sorted:
        s = students[i]
        sel = s.get('選擇', 0) or 0
        nonsel = s.get('非選', 0) or 0
        tot = sel + nonsel
        scores.append(tot)
        cells = [encode_student_cell(s.get('answers', {}).get(q, ""), ans_key[q]) for q in q_nos]
        istr = build_answer_string(cells, N)
        ws.cell(r, 1, str(s.get('座號', ''))).alignment = ctr
        ws.cell(r, 2, s.get('姓名', ''))
        ws.cell(r, 3, round(sel, 1))
        ws.cell(r, 4, "" if nonsel == 0 else round(nonsel, 1))
        ws.cell(r, 6, round(tot, 1))
        ws.cell(r, 7, rank_of[i]).alignment = ctr
        ic = ws.cell(r, 9, istr)
        ic.alignment = vmid
        ic.data_type = "s"  # 強制文字，避免作答字串以 = 開頭被當公式
        for c in range(1, 10):
            ws.cell(r, c).font = _f(9)
        r += 1

    # 統計
    n = len(scores)
    fm = five_marks(scores)
    avg = sum(scores) / n if n else 0
    sd = pop_std(scores)

    def fmt(x):
        return f"{x:.2f}"
    stat1 = (f"頂    標: {fmt(fm['頂'])}    前    標: {fmt(fm['前'])}    均    標: {fmt(fm['均'])}"
             f"   後    標: {fmt(fm['後'])}    底    標: {fmt(fm['底'])}    標 準 差: {fmt(sd)}")
    stat2 = (f"平    均: {fmt(avg)}    選擇均標: {fmt(fm['均'])}    非選均標: {fmt(0)}"
             f"   班級人數: {n:5d}    缺考人數: {0:5d}    到考人數: {n:5d}")
    ws.cell(r, 1, stat1).font = _f(9)
    r += 1
    ws.cell(r, 1, stat2).font = _f(9)
    r += 1

    # 配分資料
    blocks = _blocks(q_nos, q_config)
    total_score = sum(float(q_config.get(q, {}).get('score', 0)) for q in q_nos)
    ws.cell(r, 1, f"[配分資料]  配分合計:{total_score:.2f}分").font = _f(9)
    r += 1
    for bi, b in enumerate(blocks, 1):
        typ, score, opts = b['key']
        a, z = b['start'], b['end']
        cnt = z - a + 1
        sub = cnt * score
        line = (f"大題{bi}:{TYPE_ZH.get(typ, typ)}, {a:2d}-{z:3d}題,"
                f"答對給{score:6.2f}分,答錯倒扣 {0:5.3f}分,合計:{sub:6.2f}分")
        if typ in ("GSAT", "NORMAL", "EXACT"):
            line += f",選項個數:{opts},選項外扣{0:6.2f}分"
        ws.cell(r, 1, line).font = _f(9)
        r += 1

    # 代碼說明
    for ln in LEGEND:
        ws.cell(r, 1, ln).font = _f(9)
        r += 1

    # 最後一道防線：任何以 =/+/-/@ 開頭的文字格強制成文字，
    # 避免 Excel 把作答字串(如以「=」開頭)當公式 → 開檔跳「修復」
    for row_cells in ws.iter_rows():
        for cell in row_cells:
            if isinstance(cell.value, str) and cell.value[:1] in ("=", "+", "-", "@"):
                cell.data_type = "s"

    ws.freeze_panes = "A8"
    return ws
