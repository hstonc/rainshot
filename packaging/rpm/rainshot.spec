Name:           rainshot
Version:        0.4.7
Release:        1
Summary:        Linux screenshot, floating annotation and local OCR tools
License:        GPL-3.0-or-later
URL:            https://github.com/hstonc/rainshot
Source0:        https://github.com/hstonc/rainshot/releases/download/v%{version}/rainshot-%{version}-source.tar.gz
BuildArch:      noarch
BuildRequires:  python3
Requires:       python3 >= 3.10
Requires:       python3-qt5
Requires:       python3-numpy
Requires:       python3-opencv
Requires:       python3-pyatspi
Requires:       qt5-qtsvg
Requires:       qt5-qtimageformats
Requires:       qt5-qtwayland
Requires:       libX11
Requires:       libXi
Requires:       libXtst
Requires:       zbar
Requires:       /usr/bin/ffmpeg
Recommends:     xdg-desktop-portal
Recommends:     tesseract

%description
Region capture, floating images, annotations, local OCR and translation.
X11 is the primary target. Wayland screenshot capture uses the desktop portal;
continuous scrolling capture and GIF/WebP recording are X11-only in this release.
Fedora packaging is experimental; a container build is not a desktop test.

%prep
%setup -q

%build
# Python source; no bundled native runtime or third-party models.

%install
python3 packaging/install_tree.py --destdir "%{buildroot}" --prefix /usr

%check
QT_QPA_PLATFORM=offscreen PYTHONPATH="%{buildroot}/usr/lib/rainshot" python3 -m rainshot --version

%files
/usr/bin/rainshot
/usr/lib/rainshot
%{_datadir}/applications/io.github.rainshot.rainshot.desktop
%{_datadir}/icons/hicolor/scalable/apps/io.github.rainshot.rainshot.svg
%doc %{_datadir}/doc/rainshot
%license %{_datadir}/licenses/rainshot

%changelog
* Sun Oct 18 2026 rainshot contributors - 0.4.7-1
- Initial public Fedora package; experimental desktop support.
