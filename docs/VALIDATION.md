# rainshot 0.4.7 驗證

## GitHub 公開發布準備 / Public release preparation

2026-10-18：在原有 Mint / Cinnamon / X11 主機執行完整 offscreen 回歸，
**329 項通過（29.17 秒）**。相較 10 月 3 日增加三項封裝回歸：公開來源可重現且排除本機
QA 資料、安裝樹的啟動器可從倉庫外執行並保留授權、Arch 配方固定來源 SHA-256。

完整性掃描僅選取應用、測試、建包腳本、公開 Markdown 與 `docs/assets/` 示範圖；
未將舊的本機截圖、JSON 測試紀錄、設定、瀏覽器 profile、模型或憑證納入。
README 新示範圖是隔離設定下產生的合成內容，已目視確認。

On 2026-10-18 the complete local suite passed **329 tests in 29.17 s**. New
packaging checks cover reproducible public source, excluding machine-local QA
data, staged launcher/license preservation and checksum-pinned Arch recipes.
The application runtime is unchanged from the previously tested 0.4.7 baseline.

GitHub Actions additionally builds and checks Ubuntu, Arch and Fedora packages;
the result of each actual workflow run is authoritative. Container builds and
offscreen tests do not establish native desktop/Wayland compatibility. See
[COMPATIBILITY.md](COMPATIBILITY.md) and [RELEASING.md](RELEASING.md).

## 2026-10-03 開發版基線 / Development baseline

2026-10-03：`/usr/bin/python3 -m pytest -q --tb=short` **326 項通過**（29.38 秒）。完整回歸涵蓋多元素共同外框、局部搜尋邊界、網格間隙靠邊位置、父框裁切及選區預選 / Tab 流程，並保留桌面輔助功能、保存、翻譯、OCR、IPC 等既有測試。

## 多元素間隙選區

0.4.7 將間隙共同選區擴充為完整局部群組，驗證三個、四個、五個元素、L 形、網格與寬高不同的混合排列。共同外框以所有成員的最左、最上、最右、最下邊界計算；搜尋區域只需與成員相交，容許寬 500 px 或高 600 px 的成員完整加入。仍檢查可見性、保留父框裁切，不因成員增加而擴大搜尋區域。完整群組先被預選，Tab 可再選更大的父層；直接命中單一元素則維持單元素選區。

回歸另檢查不同網格間距及游標在間隙中心 / 靠邊的位置，避免偏移後把鄰近四格擴成六格或九格。選區提示改為「指向控件或元素間隙」，讓共同選區入口更容易發現。

原生 Chromium / Firefox fixture 的 42 個元素範圍均精確命中，10 組新增共同外框均完整預選並通過 Tab 父層切換。每個瀏覽器測試三元素 L 形、四元素網格、四元素不規則排列、高 600 px 的混合成員、寬 500 px 的混合成員。Firefox 仍透過私有 session 啟用桌面輔助功能；測試前後使用者桌面設定與 X11 根屬性保持不變。測試只使用自有臨時 profile 與本機 fixture，沒有操作使用者網頁。

本輪完整回歸、原生 fixture 與安裝包的結果記錄在交付驗證 JSON。下方 0.4.6 的測試數與耗時保留為已發布歷史，不代表本輪執行結果。

## 0.4.6 已發布驗證

2026-10-03：`/usr/bin/python3 -m pytest -q --tb=short` **307 項通過**（29.10 秒）。新增桌面啟用協議、GUI 按鈕、逾時 / 錯誤 / 釋放、GTK viewport、深層容器、兄弟預算、相關 renderer、首次延遲重試與相鄰元素共同選區的回歸。

## Firefox 與桌面輔助功能

目前桌面 `IsEnabled=false`、`ScreenReaderEnabled=false`，GNOME 與 Cinnamon 的 toolkit-accessibility 都為 false。原生預設 Firefox 測試沒有 AT-SPI 應用節點，因此不是幾何匹配失敗。獨立 D-Bus session 使用 memory GSettings，經生產 `DesktopAccessibility.enable()` 非同步啟用並驗證 `IsEnabled=true`，朗讀保持 false。未修改瀏覽器 accessibility 偏好或添加強制環境旗標；重開自有的臨時 Firefox profile 後，按鈕、圖片、卡片、文章四項精確命中，合成背景的原生全螢幕選區也通過按鈕 / 圖片識別與 Tab 父層切換。

