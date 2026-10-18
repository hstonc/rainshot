# 來源、致謝與授權 / Provenance, credits and licensing

查核日期 / Last checked: **2026-10-18** · Scope: rainshot **0.4.7** source and dependency-based packages.

## 中文

### 與 Snow Shot 的關係

rainshot 是以 Python / PyQt5 實作的 Linux 截圖工具，功能與互動流程受到 [Snow Shot（xiaofeiTM233/snow-shot）](https://github.com/xiaofeiTM233/snow-shot/) 及其來源 [Snow Apps（mg-chao/snow-apps）](https://github.com/mg-chao/snow-apps/) 啟發。特別感謝兩個專案公開截圖、貼圖、OCR、翻譯與捲動截圖的設計和程式。亦感謝 [Flameshot](https://github.com/flameshot-org/flameshot/) 提供成熟 Linux 截圖工具的參考。

本專案以獨立的 Python / Qt 程式樹發布，沒有保留 Snow Shot 的 Git fork 祖先歷史；不是 Snow Shot 的官方 Linux 版，也不代表上游維護者背書。GitHub 是否顯示「fork」是倉庫歷史關係，不能代替個別檔案的來源與授權判斷。

現存發布樹的檢查範圍是 `rainshot/`、`tests/`、`packaging/`、文件及套件設定。未發現明確以 Snow Shot、Snow Apps 或 Flameshot 原檔形式收錄的第三方程式碼與資產；應用程式是 Python，工具列圖示以 `icons.py` 的 SVG 路徑和 `icon.svg` 提供。此結論是檔案、來源註記及實作結構的檢查，不是所有歷史版本的逐行相似性稽核，也不宣稱從未參考或改寫任何片段。

既有開發紀錄在 [架構文件](ARCHITECTURE.md) 列出曾查閱的 Snow Shot commit `0974c6cd319506236280f48153c622c0c75ea896`，包括翻譯入口、OCR 和捲動截圖流程。rainshot 使用自己的 Linux 後端、文字框及影像接合處理；翻譯連到使用者選定的供應商，沒有使用 Snow Shot 自有的翻譯伺服器。

### 專案授權與上游範圍

rainshot 的專案授權是 **GPL-3.0-or-later**，完整條款在 [LICENSE](../LICENSE)，套件設定在 [pyproject.toml](../pyproject.toml)。發布的原始碼、建置腳本與版本標籤應和安裝包對應，並與安裝包一起提供下載。

上游授權的查核結果如下；這些資料用來記錄參考來源，不表示 rainshot 收錄了整個上游專案：

| 專案與查核範圍 | 公開授權資訊 |
|---|---|
| `xiaofeiTM233/snow-shot` 的 `dev` 分支 | [`LICENSE-Commercial`](https://github.com/xiaofeiTM233/snow-shot/blob/dev/LICENSE-Commercial) 是 GPLv3 文字；[`LICENSE-NonCommercial`](https://github.com/xiaofeiTM233/snow-shot/blob/dev/LICENSE-NonCommercial) 是 Apache 2.0 文字，含 `Copyright 2025 mg-chao`。不能只憑檔名把它解讀成「所有程式碼限非商用」，或假定每個檔案可任選授權。 |
| `mg-chao/snow-apps` 的 `main` 分支 | [`LICENSE.md`](https://github.com/mg-chao/snow-apps/blob/main/LICENSE.md) 按目錄區分：`snow_shot/` 等為 GPL-3.0-or-later，部分元件為 Apache-2.0；嵌入的第三方資料保留自身授權。Snow Shot 的作者與授權聲明在 [`snow_shot/COPYRIGHT`](https://github.com/mg-chao/snow-apps/blob/main/snow_shot/COPYRIGHT)。 |
| `flameshot-org/flameshot` 的 `master` 分支 | [`README` 授權段落](https://github.com/flameshot-org/flameshot#license) 聲明主程式 GPLv3+，Logo 為 Free Art License 1.3、按鈕圖示為 Apache 2.0，另有個別第三方來源；完整 GPL 條款在 [`LICENSE`](https://github.com/flameshot-org/flameshot/blob/master/LICENSE)。 |

若後續加入可辨識的上游程式碼、改寫片段、圖片或圖示，應在同一次修改中記錄原檔 URL、commit、作者、授權和修改內容，保留適用的 copyright / NOTICE，並附上需要的授權文字。把 Git 倉庫建成獨立專案不會取消這些要求。此版本未把上游商標或圖示當作 rainshot 品牌。

### 執行依賴與沒有打包的內容

本專案的依賴式套件提供 rainshot 自身的 Python 原始碼、SVG、啟動器與文件，依賴作業系統或使用者另行安裝的執行環境，沒有把以下第三方程式重新授權為 GPL：

| 依賴 | 用途與授權來源 |
|---|---|
| Python / PyQt5 / Qt 5 | Python 執行環境及 UI。開源 [PyQt 是 GPLv3 授權，而非 LGPL](https://www.riverbankcomputing.com/software/pyqt/intro)；Qt 各模組及第三方元件有自己的 [GPL / LGPL 條款](https://www.qt.io/development/open-source-lgpl-obligations)。 |
| NumPy / OpenCV | 像素處理與接合。[NumPy 為 BSD 3-clause](https://github.com/numpy/numpy/blob/main/LICENSE.txt)；[目前 OpenCV 主授權為 Apache 2.0](https://github.com/opencv/opencv/blob/4.x/LICENSE)，實際安裝版本和附帶元件依套件授權檔為準。 |
| AT-SPI / pyatspi、X11 / XInput / XTest | 元素幾何、視窗資訊、快捷鍵與明確要求的捲動輸入；使用系統動態函式庫及 [pyatspi](https://github.com/GNOME/pyatspi2/blob/master/COPYING)，保留各套件自身的授權。 |
| ZBar | 本機 QR 辨識，使用系統函式庫；見 [ZBar 授權](https://github.com/mchehab/zbar/blob/master/LICENSE.md)。 |
| FFmpeg | 以外部行程錄製與編碼；[實際 GPL / LGPL 授權取決於建置選項和元件](https://ffmpeg.org/legal.html)。rainshot 不內附 FFmpeg 二進位。 |
| Tesseract（可選） | 本機 OCR 外部行程；見 [Apache 2.0 授權](https://github.com/tesseract-ocr/tesseract/blob/main/LICENSE)。語言資料由使用者的發行版套件另行安裝。 |
| RapidOCR / ONNX Runtime（可選） | 使用者另裝到獨立 Python 環境；見 [RapidOCR 1.4.4 授權](https://github.com/RapidAI/RapidOCR/blob/v1.4.4/LICENSE) 與 [ONNX Runtime 授權](https://github.com/microsoft/onnxruntime/blob/main/LICENSE)。模型與其相關資料須依實際下載套件的聲明處理。 |

發布樹不含 OCR 模型、Tesseract 語言資料或第三方字型；使用者的截圖記錄、瀏覽器 profile、設定與 API 金鑰不是發布內容。UI 使用系統字型；程式提及字型名稱不會把字型檔一起打包。網路翻譯供應商有各自的服務條款、金鑰與費用；程式授權不提供供應商帳號或使用額度。

若未來提供自帶 Python / Qt / FFmpeg / OCR 模型的 AppImage、Flatpak 或其他整合執行環境，必須針對實際收錄的版本補上第三方授權、通知與所需對應原始碼；本文件的「依賴式套件」範圍不能直接套用到那種新產物。

## English

### Relationship to Snow Shot

rainshot is a Linux screenshot application implemented in Python / PyQt5. Its feature set and interaction design were inspired by [xiaofeiTM233/snow-shot](https://github.com/xiaofeiTM233/snow-shot/) and its upstream [mg-chao/snow-apps](https://github.com/mg-chao/snow-apps/). We thank both projects for publishing their screenshot, floating-image, OCR, translation and scrolling-capture work, and [Flameshot](https://github.com/flameshot-org/flameshot/) for its Linux screenshot tooling.

rainshot is published as a separate Python / Qt source tree without Snow Shot's Git fork ancestry. It is not an official Snow Shot Linux port and does not imply upstream endorsement. A GitHub fork relationship describes repository history; it does not determine the origin or license of individual files.

The release-tree review covered `rainshot/`, `tests/`, `packaging/`, documentation and package metadata. No clearly vendored Snow Shot, Snow Apps or Flameshot source files or assets were identified. The application code is Python; its vector artwork is represented by `icons.py` and `icon.svg`. This was a review of files, source notices and implementation structure, not an exhaustive historical line-by-line similarity audit or a claim that no snippet was ever consulted or adapted.

[ARCHITECTURE.md](ARCHITECTURE.md) records earlier references to Snow Shot commit `0974c6cd319506236280f48153c622c0c75ea896`, including translation endpoints and OCR / scrolling workflows. rainshot uses its own Linux backend, text geometry and image stitching. Translation goes to the user's selected provider, not Snow Shot's private backend.

### License and upstream records

rainshot is licensed under **GPL-3.0-or-later**; see [LICENSE](../LICENSE) and [pyproject.toml](../pyproject.toml). Release packages must have matching source, build scripts and version tags available alongside them.

The upstream records above distinguish the older Snow Shot `dev` branch's GPLv3 and Apache 2.0 license texts, the current Snow Apps per-directory license scopes, and Flameshot's GPLv3+ main code. Flameshot's logo and button artwork have separate licenses. The older `Commercial` / `NonCommercial` filenames alone do not establish a noncommercial restriction or a choice of license for every file. Consult the actual revision and file notices when reusing material.

When adding identifiable upstream code, adapted snippets or artwork, record its source URL, commit, author, license and modifications, retain applicable copyright / NOTICE statements, and include required license texts. A new repository does not remove those obligations. This release does not use upstream logos as rainshot branding.

### Runtime dependencies and release contents

Dependency-based packages contain rainshot's Python source, SVG artwork, launcher and documentation. Python, PyQt5 / Qt, NumPy, OpenCV, AT-SPI / pyatspi, X11 libraries, ZBar and FFmpeg are supplied separately by the system or user and retain their own licenses. The dependency table in the Chinese section links to the authoritative license records. In particular, open-source PyQt uses GPLv3 rather than LGPL; FFmpeg's license depends on its build configuration.

Tesseract language data and optional RapidOCR / ONNX Runtime packages and models are installed separately. No OCR models, language data or third-party fonts are included in the release tree. Users' screenshot history, browser profiles, settings and API keys are not release contents. The UI uses installed system fonts. Translation services retain their own terms, credentials and charges.

A future self-contained AppImage, Flatpak or bundled runtime would require a separate inventory of the actual third-party versions, license texts, notices and corresponding-source requirements. The dependency-only scope described here must not be assumed for those future artifacts.
