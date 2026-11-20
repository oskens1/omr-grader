# 自動閱卷小助手

Windows 答案卡批改工具。設定答案與配分後匯入掃描 PDF，可輸出 Excel 成績與批閱圖。

## Windows 試用下載

下載 `OMR_Grader_V53_20261120.zip`，全部解壓後開啟 `OMR_Grader_V53.exe`。Windows 試用包已附 Python 執行環境。 [V5.3 試用版](https://github.com/oskens1/omr-grader/releases/tag/v5.3-trial.20261120) · [V5.2 試用版](https://github.com/oskens1/omr-grader/releases/tag/v5.2-trial.20260920)

V5.3 新增可選的「影印卡－定位復原」。適用 ANS93002-7A、A4 橫向影印掃描的第 1～15 題。可在印刷框佐證充足時復原中間漏掉的定位黑條，並將可疑塗記及重複學號送待核。既有四種模式、手動配分與計分公式沿用。

操作流程見 [繁體中文使用說明](使用說明.md)，測試範圍見 [V5.3 驗收](驗收報告_V53.md)。`samples/` 內都是人工合成素材。

## 從原始碼執行

在獨立 CPython 3.12 環境建立 venv，依 `requirements-share-lock.txt` 安裝套件後執行 `python share_launcher.py`。可用 `python test_recovery.py` 重跑合成缺列及待核測試。

Windows 執行檔由 PowerShell 執行 `./build_share.ps1 -Python <venv 的 python.exe 完整路徑> -Windowed` 建置，預設放在 `%TEMP%/omr_v53_build/dist/OMR_Grader_V53`。

套件授權文字收錄於 `third_party_licenses/`。此倉庫提供軟體試用與原始碼檢視。