此測試啟動私有 accessibility launcher 時不提供 DISPLAY，避免變更使用者 X11 的 `AT_SPI_BUS` 根屬性。測試前後檢查實際 GNOME / Cinnamon 設定與根屬性，全部保持不變；僅實際按下設定裡的啟用按鈕會更改桌面狀態。

## GTK / Qt 通用控件

`tests/desktop_toolkit_snap.py` 每個 toolkit 建立兩個自有視窗，測試按鈕、輸入欄、標籤、文字編輯器、清單可見列、清單空白區、樹狀控件、巢狀按鈕、第 84 個兄弟按鈕、第二視窗按鈕及按鈕 / 輸入欄之間的共同外框。清單與樹只透過自有控件 API 捲動至第 84 項，沒有操作使用者滑鼠。

GTK 3 首次測試清單列與空白區漏選：GtkViewport 原點為 -2147483648，缺少 SHOWING，但螢幕內子列仍回傳正確座標。修正此結構容器後 **11 / 11 通過**。只跳過無效 viewport 的範圍，保留父 scroll pane 裁切；不可見或無效的實際控件仍排除。

Qt 5 在桌面未啟用輔助功能時沒有可用控件樹；私有 session 啟用 IsEnabled 後，預設 Qt fixture **11 / 11 通過**，未強制 QT_ACCESSIBILITY 或 QT_LINUX_ACCESSIBILITY_ALWAYS_ON。Qt 5 從現有 X11 根屬性取得 bridge 地址，因此這項隔離測試只將 Qt 查詢指向未改動的真實 bridge，以找到自有 fixture；其啟用狀態仍來自私有 session。這是測試路由處理，生產程式沒有新增特殊 Qt bus 或啟動參數。

## Chromium 與限制

0.4.6 重新執行未加強制 accessibility 參數的本機 Chromium fixture：四類元素精確命中，首次查詢 109 ms，卡片 / 文章間隙取得兩者共同外框，選區覆蓋後的共同外框預選與 Tab 父層切換通過。Firefox 同樣通過垂直間隙選區，GTK / Qt 通過水平間隙。單元測試另檢查隱藏元素、過遠 / 未對齊元素、游標直接命中元素不合併、最近的一對及父框裁切。完整結果見 0.4.6 交付驗證 JSON。

Canvas、沒有公開的元素、自繪控件仍可能回退至視窗。這次沒有讀取使用者 Firefox profile，也沒有在每種實際第三方軟體逐一驗證；Wayland 與混合 DPI 未新增實測。

## 0.4.5 已發布驗證

2026-10-02：`/usr/bin/python3 -m pytest -q --tb=short` **265 項通過**（28.17 秒）。保存相關測試 59 項通過，輔助功能 / Snap / 選區測試 70 項通過。完整回歸也確認譯文仍寫入保存圖片；保存後貼圖已關閉，原文還原另在保存前獨立驗證。

## 保存後關閉貼圖

原生 Cinnamon / X11 的 `native_save_lifecycle.py` 檢查釘住與未釘住貼圖：保存後立即隱藏，實際處理 `DeferredDelete` 後貼圖已銷毀，無父貼圖的通知仍顯示。原生通知接受輸入但不接受焦點；對測試自己的通知送出 Qt 滑鼠事件，回調取得正確資料夾 URL，點擊與逾時後通知都釋放。影像、設定與保存路徑使用隔離資料；檔案管理器呼叫使用 mock。不是使用者桌面的實體滑鼠測試。

回歸涵蓋保存按鈕與快捷鍵、PNG / JPEG / WebP、取消與失敗保留貼圖、通知取代及角落快照、開啟資料夾失敗提示。開始新截圖與錄製前清除獨立保存通知，避免將提示擷取到畫面；回歸確認貼圖已銷毀後，開始新截圖仍清除並釋放通知。錄製成功不重新顯示或啟用即將關閉的貼圖，其他原先隱藏的貼圖正常恢復。

## Chromium 實際原因與修正

