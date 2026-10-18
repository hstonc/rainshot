# 相容性與實測範圍 / Compatibility and test coverage

查核日期 / Last checked: **2026-10-18** · Applies to rainshot **0.4.7**.

## 中文

### 支援範圍怎麼讀

rainshot 目前以 **Linux Mint 21.3、Cinnamon、X11、雙螢幕、100% 縮放**為實機驗證基線。Ubuntu / Debian 的依賴與 `.deb` 包裝已準備，但這不等於每個發行版、桌面環境、縮放比例和合成器都完成實測。

| 環境 | 證據與狀態 |
|---|---|
| Linux Mint 21.3 / Cinnamon / X11 | 已做原生桌面與套件測試，是目前主要驗證環境。 |
| Ubuntu / Debian 的 X11 桌面 | 提供依賴式 `.deb` / 原始碼安裝途徑；沒有獨立覆蓋所有版本的實機矩陣。Python 須為 3.10 以上。 |
| Ubuntu / GNOME Wayland | 已實作 Screenshot Portal 路徑及模擬協議測試；沒有完整真實 Wayland 桌面驗證。功能限制見下表。 |
| Fedora、Arch Linux 及其他發行版 | 原始碼與可用的封裝方式供試用；本版沒有這些發行版的原生安裝及桌面實測。套件格式可安裝不代表功能已通過驗證。 |
| KDE Plasma、Sway、Hyprland 等其他桌面 / 合成器 | 沒有本版的原生桌面驗證；需回報實際環境及 Portal 後端。 |
| 混合 DPI、分數縮放、ARM | 部分座標與影像合成有單元測試；沒有對應硬體 / 桌面的完整驗證。`.deb` 的 `Architecture: all` 指程式本身是 Python，不代表所有架構測試通過。 |

0.4.7 的既有驗證記錄為 **326 項自動測試通過（2026-10-03）**，另有原生 Chromium / Firefox 及 GTK 3 / Qt 5 fixture 測試。測試數不是 Linux 發行版數，也不能代替 Wayland 實測。具體方法、版本歷史與限制見 [VALIDATION.md](VALIDATION.md)；新的發布驗證應記錄其實際日期和結果。

### X11 與 Wayland 功能表

| 功能 | X11 | Wayland（此版） |
|---|---|---|
| 區域 / 視窗 / 全畫面截圖 | 使用 Qt 讀取螢幕並顯示 rainshot 選區。 | 呼叫系統 Screenshot Portal 的互動選區；可選範圍由桌面後端決定。 |
| 視窗、網頁與控件自動選區 | X11 視窗資訊 + AT-SPI 元素幾何；可在相鄰元素間隙選取共同外框，Tab 切換父層。 | 沒有 rainshot 的任意應用視窗 / 元素吸附；使用系統提供的截圖介面。 |
| 貼圖、標註、保存、OCR、翻譯、QR、取色、圖片拼接 | 已實作；主要流程在上述 X11 基線驗證。 | 取得圖片後的處理程式可用，但尚未完整實機驗證；視窗定位、置頂、失焦關閉及剪貼簿行為依合成器。 |
| 連續捲動長截圖 | 支援固定區域取樣、手動捲動或明確啟動的自動捲動。 | 未實作連續螢幕擷取與輸入控制；可逐張截圖，再用「更多 → 拼接圖片」。 |
| GIF / 動態 WebP 錄製 | 使用 FFmpeg `x11grab`；每次限單一螢幕、最長 120 秒。FFmpeg 須有相應 GIF / WebP 編碼器。 | 未實作 ScreenCast / PipeWire 錄製；此版會顯示不支援提示。 |
| 程式內設定全域快捷鍵 | 透過 X11 註冊；桌面已有綁定時可能衝突。 | 不註冊全域快捷鍵；到桌面鍵盤設定綁定 `rainshot --capture` 等命令。未實作 GlobalShortcuts Portal。 |
| 截圖後的工具快捷鍵 | 貼圖取得鍵盤焦點時使用，允許自訂。 | 同樣依貼圖焦點使用；不會變成可在其他軟體內觸發的全域快捷鍵。 |
| 工作區移動與貼圖置頂 | 已驗證正常管理視窗、置頂及工作區屬性；實際拖曳手勢由視窗管理器提供。 | 請由桌面提供的移動 / 工作區操作處理；不能保證等同 Cinnamon X11 的行為。 |
| 系統匣與角落提示 | Cinnamon 基線已驗證。 | 依桌面系統匣支援與合成器定位規則；必要時用 `rainshot --settings` 開啟設定。 |

