# 發布流程 / Releasing

更新日期 / Updated: **2026-10-18**.

## 中文

### 自動驗證與首次發布

[Linux packages and release](../.github/workflows/ci.yml) 在 `main` 的 push、pull request 及 Actions 頁面的手動 `workflow_dispatch` 執行。所有建置工作預設只有 `contents: read`，只有最後的發布工作取得 `contents: write`。PR 不會進入發布工作，也沒有使用 `pull_request_target`。

流程如下：

1. 從 `rainshot/__init__.py` 讀版本，產生對應的來源壓縮包和含 SHA-256 的 Arch 建置配方。
2. Ubuntu 22.04 與 24.04 各執行完整 headless pytest，再建置、安裝 `.deb`，從倉庫以外的目錄檢查系統套件中的執行依賴、PNG / JPEG / WebP 寫入讀回和 `--diagnose`。
3. 在官方 `archlinux:base-devel` 容器以一般使用者執行 `makepkg`，安裝 `.pkg.tar.zst` 並檢查 PyQt5 / QtSvg、NumPy、OpenCV、pyatspi 和應用匯入及診斷。配方與來源 tar 放在同一資料夾，避免首次 Release 尚不存在而下載失敗。
4. 在官方 Fedora 44 容器建置 binary / source RPM，安裝 RPM 並執行相同類型的匯入和診斷檢查。
5. 全部成功後，只有 `hstonc/rainshot` 的當前 `main` commit 可以發布；已被更新的 commit 不會搶先發布舊產物。
6. 若同版本 Release（包括 draft）已存在，保持原狀並略過。若已有同名 tag 卻指向別的 commit，工作失敗，不會移動 tag。
7. 建立指向已驗證 commit 的 draft Release，上傳完整產物與 `SHA256SUMS`，成功後才公開。沒有 `--clobber` 或覆寫已發布檔案的步驟。

GitHub-hosted runner 的內建 `GITHUB_TOKEN` 用於這個發布工作，不需要把個人 GitHub token 寫入專案。倉庫須允許 GitHub Actions 執行及該工作的 contents 寫入權限；若組織原則禁止此權限，需由倉庫管理者調整政策，不能把金鑰放進程式繞過。

### 產物及驗證範圍

| 產物 | 來源與用途 |
|---|---|
| `rainshot-VERSION-source.tar.gz` | 對應來源、文件及建置腳本。 |
| `rainshot-VERSION-arch-build.tar.gz` | `PKGBUILD` 和 `.SRCINFO` 建置配方目錄，另需同頁的來源 tar。 |
| `rainshot_VERSION_all.deb` | 發布 Ubuntu 22.04 job 的 `.deb`；24.04 job 也會獨立建置和驗證，但避免上傳同名重複產物。 |
| `rainshot-VERSION-RELEASE-any.pkg.tar.zst` | Arch 官方容器內由 makepkg 產生的套件。 |
| `rainshot-VERSION-RELEASE.fc44.noarch.rpm` | Fedora 44 容器建置的 RPM，實際 release 後綴以產物為準。 |
| `rainshot-VERSION-RELEASE.fc44.src.rpm` | 對應的 RPM spec 與來源。 |
| `SHA256SUMS` | 同一 Release 全部上述附件的 SHA-256，下載後以 `sha256sum --check SHA256SUMS` 驗證。 |

CI 的 Arch / Fedora 工作證明容器中的建置、依賴解析、安裝、匯入與無桌面診斷成功，**不代表在 Arch / Fedora 真實桌面上完成截圖、Wayland、視窗、輸入法或螢幕配置實測**。Ubuntu offscreen 測試也不代表原生 Wayland 已驗證。請保留 [COMPATIBILITY.md](COMPATIBILITY.md) 的實測 / 未測區別。