對目前開啟的 Chromium 做只讀 AT-SPI / X11 後端測試，首次角色統計只有 application 與 12 個 frame，沒有網頁元素。對命中視窗做正常 `getRelationSet()` 查詢後，出現 document web、image、link、section。生產程式現在對選定根視窗做同樣查詢，丟棄關係內容；更新快取，冷啟動空樹最多等待 240 ms，仍受 800 ms 內部預算與 1,500 ms 子行程逾時限制。

目前 Chromium 的 6 個圖片 / 連結中心後端查詢中，5 個返回完全一致的元素範圍（78–104 ms），1 個頁首連結返回重疊區塊。測試點被其他原生視窗遮擋，因此測試中僅把目標 Chromium 保留在視窗候選裡；未抬升或操作使用者視窗。這驗證目標瀏覽器後端，不能當成目前桌面最上層選區介面的完整實測。沒有讀取頁面文字、網址、使用者 profile，亦沒有進行 bilibili / YouTube 的指定頁面導航。

`tests/desktop_browser_snap.py` 在隔離 Chromium profile、本機固定幾何 HTML 通過，**未使用 `--force-renderer-accessibility`**。先讓頁面完成顯示，再由生產 `SnapProbe` 做首次查詢，沒有先讀取 AT-SPI 名稱來預熱；首次取得頁面範圍，耗時 110 ms。之後按鈕、圖片、卡片與文章區塊均精確命中並含父候選；原生全螢幕選區覆盖後，按鈕 / 圖片識別與 Tab 切換父層也通過。使用合成背景與固定 hover 座標，沒有匯出桌面畫面或操作使用者滑鼠。

根節點搜尋的回歸另涵蓋非元件容器、慢速無關行程、慢速根節點兄弟、有界發現預算、關係查詢失敗及剩餘時間不足。Canvas、沒有公開的 DOM、重疊內容仍不保證精確；Wayland 與實體混合 DPI 桌面未新增實測。

## 0.4.4 已發布驗證

2026-10-01：`/usr/bin/python3 -m pytest -q --tb=short` **231 項通過**（28.19 秒），其中保存提示與保存路徑的兩份測試共 **39 項通過**。測試涵蓋保存按鈕與 Ctrl+S、設定持久化及即時生效、PNG / JPEG / WebP 副檔名、取消不寫入、不改動預設資料夾、提示開啟本次實際位置，以及可點擊 / 穿透提示切換時的原生 Qt 輸入旗標。

新增 **57 項**自動選區測試：AT-SPI 可見性、深層命中補父鏈、父容器裁切、有限子節點回退、同 UID 的瀏覽器 renderer、冷啟動 / 取消 / 逾時、過期與重入結果、physical / logical 高 DPI 座標、滑鼠移動不重置已辨識元素、Tab 保留與移到新元素後重查、Shift 釋放恢復、停用設定及跨螢幕視窗。

原生 Cinnamon / X11：`tests/desktop_save_v044.py` 通過，確認「普通提示 → 保存提示 → 普通提示 → 再保存」的真實 XTest 點擊，底層測試視窗收到兩次穿透事件，兩次可點提示則送出正確資料夾。未釘住貼圖的 XInput 外部點擊監聽不會先誤關閉貼圖。檔案管理器呼叫使用 mock，沒有開啟外部程式。

`tests/desktop_browser_snap.py` 在獨立 Chromium profile 的本地 HTML 通過：按鈕、圖片、卡片與文章區塊均得到精確幾何及父候選，原生全螢幕選區介面覆蓋瀏覽器後仍可識別，Tab 父層切換與移至圖片重查通過。瀏覽器明確啟用 renderer accessibility；測試使用合成背景及固定 hover 輸入，沒有匯出桌面畫面、讀取使用者 profile 或造訪外部網頁。這不能代表所有瀏覽器的預設設定皆會公開網頁元素；未提供 AT-SPI 的頁面、Canvas 內容仍以視窗回退及手動拖曳為主。

完整測試需要本機 HTTP、D-Bus 與 IPC socket 權限；正式結果在允許這些本機連線的環境執行。此版本沒有改動系統安裝。

## 0.4.3 既有驗證

