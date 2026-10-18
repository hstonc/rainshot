# Build and install / 建置與安裝

Python 3.10+ and a graphical Linux desktop are required. Distribution packages are
preferred: PyQt5, Qt SVG/Wayland plugins and AT-SPI depend on native system libraries.
The release source archive and native packages do not bundle those runtimes or OCR models.

需要 Python 3.10+ 與圖形桌面。建議使用發行版套件提供 PyQt5、Qt SVG／Wayland
外掛及 AT-SPI；來源壓縮包和原生安裝包均不內附這些執行環境或 OCR 模型。

## Native dependencies / 系統依賴

Ubuntu / Mint / Debian:

```bash
sudo apt install python3-pyqt5 python3-pyqt5.qtsvg python3-numpy python3-opencv \
  python3-pyatspi libqt5svg5 qt5-image-formats-plugins qtwayland5 libx11-6 libxi6 libxtst6 libzbar0 ffmpeg
```

Arch Linux (experimental / 實驗性):

```bash
sudo pacman -S python python-pyqt5 python-numpy python-opencv python-atspi \
  qt5-svg qt5-imageformats qt5-wayland libx11 libxi libxtst zbar ffmpeg
```

Fedora (experimental / 實驗性):

```bash
sudo dnf install python3 python3-qt5 python3-numpy python3-opencv python3-pyatspi \
  qt5-qtsvg qt5-qtimageformats qt5-qtwayland libX11 libXi libXtst zbar ffmpeg-free
```

Fedora needs the complete `python3-qt5`, not just `python3-qt5-base`, for QtSvg.
For Wayland also install `xdg-desktop-portal` and the backend for your desktop
(GNOME, KDE, etc.). The portal controls its own permission and selection UI.

Fedora 的 QtSvg 需完整 `python3-qt5`；只有 `python3-qt5-base` 不足。
Wayland 還需要 `xdg-desktop-portal` 及對應桌面的後端（例如 GNOME／KDE）。
授權與選區介面由該桌面提供；這不會啟用 rainshot 尚未實作的錄製或長截。

From an extracted source release / 解開來源後:

```bash
./run.sh
./run.sh --diagnose
```

Optional OCR: install `tesseract` and the language data packages for your distribution.
RapidOCR's separate virtual environment is documented in [the user guide](USER_GUIDE.zh-TW.md).
Do not run the desktop application as root.

可選 OCR：安裝發行版的 Tesseract 與所需語言包；RapidOCR 獨立環境見
[使用指南](USER_GUIDE.zh-TW.md)。桌面程式請以一般使用者執行。

## Build native packages / 建立原生套件

```bash
# No root or network required after build tools are installed.
# 安裝建包工具後，此步不需 root 或下載依賴。
python3 packaging/build_release.py dist
```

This creates the public source, checksum-pinned Arch recipe bundle and Debian
package. `--source-only` omits Debian so the generator works on other distributions.
It excludes local test captures, machine-specific JSON reports, credentials,
bytecode and build caches. `SHA256SUMS` covers files at the output directory root.

產出來源、固定 SHA-256 的 Arch 配方與 Debian 套件；`--source-only` 可在非 Debian
系統略過 `.deb`。生成器排除本機測試截圖、機器特定 JSON、憑證、位元碼與快取。

Arch native package, inside Arch / 在 Arch 原生建包:

```bash
python3 packaging/build_release.py dist --source-only
cd dist/arch-build
makepkg -si
```

Use a regular account with Arch build tools. The generated recipe uses an exact
source hash, and the generator puts a local copy beside it; no source `SKIP` hash.
`.SRCINFO` can be regenerated using `makepkg --printsrcinfo > .SRCINFO`.

請用一般帳號並先安裝 Arch 建包工具。配方固定來源雜湊，生成器也把本機來源放在旁邊，
不使用 `SKIP` 跳過驗證。尚未上架 AUR。

Fedora RPM, inside Fedora / 在 Fedora 建立 RPM:

```bash
sudo dnf install rpm-build python3
python3 packaging/build_release.py dist --source-only
mkdir -p "$PWD/rpmbuild"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
cp dist/rainshot-0.4.7-source.tar.gz rpmbuild/SOURCES/
rpmbuild -ba --define "_topdir $PWD/rpmbuild" packaging/rpm/rainshot.spec
```

Install the runtime dependencies above before running the RPM build's import check.
The spec targets Fedora package names; it is not a promise that the RPM resolves
on every RPM-based distribution. `all`/`any`/`noarch` describe application files,
not cross-platform validation. See [COMPATIBILITY.md](COMPATIBILITY.md).

RPM 建包的匯入檢查需先裝好上述執行依賴。spec 針對 Fedora 套件名稱，
不能保證直接用在所有 RPM 發行版；封裝架構名稱不等同所有平台實測。

## Tests / 測試

On Ubuntu/Mint, additional test tools / Ubuntu/Mint 額外測試工具:

```bash
sudo apt install python3-pytest python3-qrcode python3-pil python3-dbus python3-gi dbus
PYTHONPATH=. /usr/bin/python3 -m pytest -q
```

Tests use offscreen Qt, temporary settings, loopback HTTP and private D-Bus/IPC
sockets. A sandbox that denies local sockets cannot run the entire suite.
The optional `tests/desktop_*.py` scripts use owned test windows and require a
real desktop; they are not run by headless CI.

測試使用 offscreen Qt、暫存設定、本機 HTTP 與私有 D-Bus／IPC；禁止本機 socket
的沙箱無法執行完整測試。`tests/desktop_*.py` 是需圖形桌面的可選實測，
不會在無桌面 CI 中自動執行。

## Packaging boundaries / 封裝範圍

No AppImage or Flatpak is currently shipped. The app uses desktop AT-SPI, X11
helpers and external FFmpeg/OCR tools; sandboxing and bundling require separate
integration and license work. A source archive is not advertised as a portable
single-file binary. Build success alone does not verify Wayland behavior.

目前不提供 AppImage／Flatpak；桌面 AT-SPI、X11 輔助介面與外部 FFmpeg／OCR 工具
需要另做沙箱整合和執行環境授權處理，不能把來源壓縮包宣稱為免依賴單檔版。

Package-name references, checked 2026-10-18 / 套件名稱查核來源：
[Arch PyQt5](https://archlinux.org/packages/extra/x86_64/python-pyqt5/),
[Arch AT-SPI](https://archlinux.org/packages/extra/any/python-atspi/),
[Arch OpenCV](https://archlinux.org/packages/extra/x86_64/python-opencv/),
[PKGBUILD format](https://man.archlinux.org/man/core/pacman/PKGBUILD.5),
[Fedora PyQt5](https://packages.fedoraproject.org/pkgs/python-qt5/python3-qt5/),
[Fedora OpenCV](https://packages.fedoraproject.org/pkgs/opencv/python3-opencv/),
[Fedora AT-SPI](https://packages.fedoraproject.org/pkgs/pyatspi/python3-pyatspi/).
