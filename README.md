# 自動閱卷小助手

Windows 答案卡讀卡／批卷平台：手動設定答案與配分、選取掃描 PDF，輸出 Excel 成績、批閱 JPG 與結果 PDF。

## 下載免安裝試用版

[下載 V5.2 試用版（2026-09-20）](https://github.com/oskens1/omr-grader/releases/tag/v5.2-trial.20260920)

下載 Release 中的 **OMR_Grader_V52_20260920.zip**（約112 MiB），全部解壓後開啟 `OMR_Grader_V52.exe`，不必安裝 Python。GitHub 自動提供的「Source code」不是 Windows 執行包。

完整操作見[繁體中文使用說明](使用說明.md)，測試與限制見[驗收報告](驗收報告.md)。

## V5.2 改了什麼

- 保留原視窗、手動答案／配分與三種既有卡別。
- 新增「影印卡－9/14 改良版」：黑線追蹤、格框檢查、淡塗與未知學號待核。
- 新模式目前限 **Q1～Q10**，其他題數或正式卡請使用原模式。
- 計分核心未更動；新增待核輸出、每批獨立資料夾與可攜路徑。

支援原 ANS93002-7A 幾何格式；不是通用 OCR。新模式使用 A4 橫向、200 dpi 影印卡版面。請逐頁覆核再採用成績。

## 已測與未測

五頁合成卡涵蓋正常、旋轉、空白、淡塗、黑線破損；Python／EXE 判讀與 Excel 值一致、批閱 JPG 完全一致。本機 Windows 中文路徑搬移測試通過。**尚未在另一台乾淨 Windows 驗證**，也不宣稱所有真實掃描的準確率。

`samples/` 全為人工合成，沒有真實学生名單、答案卡、成績、雲端帳號或金鑰。

## 從原始碼執行或建置

在獨立 CPython 3.12 環境建立 venv，依 `requirements-share-lock.txt` 安裝固定版本後執行 `python share_launcher.py`。

Windows PowerShell 建置：`./build_share.ps1 -Python <venv中python.exe完整路徑>`。先測 console 版，確認後加 `-Windowed`；產物位於 `%TEMP%/omr_v52_build/dist/OMR_Grader_V52`。需另附本倉庫的合成設定、samples與說明；不可把個人使用後的資料重新包入。

套件公開授權文字收錄於 `third_party_licenses/`。本倉庫未另行授予自訂程式碼的開源授權；目前提供同事試用與檢視。