2026-09-16 的工作區修正：`python3 -m pytest -q` **167 項通過**。`tests/desktop_workspace.py` 在原生 Cinnamon / X11 確認貼圖是 `_NET_WM_WINDOW_TYPE_NORMAL`、位於當前工作區、沒有 sticky 狀態、保持置頂且要求不顯示於工作列；使用視窗管理器把測試貼圖移至相鄰工作區後，`_NET_WM_DESKTOP` 正確更新。`tests/desktop_v03.py` 的工具列、失焦、彈出選單與快捷鍵回歸通過。尚未以實體滑鼠完成「按住貼圖後按左右鍵」手勢測試；Wayland 工作區拖曳仍由桌面合成器決定。

2026-09-09～12，Linux Mint / Cinnamon X11，Python 3.10、Qt 5.15。測試使用合成影像與隔離的設定、快取、HTTP 及 D-Bus 服務。

## 完整回歸

`PYTHONPATH=. python3 -m pytest -q tests`：**165 項通過**。

覆蓋既有影像處理、OCR 選取、IPC 延遲斷線、Portal 協議、設定、翻譯供應商協議、捲動接合、QR、錄製資源管理及 0.4.1 功能。新增檢查：

- 預設翻譯 T、複製色碼 C、文字 X；自訂、解除、恢復預設、按鍵衝突與保留鍵驗證；已開啟貼圖立即換綁、提示更新。
- 滑鼠點擊、Enter、預設 C 與自訂按鍵複製色碼後，立即退出取色、關閉放大鏡，保留貼圖。
- 選中色標記與大小滑軌、標註列內上一步 / 下一步、Ctrl+Z / Ctrl+Shift+Z；移除移動與裁切按鈕；關閉標註列後不再繪圖。
- 透明文字編輯，Enter 確認、Shift+Enter 換行、中文輸入法提交；文字編輯期間不触發功能鍵，確認前後文字位置一致。
- OCR 行與部分文字選取的翻譯覆蓋、依實際字形高度配對與寬度限制、未選區不變、譯文選取 / 複製 / 匯出 / 還原、翻譯後取色與可撤銷標註。
- 翻譯逐行順序、取消後不套用延遲結果、切换工具取消請求；自己的附屬提示不被當成外部視窗，真正外部失焦仍關閉臨時貼圖。

無沙箱網路權限時，本機 socket 測試會失敗；正式結果使用允許本機 IPC 的執行環境。未為測試安裝系統套件，OpenCV 開發依賴位於工作資料夾。

## 原生桌面

`tests/desktop_v042.py` 通過，詳見 `native-v042.json`：

- 用 T 啟動兩行本機 HTTP 模擬翻譯，譯文顯示在 OCR 原位置。選取、複製、儲存及原文還原均通過。
- 原生箭頭標註、選色、滑軌、上一步 / 下一步與關閉標註列測試通過。
- 在圖片上用輸入法事件提交中文字，Shift+Enter 換行，Enter 確認。
- 在設定欄實際錄入 F6，套用後同一張貼圖立即使用新按鍵，角落提示與工具提示同步。
- 已查看 `translated-shot.png`、`inline-text-editing.png`、`annotations-confirmed.png`、`local-shortcut-settings.png`，確認譯文與編輯文字的位置、色彩及工具列。

翻譯服務為本機模擬服務，本輪沒有使用付費金鑰或對外傳送截圖。原生 UI 測試使用字型實際字形範圍建立已知字框。另外已執行 `tests/real_translation_ocr.py`：實際 Tesseract 識別兩行合成文字，依真實 OCR 字框完成本機 HTTP 翻譯、原位選取與 Ctrl+C，暫存檔已清理，見 `translation-pipeline.json`。長截與錄製沿用前版實測基線。現有 `desktop_v03.py` 另檢查原生下拉選單、釘住工具列、圖片原點及全域快捷鍵。

## 安裝包

`tests/package_smoke.py` 檢查解開的安裝包：版本、背景啟動、設定 / 記錄 / 圖片 IPC、16 次連線、斷線後等待 2.4 秒、正常退出；詳細結果放在交付的驗證 JSON。

仍未提供 Wayland 連續長截與 GIF / WebP 錄製；本輪沒有實體 Wayland 或混合 DPI 桌面驗證。原位翻譯以原文字框排版，長句會縮小；複雜圖片背景使用邊緣取樣色覆蓋，沒有重建原背景。