程式根據 `XDG_SESSION_TYPE`、`WAYLAND_DISPLAY` 及 Qt 平台判斷 Wayland，正常入口會選擇原生 Qt Wayland 平台。不會在 Wayland 工作階段把 XWayland 當成能讀取全部螢幕的替代方式。安裝 Arch 包、RPM 或其他格式不會繞過 Wayland 的功能限制。

Wayland 需要 `xdg-desktop-portal` 及適合目前桌面的後端，而且該後端必須實作 Screenshot 介面。例如 GNOME 常使用 `xdg-desktop-portal-gnome`；其他桌面應使用對應後端。授權對話框、可擷取內容及是否記住授權由桌面後端決定。

此版每次使用互動 Screenshot 請求；沒有實作長期 ScreenCast 工作階段或 `restore_token`。不能承諾「授權一次後永遠無提示」。Screenshot 與持續畫面分享是不同介面，規格見 [Screenshot](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Screenshot.html) 和 [ScreenCast](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html)。

### 元素識別、OCR 與服務限制

- **Firefox / Qt 元素沒有出現：** 在「設定 → 一般設定」按「啟用更多軟體的元素識別」，必要時重開目標軟體。這個明確操作會啟用桌面輔助功能，不會啟動朗讀器；程式不會在背景自動更改此設定。
- **部分軟體只選到整個視窗：** AT-SPI 須由目標應用公開。Canvas、遊戲、自繪控件、重疊內容、未公開的 Electron 介面及特殊可捲動容器不保證有精確元素，請手動拖曳選區。
- **不規則群組：** 共同選區是成員最左、最上、最右、最下邊界組成的矩形，會包含中間空白；不會沿不規則外緣裁出透明形狀。合併以游標附近的可見元素為範圍，不保證猜中所有主觀群組。
- **藝術字與 OCR：** 文字高度、描邊、傾斜、背景及模型會影響識別。RapidOCR 是可選本機引擎，不保證正確識別每種字型；辨識後可選取和複製，不應把結果當作原文的可靠校對。
- **翻譯與以圖搜圖：** 翻譯會將使用者選擇的文字送至選定服務；免金鑰入口可能變動、限流或失效。以圖搜圖是交給瀏覽器手動上傳的流程，是否接受拖放由網站決定。
- **語言與字型：** 此版 README 中英雙語，應用介面主要為中文；沒有完整英文 UI。中文顯示和輸入依賴系統的 CJK 字型及輸入法。

### 回報問題

請附上 rainshot 版本、發行版 / 桌面 / 合成器、X11 或 Wayland、螢幕數與每個螢幕的縮放比例、重現步驟和預期行為。可執行：

```sh
rainshot --diagnose
```

此命令不擷取螢幕。Wayland 問題請另提供使用的 Portal 後端；元素識別問題請提供軟體名稱與版本、是否已啟用桌面輔助功能。請移除金鑰及私人內容後再貼入公開 issue。

## English

### Tested baseline

The native test baseline is **Linux Mint 21.3, Cinnamon, X11, two monitors, 100% scaling**. Packaging for another distribution does not establish desktop compatibility.

