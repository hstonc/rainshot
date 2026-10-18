# rainshot 0.4.7 架構與參考來源

0.4.7：間隙選區重用有限兄弟搜尋中的可見幾何，無須讀取文字或新增 D-Bus 呼叫。游標沒有直接命中兄弟元素時，取包住游標且足夠近的元素對作為起點，建立固定的局部搜尋區域；將與區域相交、彼此鄰近的成員組成完整群組。可包含三個、四個、五個或更多元素，以及 L 形、網格與寬高不同的混合排列。使用相交範圍判斷容許大型成員跨出搜尋區域，成員數增加時不再擴大搜尋區域，避免一路連鎖到整頁。只輸出完整群組外框，其座標為所有成員的 min(x)、min(y)、max(x + width)、max(y + height)，再沿用父框裁切與候選排序；不保留較小的起始元素對以免它因面積較小搶先預選。Tab、點擊確認與拖曳仍沿用既有選區流程。

0.4.6：`DesktopAccessibility` 透過 Qt D-Bus 非同步讀取 `org.a11y.Status`；一般設定只讀狀態，使用者按下啟用按鈕才送出 `IsEnabled=true`，完成後再次讀取確認。每次呼叫有 2,500 ms 逾時；不改動 `ScreenReaderEnabled`。依桌面服務實作，此操作可能同步保存 toolkit-accessibility 設定。參見 [Firefox 的啟用判斷](https://raw.githubusercontent.com/mozilla-firefox/firefox/main/accessible/atk/Platform.cpp)、[GNOME 輔助功能服務](https://raw.githubusercontent.com/GNOME/at-spi2-core/AT_SPI2_CORE_2_44_0/bus/at-spi-bus-launcher.c) 與 [Qt 5 的服務連線](https://raw.githubusercontent.com/qt/qtbase/5.15/src/platformsupport/linuxaccessibility/dbusconnection.cpp)。

元素探測將最大深度增至 64，保持 160 節點 / 800 ms 的總預算；發現可用子分支後保留遞迴預算。GTK 捲動後的 viewport 可能提供無效原點並缺少 SHOWING，只有這種結構容器允許沿已驗證的父範圍繼續，真正輸出的子控件仍須 VISIBLE、SHOWING 與有效座標。主行程僅有整個視窗時，繼續檢查已驗證的相關 renderer。選區首次只有視窗或沒有元素時，游標不動則 450 ms 後重試一次；新移動恢復 140 ms 延遲，Tab 選定與拖曳不被重試覆蓋。

0.4.6 的間隙選區最初合併左右 / 上下同帶的兩個控件；0.4.7 以上改用完整局部群組，仍保留 256 原生像素的接近程度上限與既有探測預算。

0.4.5：`SavedNoticeManager` 由 `QApplication` 持有，保存通知是無父貼圖的頂層 `CornerMessage`，保存實際路徑與提示角落的快照；成功後關閉貼圖，動作不引用已銷毀的貼圖。點擊、逾時、取代或應用退出時清理；`Controller.hide_windows()` 在新截圖與錄製之前清理通知，避免提示出現在擷取畫面。取消與失敗不關閉貼圖；錄製成功略過該貼圖的恢復與啟用。

AT-SPI 在找到指定視窗後查詢一次 `getRelationSet()`，丟棄關係與目標，不讀 DOM 屬性；Chromium 的該介面會要求按需提供網頁輔助功能。快取更新與短暫等待都在可取消子行程與既有時間界限內。依據 [Chromium 的 AtkRefRelationSet 實作](https://github.com/chromium/chromium/blob/main/ui/accessibility/platform/ax_platform_node_auralinux.cc) 與 [輔助功能架構說明](https://github.com/chromium/chromium/blob/main/docs/accessibility/overview.md)。根視窗搜尋可穿過非元件容器，找到目標行程後立即探測，保留命中遍歷的預算。

0.4.4：`ask_save_path` 是持久化的布林設定，保存按鈕與快捷鍵每次讀取；開啟後進入既有另存圖片流程，取消不寫入，手動路徑不改動預設資料夾，錄製仍使用預設資料夾。保存成功提示帶有本次檔案所在資料夾的動作，由 `QDesktopServices` 呼叫預設檔案管理器。

`hints.py` 同步切換 `WA_TransparentForMouseEvents` 與原生 `WindowTransparentForInput`，讓一般提示穿透、可點提示接受輸入；僅切換 QWidget 屬性不足以更新已建立的原生視窗。提示保持不接受焦點，位置遵循四角設定；逾時、隱藏或取代提示時清除動作。未釘住貼圖的外部點擊判定包含可點提示範圍，避免在執行動作前關閉貼圖。

0.4.3：貼圖使用無邊框一般視窗，X11 設定 `SKIP_TASKBAR` 並保留 `ABOVE`；拖曳優先呼叫 Qt 的 `startSystemMove()` 讓工作區管理器接手，失敗時回退到舊的視窗座標拖曳。

啟動 → 系統匣待命；明確截圖命令 → Controller → X11 / Portal → FloatingShot。設定頁延遲建立。影像處理與模型推論不在 GUI 執行緒執行。

- `app.py` 管理截圖、捲動與錄製工作階段、隱藏 / 恢復貼圖、退出清理。舊版的每次等待兩秒追加流程已移除。
- `config.py` 使用 rainshot 設定命名空間，管理預設匯出資料夾、路徑驗證及原檔原子複製。已移除舊命名空間的相容讀取。
- `capture.py` / `x11.py` / `snap.py`：凍結桌面、EWMH 視窗堆疊與 AT-SPI 控件範圍。視窗回退立即提供；元素查詢為可取消子行程，140 ms debounce / 1,500 ms 上限，取消不阻塞 GUI。使用 X11 原生螢幕像素查詢，在所屬螢幕換算為 Qt 邏輯座標；快取依視窗隔離，延遲回應不能覆寫手動或 Tab 選區，Shift 放開後恢復吸附。
- `accessible.py` 只輸出幾何，不讀名稱、文字、URL 或 DOM 屬性，不執行應用動作。只探測指定 PID，或 `/proc` 驗證為同 UID、8 層內子行程的瀏覽器 renderer；依前景視窗原生範圍挑選單一根視窗。深層命中會補祖先並逐層裁切可見父框；命中失效時有限度檢查包含游標的子分支，虛擬表格的 `MANAGES_DESCENDANTS` 不枚舉。內部時間界限 800 ms、每次 D-Bus 100 ms、最多 160 節點 / 64 層、48 個應用 PID、每個匹配應用 24 個根視窗，每次後備檢查至多 64 個子元件、深入 4 個分支；候選去重後由小到大排序。
- `floating.py`：圖片、圖示工具列、原位 OCR 文字選取、附屬譯文 / QR 面板、取色及錄製設定。釘住後工具列收起不推移圖片；自有下拉選單沿 QObject 父鏈辨識。色碼從 render cache 的原像素讀取，提示不寫入匯出。
- `magnifier.py`：按鈕啟動的 11×11 像素放大鏡，不接受焦點與滑鼠事件；方向鍵從原始影像座標逐像素微調。
- `image_search.py`：標準 QDrag 檔案 URI 與 image MIME、私有有界 PNG 快取；瀏覽器手動上傳交接，不含 HTTP 上傳介面。二維碼網址僅接受完整 HTTP(S)。
- `shortcuts.py` 是截圖後快捷鍵、預設值、衝突驗證與動態提示的共同定義；`hotkeys.py` 管理 X11 被動按鍵註冊、衝突與釋放。長截 / 錄製暫時註冊 Ctrl+Enter、Ctrl+Esc，結束時清理。
- `scroll_capture.py`：220 ms 取樣，單一背景接合工作，忙碌時略過中間畫面而不累積無界佇列。ORB / Hamming 描述子估計垂直位移，再以原解析度重疊區與文字邊緣驗證。保留最後一次成功的 viewport，反向捲動或無法接合時不污染長圖。固定頁尾僅保留一次；預覽限 128 × 420。
- 捲動控制列優先放在選區外；空間不足時收起預覽，再退回右上角懸浮按鈕。滑鼠進入按鈕區時暫停擷取，移出隱藏後至少等下一個取樣週期。控制列禁用系統陰影，避免陰影污染選區。
- `recording.py`：FFmpeg X11grab → 私有 FFV1 暫存 → GIF palettegen / paletteuse 或 libwebp_anim → 原子匯出。限制 120 秒、20 FPS、512 MB 暫存；停止與編碼均有逾時、取消和清理。沒有空間放控制列時使用工作階段快捷鍵與系統匣。
- `qr.py`：libzbar C API，QR-only，保留原始位元組再解 UTF-8，避免中文被啟發式編碼轉換破壞；獨立子行程、20 秒上限、私有暫存與取消。
- `ocr.py` / `rapid_worker.py`：Tesseract TSV 或可選 RapidOCR / PP-OCRv4。RapidOCR 用獨立 Python 環境，只載入套件附帶本機模型；限制推論執行緒數。兩者輸出同一 `Word` / `TextSelection` 幾何模型。字符位置根據文字框與字形寬度估計。
- `translation.py`：Google、Microsoft、DeepL、有道 v3、DeepSeek / 通義千問 Turbo、Plus、Max / 相容 Chat Completions、LibreTranslate。最多 5,000 字、1 MB 回應、60 秒。HTTPS 使用 `translation_http.py` 的系統 Python TLS，避免 Qt 與 OpenSSL ABI 不一致；請求和金鑰透過 stdin，不放入 argv 或暫存檔。HTTP loopback 使用 QNetworkAccessManager。兩種傳輸均不追蹤转址、不自動重試，關閉貼圖即取消。
- `history.py`：自動截圖 PNG 快取限制張數 / 256 MB、0600 檔案；清除不刪除另存輸出。`ipc.py` 讓 Peer 擁有 socket 與計時器，先關傳輸再分派，避免延遲回呼使用已刪除的 QLocalSocket。
- `icons.py` 與 `icon.svg` 是原創 SVG，深色背景與藍紫色主題；`hints.py` 將四角提示與工具列分開。

`home.py`、`editor.py` 保留為舊原型與回歸測試用途；正常入口不建立這些舊視窗。

## Snow Shot 對照

本次查閱 Snow Shot `dev` 的 commit `0974c6cd319506236280f48153c622c0c75ea896`。參考操作流程與公開協議；此發布樹是 Python/Qt 實作，來源與授權查核見 [PROVENANCE.md](PROVENANCE.md)：

- [翻譯實作](https://github.com/xiaofeiTM233/snow-shot/blob/0974c6cd319506236280f48153c622c0c75ea896/src/services/tools/translation.ts)：包含 Google `translate_a/single`、Microsoft Edge `translatetext` 免金鑰入口，以及 Snow Shot 自有後端。rainshot 直接對使用者選定的 Google / Microsoft 入口送出文字，不依赖 Snow Shot 自有伺服器。
- [OCR 服務](https://github.com/xiaofeiTM233/snow-shot/blob/0974c6cd319506236280f48153c622c0c75ea896/src-tauri/src-crates/app-services/src/ocr_service.rs)：Paddle / RapidOCR 模型與 ONNX Runtime。本版可選的 RapidOCR 1.4.4 同樣附帶 PP-OCRv4 detection / recognition 與 mobile v2 classification 模型，但包裝與字框處理不同，識別品質不保證相同。
- [捲動截圖服務](https://github.com/xiaofeiTM233/snow-shot/tree/0974c6cd319506236280f48153c622c0c75ea896/src-tauri/src-crates/app-scroll-screenshot-service)：持續擷取、背景匹配、畫面位移和縮圖預覽。rainshot 以 OpenCV ORB 與額外像素驗證獨立實現。
- [AT-SPI 座標查詢](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Component.get_accessible_at_point.html)、[可見元件範圍](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Component.get_extents.html) 與 [應用行程 ID](https://gnome.pages.gitlab.gnome.org/at-spi2-core/libatspi/method.Accessible.get_process_id.html) 是 Linux 控件探測的依據；瀏覽器必須提供 AT-SPI，Canvas 或未暴露的 DOM 無法保證取得。
- [RapidOCR 1.4.4](https://github.com/RapidAI/RapidOCR/tree/v1.4.4)、[FFmpeg x11grab](https://ffmpeg.org/ffmpeg-devices.html#x11grab)、[ZBar C API](https://github.com/mchehab/zbar/blob/master/include/zbar.h) 為新增功能所用上游介面。

0.4.2 補充參考：[Snow Shot 翻譯類型](https://github.com/xiaofeiTM233/snow-shot/blob/0974c6cd319506236280f48153c622c0c75ea896/src/types/servies/translation.ts) 列出 Qwen Turbo / Plus / Max；這些選項經 Snow Shot 自有後端，不等於阿里雲免金鑰 API。rainshot 直接使用 [阿里雲官方協議](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。

## 0.4.2 互動更新

- `translated_overlay.py` 保留選取字元對應的 OCR 行、原圖座標，逐行以既有 TranslationJob 請求；序列可取消，整批 120 秒，全部成功後才套用。字型盡量符合原行高度與寬度，建立譯文字元幾何以支援原位選取。
- `FloatingShot.render_image()` 統一顯示、取色、複製、QR、儲存與以圖搜圖的可見影像。原始 Document 不因單純切換譯文而變更；加入標註時把譯文合入可撤銷歷史。
- 文字編輯使用透明、零邊距的原位 QPlainTextEdit，保留輸入法與編輯能力。確認後使用同字型與零邊距 QTextDocument 繪製；Enter 確认、Shift+Enter 換行。
- 設定有獨立「截圖後按鍵」頁面。套用後重建視窗 QShortcut，不抓取其他應用的按鍵；編輯文字期間暫停功能鍵。
- 失焦關閉先沿 QObject 父鏈檢查 activeWindow，將自己的提示、放大鏡與附屬視窗視為同一次互動。