Fedora `python3-qt5-base` 不含 QtSvg 綁定，因此使用 `python3-qt5` 和 `qt5-qtsvg`。其他執行依賴包括 `python3-opencv`、`python3-pyatspi`、`qt5-qtwayland`、`ffmpeg-free` 和 `zbar`；FFmpeg 可用編碼器仍依發行版建置而定。Arch 使用 `python-opencv` 提供 `cv2`、`python-atspi` 提供 `pyatspi`，不以一般 `opencv` 套件是否存在來推斷 Python 綁定。WebP 靜態圖片另需 Qt 圖片插件：Ubuntu 的 `qt5-image-formats-plugins`、Arch 的 `qt5-imageformats`、Fedora 的 `qt5-qtimageformats`，三個平台的執行檢查都會實際寫入再讀回。套件名稱查核於 2026-10-18，來源為 [Fedora Qt 套件檔案](https://packages.fedoraproject.org/pkgs/python-qt5/python3-qt5/fedora-44.html)、[Fedora OpenCV](https://packages.fedoraproject.org/pkgs/opencv/python3-opencv/)、[Arch Python OpenCV](https://archlinux.org/packages/extra/x86_64/python-opencv/)、[Arch AT-SPI](https://archlinux.org/packages/extra/any/python-atspi/)、[Arch 圖片插件](https://archlinux.org/packages/extra/x86_64/qt5-imageformats/files/)。

### 之後發布新版本

先同步程式版本、`pyproject.toml`、翻譯 User-Agent、RPM spec、文件及版本相關測試；讓程式與所有包裝版本相同，再送到 `main`。工作流程會從程式版本決定 `vVERSION`，不必另外推 tag 才能開始。

本機可先執行：

```sh
PYTHONPATH=. /usr/bin/python3 -m pytest -q --tb=short
/usr/bin/python3 packaging/build_release.py dist
```

只產生來源與 Arch 配方時：

```sh
/usr/bin/python3 packaging/build_release.py dist --source-only
```

若建置失敗，修正後 push 或重新執行 workflow；尚未建立 Release 時不會公開半套附件。若上傳或公開動作失敗，draft 可能留下；流程為避免覆寫會略過它。維護者應先檢查失敗原因與 draft 的附件，必要時手動移除未發布的 draft 後重跑。不要刪除或取代已發布版本的附件來悄悄更換內容；功能或內容更動應使用新版本。

## English

The [Linux packages and release workflow](../.github/workflows/ci.yml) runs on pushes to `main`, pull requests and manual dispatch. Build jobs have read-only repository access. Only the final release job has `contents: write`; pull requests cannot publish.

The workflow produces matching source and a checksum-pinned Arch recipe, runs the complete headless suite and Debian package installation checks on Ubuntu 22.04 / 24.04, builds an Arch package as an unprivileged user in the official Arch container, and builds binary / source RPMs in Fedora 44. Packages are installed and checked for actual runtime imports, PNG / JPEG / WebP round trips and `--diagnose` outside the source checkout.

After every check passes, only the current `main` commit in `hstonc/rainshot` can publish. Existing releases, including drafts, are left unchanged. A conflicting tag fails the job instead of moving it. The job creates a draft targeted at the verified commit, uploads source, the Arch recipe, Debian / Arch / Fedora packages, source RPM and `SHA256SUMS`, then publishes the draft. It never uses asset overwrite flags. The Debian asset comes from Ubuntu 22.04; Ubuntu 24.04 is independently checked.

Container builds and offscreen tests do not establish native desktop, Wayland, input-method or monitor-layout compatibility. Keep the distinction in [COMPATIBILITY.md](COMPATIBILITY.md). These packages use system runtimes rather than bundling third-party libraries or OCR models.

The release job uses GitHub's built-in `GITHUB_TOKEN`, not a personal token embedded in the project. Repository / organization policy must allow Actions and the job's contents permission. `workflow_dispatch` allows retrying without relying on tag-push triggers. A push made by a connector can start this workflow through an ordinary main-branch update.

For a new version, synchronize application and package versions, metadata, RPM spec, translation User-Agent, tests and documentation before pushing to `main`. The workflow derives `vVERSION` from the application; a pre-existing tag is unnecessary. Use `python3 packaging/build_release.py dist` locally, or add `--source-only` to generate just the source and Arch recipe.

If package building fails, no release is published. If asset upload or publication fails after draft creation, inspect the draft; the next run intentionally skips it. A maintainer may remove an incomplete unpublished draft and rerun after fixing the cause. Published assets must not be silently replaced; use a new version for changed contents.