| Environment | Status |
|---|---|
| Mint 21.3 / Cinnamon / X11 | Native desktop and package validation baseline. |
| Ubuntu / Debian X11 | Dependency-based installation is provided; all distribution versions and desktops have not been tested. Requires Python 3.10 or later. |
| Ubuntu / GNOME Wayland | Screenshot Portal implementation and protocol tests exist; no complete native Wayland validation. |
| Arch, Fedora and other distributions | Installation paths are intended for testing; no native distribution / desktop validation for this release. |
| KDE Plasma, Sway, Hyprland and other compositors | Not natively validated for this release. |
| Mixed DPI, fractional scaling and ARM | Some coordinate / composition unit coverage; no complete hardware or desktop validation. Debian `Architecture: all` describes Python package contents, not tested CPU coverage. |

The recorded 0.4.7 regression result is **326 tests passed on 2026-10-03**, with separate Chromium / Firefox and GTK 3 / Qt 5 native fixture checks. This is not a distribution matrix or proof of Wayland support. See [VALIDATION.md](VALIDATION.md) and the actual release verification results.

### X11 / Wayland behavior

| Feature | X11 | Wayland in this release |
|---|---|---|
| Capture | rainshot's frozen-screen selection interface. | Interactive system Screenshot Portal; choices depend on the desktop backend. |
| Window / element snapping and adjacent-element groups | X11 window geometry plus AT-SPI; Tab selects parent candidates. | No rainshot element snapping; use the system capture interface. |
| Floating image, annotation, saving, OCR, translation, QR, color sampling, file stitching | Implemented; main workflows tested on the X11 baseline. | Image-processing paths are implemented, but not fully tested on native Wayland. Positioning, always-on-top, focus and clipboard behavior depend on the compositor. |
| Continuous scrolling capture | Implemented. | Not implemented; capture images individually and use file stitching. |
| GIF / animated WebP recording | FFmpeg `x11grab`, one monitor, up to 120 seconds; requires suitable encoders. | No ScreenCast / PipeWire recording implementation. |
| Global shortcuts | X11 registration with conflict reporting. | Bind commands such as `rainshot --capture` in desktop settings. No GlobalShortcuts Portal implementation. |
| Shortcuts after capture | Customizable while the floating image has focus. | Same focus requirement; these are not global shortcuts. |
| Workspaces, tray and corner notices | Cinnamon baseline tested; move gestures come from the window manager. | Compositor / shell dependent; use `rainshot --settings` if tray access is unavailable. |

Wayland sessions use the native Qt Wayland platform and Screenshot Portal rather than treating XWayland as unrestricted screen access. Install `xdg-desktop-portal` and a backend appropriate for the desktop that implements Screenshot. The backend controls consent, capture choices and permission persistence.

This release makes interactive Screenshot requests. It has no persistent ScreenCast session or `restore_token` integration and cannot promise permanent, prompt-free consent. The [Screenshot](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.Screenshot.html) and [ScreenCast](https://flatpak.github.io/xdg-desktop-portal/docs/doc-org.freedesktop.portal.ScreenCast.html) specifications describe different interfaces. Changing the package format does not remove these limits.

### Practical limitations and reporting

For Firefox / Qt element detection, use **Settings → General → 啟用更多軟體的元素識別** and restart the target application if needed. This explicit action enables desktop accessibility without starting a screen reader. Applications must publish useful AT-SPI geometry; canvas content, games, custom controls, overlapping regions and some Electron interfaces can still require manual selection.

Multi-element selection produces the rectangular bounding box of nearby visible members, including gaps. It does not create an irregular transparent crop or guarantee every intended grouping. OCR accuracy varies with fonts, layout and models. Translation sends selected text to the chosen provider; keyless endpoints can change or fail. Reverse image search hands the image to a browser for user-controlled upload.

The README is bilingual; the application UI is primarily Chinese and has no complete English localization. Chinese display and input require suitable system fonts and input methods.

When reporting a problem, include the app version, distribution, desktop / compositor, session type, monitor layout and scaling, reproduction steps and expected result. `rainshot --diagnose` prints basic diagnostics without capturing the screen. For Wayland include the Portal backend; for snapping include the target application's version and accessibility setting. Remove credentials and private content before posting a public issue.
