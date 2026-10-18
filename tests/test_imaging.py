import numpy as np
import pytest
from PyQt5.QtCore import QRect, QRectF, QPoint
from PyQt5.QtGui import QImage, QColor
from rainshot.imaging import (Document, Mark, ScreenTile, compose_tiles, anchor_geometry,
    stitch_pair, find_overlap, load_image, save_image, check_size, rgb_array)


def from_array(a):
    a = np.ascontiguousarray(a, dtype=np.uint8)
    return QImage(a.data, a.shape[1], a.shape[0], a.strides[0], QImage.Format_RGB888).copy()


def test_annotation_crop_undo_redo(image):
    doc = Document(image)
    doc.add(Mark("redact", ((10, 10), (80, 60))))
    assert doc.render().pixelColor(20, 20).name() == "#161d25"
    assert doc.crop(QRectF(5, 5, 100, 90))
    assert doc.render().size().width() == 100
    assert doc.undo()
    assert doc.render().width() == 640
    assert doc.render().pixelColor(20, 20).name() == "#161d25"
    assert doc.undo()
    assert doc.render().pixelColor(20, 20).name() == "#ffffff"
    assert doc.redo()
    doc.add(Mark("number", ((100, 100),), text="1"))
    assert not doc.redo()


@pytest.mark.parametrize("kind", ["rect", "ellipse", "arrow", "line", "pen", "highlight", "text", "number", "redact"])
def test_tools_change_pixels(kind, image):
    doc = Document(image)
    doc.add(Mark(kind, ((50, 50), (150, 150)), text="Test" if kind == "text" else "1"))
    assert not np.array_equal(rgb_array(image), rgb_array(doc.render()))


def test_mosaic_is_flattened_and_redaction_exact(tmp_path, app):
    rng = np.random.default_rng(5)
    base = from_array(rng.integers(0, 256, (160, 200, 3), dtype=np.uint8))
    doc = Document(base)
    doc.add(Mark("mosaic", ((20, 20), (120, 120)), width=4))
    a = rgb_array(doc.render())
    assert np.array_equal(a[0:20], rgb_array(base)[0:20])
    assert len(np.unique(a[20:120, 20:120].reshape(-1, 3), axis=0)) <= 100
    doc.add(Mark("redact", ((30, 30), (100, 100))))
    path = tmp_path / "export.png"
    save_image(doc.render(), path)
    reopened = load_image(path)
    assert np.all(rgb_array(reopened)[30:100, 30:100] == [22, 29, 37])
    assert np.array_equal(rgb_array(reopened), rgb_array(doc.render()))


def test_atomic_save_and_errors(tmp_path, image):
    path = tmp_path / "output.png"
    save_image(image, path)
    assert path.stat().st_size < 10000, "Flat PNG should be losslessly compressed"
    original = path.read_bytes()
    with pytest.raises(ValueError):
        save_image(image, tmp_path / "bad.txt")
    assert path.read_bytes() == original
    with pytest.raises(OSError):
        save_image(image, tmp_path / "missing" / "out.png")
    with pytest.raises(ValueError):
        load_image(tmp_path / "absent.png")
    with pytest.raises(ValueError):
        check_size(100000, 100000)


def test_negative_origin_mixed_dpi(app):
    left = QImage(200, 200, QImage.Format_ARGB32)
    left.fill(QColor("red"))
    right = QImage(200, 200, QImage.Format_ARGB32)
    right.fill(QColor("blue"))
    left.setDevicePixelRatio(2)
    tiles = [ScreenTile(QRect(-100, 0, 100, 100), left), ScreenTile(QRect(0, 0, 200, 200), right)]
    result = compose_tiles(tiles, QRect(-50, 0, 100, 80))
    assert (result.width(), result.height()) == (200, 160)
    assert result.pixelColor(99, 40).name() == "#ff0000"
    assert result.pixelColor(100, 40).name() == "#0000ff"
    assert result.devicePixelRatio() == 1


@pytest.mark.parametrize("point", [QPoint(0, 0), QPoint(331, 215), QPoint(790, 590)])
def test_pin_cursor_anchor_no_cumulative_drift(point):
    old = QRect(-40, -30, 800, 600)
    cursor = old.topLeft() + point
    rx = point.x() / old.width()
    ry = point.y() / old.height()
    new = anchor_geometry(old, cursor, 1043, 782)
    assert abs((cursor.x() - new.x()) - rx * new.width()) <= .5
    assert abs((cursor.y() - new.y()) - ry * new.height()) <= .5
    back = anchor_geometry(new, cursor, old.width(), old.height())
    assert abs(back.x() - old.x()) <= 1
    assert abs(back.y() - old.y()) <= 1


def test_stitch_three_frames_preserves_pixels(app):
    rng = np.random.default_rng(19)
    array = rng.integers(0, 256, (1500, 300, 3), dtype=np.uint8)
    frames = [from_array(array[a:a + 700]) for a in (0, 400, 800)]
    result, overlap = stitch_pair(frames[0], frames[1])
    assert overlap == 300
    assert result.height() == 1100
    result, overlap = stitch_pair(result, frames[2])
    assert overlap == 300
    assert np.array_equal(rgb_array(result), array)


def test_stitch_rejects_duplicate_blank_and_unrelated(app):
    rng = np.random.default_rng(9)
    a = from_array(rng.integers(0, 256, (400, 200, 3), dtype=np.uint8))
    b = from_array(rng.integers(0, 256, (400, 200, 3), dtype=np.uint8))
    with pytest.raises(ValueError, match="没有移动"):
        find_overlap(a, a)
    with pytest.raises(ValueError):
        find_overlap(a, b)
    blank = QImage(200, 400, QImage.Format_ARGB32)
    blank.fill(QColor("white"))
    with pytest.raises(ValueError):
        find_overlap(blank, blank)
    with pytest.raises(ValueError, match="宽度不同"):
        find_overlap(a, b.copy(0, 0, 100, 400))


def test_repeating_content_rejected(app):
    rng = np.random.default_rng(91)
    stripe = rng.integers(0, 256, (50, 100, 3), dtype=np.uint8)
    a = from_array(np.tile(stripe, (10, 1, 1)))
    b = from_array(np.roll(np.tile(stripe, (10, 1, 1)), 10, axis=0))
    with pytest.raises(ValueError, match="不唯一"):
        find_overlap(a, b)
