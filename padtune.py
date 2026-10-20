"""
PadTune — réglage des manettes NYXI Flexi (protocole KeyLinker) depuis Windows.

Joysticks, gâchettes, vibrations et mise en veille, enregistrés dans la manette.

Lancement :  python padtune.py          (manette réelle, Bluetooth)
             python padtune.py --demo   (manette simulée, pour essayer l'interface)
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import json
import os
import sys
import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QObject, QPointF, QProcess, QRectF, Qt, QTimer, QTranslator, Signal
from PySide6.QtGui import QActionGroup, QColor, QFont, QIcon, QPainter, QPainterPath, QPalette, QPen
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QColorDialog, QComboBox, QHeaderView, QMenu, QTableWidget,
    QToolButton, QFileDialog, QFrame, QGridLayout, QGroupBox, QHBoxLayout,
    QLabel, QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSlider, QSpinBox,
    QTabWidget, QVBoxLayout, QWidget,
)

import flexi_protocol as fp
import i18n
from i18n import tr
from flexi_ble import ALL_BLOCKS, BLOCK_CLASSES, BleLink, FakeLink, LinkError

APP_NAME = "PadTune"
VERSION = "1.0.0"
FROZEN = getattr(sys, "frozen", False)                 # True dans PadTune.exe (PyInstaller)
APP_DIR = Path(__file__).resolve().parent
ICON_FILE = APP_DIR / "assets" / ("padtune.ico" if sys.platform == "win32" else "padtune_256.png")
DATA_DIR = Path(os.environ.get("APPDATA", Path.home())) / "PadTune"
_OLD_DATA_DIR = DATA_DIR.parent / "FlexiConfig"          # ancien nom de l'appli
if not DATA_DIR.exists() and _OLD_DATA_DIR.exists():
    try:
        _OLD_DATA_DIR.rename(DATA_DIR)                    # récupère sauvegardes et favoris
    except OSError:
        DATA_DIR = _OLD_DATA_DIR
SETTINGS_FILE = DATA_DIR / "settings.json"
_OLD_SETTINGS_FILE = DATA_DIR / "parametres.json"      # nom utilisé jusqu'à la 1.0.0
RESCAN_MS = 8000          # recherche discrète tant qu'un favori n'est pas détecté


def load_settings() -> dict:
    for f in (SETTINGS_FILE, _OLD_SETTINGS_FILE):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            return {}
        # anciennes clés françaises -> clés anglaises
        if "favoris" in data:
            data.setdefault("favorites", data.pop("favoris"))
        if "langue" in data:
            data.setdefault("language", data.pop("langue"))
        return data
    return {}


def save_settings(data: dict):
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        SETTINGS_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        if _OLD_SETTINGS_FILE.exists():
            _OLD_SETTINGS_FILE.unlink()
    except OSError:
        pass
ACCENT = QColor("#3b82f6")
RED = QColor(220, 38, 38)
def block_label(name: str) -> str:
    return {"sticks": tr("joysticks"), "triggers": tr("gâchettes"), "motors": tr("vibrations / veille"),
            "remap": tr("boutons"), "lights": tr("lumières"), "macros": tr("macros")}[name]
TAB_OF = {"sticks": 0, "triggers": 1, "remap": 2, "macros": 3, "lights": 4, "motors": 5}
# mode maintenu pendant l'affichage en direct, comme les pages de KeyLinker
LIVE_PAGE_OF_TAB = {0: 7, 1: 7, 2: 8, 3: 2, 4: 8, 5: 8}


# --------------------------------------------------------------------------- async
class AsyncRunner(QObject):
    """Boucle asyncio dans un thread ; les résultats reviennent dans le thread Qt via un signal."""
    done = Signal(object, object, object)   # callback, résultat, exception

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self.loop.run_forever, daemon=True).start()
        self.done.connect(self._dispatch)

    def run(self, coro, callback=None):
        fut = asyncio.run_coroutine_threadsafe(coro, self.loop)

        def finished(f):
            exc = f.exception()
            self.done.emit(callback, None if exc else f.result(), exc)
        fut.add_done_callback(finished)

    @staticmethod
    def _dispatch(cb, res, exc):
        if cb:
            cb(res, exc)


# --------------------------------------------------------------------------- dessin
def _caption(p: QPainter, rect: QRectF, text: str, fg: QColor):
    p.setPen(fg)
    p.setFont(QFont(p.font().family(), 8))
    p.drawText(rect, Qt.AlignCenter, text)


def draw_curve(p: QPainter, box: QRectF, curve, mid: QColor, marker_in: float | None = None):
    """Courbe (0,0)->(x1,y1)->(x2,y2)->(255,255) ; marker_in = entrée 0-255 actuelle (point rouge)."""
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(mid, 1))
    p.drawRect(box)
    p.setPen(QPen(mid, 1, Qt.DashLine))
    p.drawLine(box.bottomLeft(), box.topRight())

    def pt(x, y):
        return QPointF(box.left() + box.width() * x / 255, box.bottom() - box.height() * y / 255)
    x1, y1, x2, y2 = curve
    path = QPainterPath(pt(0, 0))
    for x, y in ((x1, y1), (x2, y2), (255, 255)):
        path.lineTo(pt(x, y))
    p.setPen(QPen(ACCENT, 2))
    p.drawPath(path)
    p.setBrush(ACCENT)
    p.setPen(QPen(QColor(255, 255, 255), 1.5))
    for x, y in ((x1, y1), (x2, y2)):
        p.drawEllipse(pt(x, y), 5, 5)
    if marker_in is not None:
        p.setPen(Qt.NoPen)
        p.setBrush(RED)
        p.drawEllipse(pt(marker_in, fp.curve_value(marker_in, curve)), 4.5, 4.5)


class CurvePreview(QWidget):
    """Aperçu avec courbe dont les 2 points de contrôle se déplacent à la souris."""
    curve_edited = Signal(list)
    GRAB_PX = 12

    def __init__(self):
        super().__init__()
        self._curve_box: QRectF | None = None
        self._drag = None              # index du point déplacé (0 ou 1)
        self.setMouseTracking(True)

    def _point_px(self, i):
        b = self._curve_box
        x, y = self.curve[2 * i], self.curve[2 * i + 1]
        return QPointF(b.left() + b.width() * x / 255, b.bottom() - b.height() * y / 255)

    def _hit(self, pos):
        if self._curve_box is None:
            return None
        best, dist = None, self.GRAB_PX
        for i in (0, 1):
            d = (self._point_px(i) - QPointF(pos)).manhattanLength()
            if d <= dist:
                best, dist = i, d
        return best

    def mousePressEvent(self, e):
        i = self._hit(e.position())
        if e.button() == Qt.LeftButton and i is not None:
            self._drag = i
            self.setCursor(Qt.ClosedHandCursor)
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            self.setCursor(Qt.OpenHandCursor if self._hit(e.position()) is not None else Qt.ArrowCursor)
            return
        b = self._curve_box
        x = round((e.position().x() - b.left()) / b.width() * 255)
        y = round((b.bottom() - e.position().y()) / b.height() * 255)
        x, y = max(0, min(255, x)), max(0, min(255, y))
        c = list(self.curve)
        # le 1er point reste à gauche du 2e
        if self._drag == 0:
            x = min(x, c[2])
        else:
            x = max(x, c[0])
        c[2 * self._drag], c[2 * self._drag + 1] = x, y
        if c != self.curve:
            self.curve = c
            self.update()
            self.curve_edited.emit(c)

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            self._drag = None
            self.setCursor(Qt.OpenHandCursor if self._hit(e.position()) is not None else Qt.ArrowCursor)
        else:
            super().mouseReleaseEvent(e)


class StickPreview(CurvePreview):
    """Cercle de course du stick (zones mortes, croix de centrage, positions en direct) + courbe."""

    def __init__(self):
        super().__init__()
        self.inner, self.outer, self.curve = 0, 100, [85, 85, 170, 170]
        self.raw = None          # (x, y) 0-255 reçu de la manette
        self.setMinimumSize(300, 170)

    def set_values(self, inner, outer, curve):
        self.inner, self.outer, self.curve = inner, outer, list(curve)
        self.update()

    def set_raw(self, xy):
        self.raw = xy
        self.update()

    def _stick(self):
        return fp.Stick(inner=self.inner, outer=self.outer, curve=self.curve)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        fg, mid = pal.color(QPalette.WindowText), pal.color(QPalette.Mid)
        size = min(self.height() - 24, self.width() / 2 - 16)
        c = QPointF(8 + size / 2, 4 + size / 2)
        r = size / 2

        # zones
        p.setPen(QPen(mid, 1))
        p.setBrush(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 60))
        p.drawEllipse(c, r * self.outer / 100, r * self.outer / 100)
        p.setBrush(QColor(220, 38, 38, 110))
        p.drawEllipse(c, r * self.inner / 100, r * self.inner / 100)
        # croix de centrage
        cross = QColor(mid)
        cross.setAlpha(200)
        p.setPen(QPen(cross, 1, Qt.DashLine))
        p.drawLine(QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()))
        p.drawLine(QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r))
        # bord
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(fg, 1.2))
        p.drawEllipse(c, r, r)

        caption, marker = tr("course du stick"), None
        if self.raw is not None:
            def to_pt(x, y):
                return QPointF(c.x() + (x - 128) / 128 * r, c.y() + (y - 128) / 128 * r)
            bx, by = fp.clamp_to_circle(*self.raw)
            ox, oy = fp.corrected_position(int(self.raw[0]), int(self.raw[1]), self._stick())
            p.setPen(QPen(QColor(60, 60, 60), 1))
            p.setBrush(QColor(255, 255, 255))
            p.drawEllipse(to_pt(bx, by), 6, 6)
            p.setPen(Qt.NoPen)
            p.setBrush(RED)
            p.drawEllipse(to_pt(ox, oy), 4.5, 4.5)

            def pct(x, y):
                return min(100, round(((x - 128) ** 2 + (y - 128) ** 2) ** 0.5 / 128 * 100))
            caption = tr("brut {a} %  →  sortie {b} %", a=pct(bx, by), b=pct(ox, oy))
            # entrée de la courbe = amplitude après zone morte, sur 0-255
            rr = ((bx - 128) ** 2 + (by - 128) ** 2) ** 0.5
            r_in, r_out = self.inner / 100 * 127.5, self.outer / 100 * 127.5
            m = 0 if rr < r_in else (128 if rr > r_out else (rr - r_in) * 100 / max(1, self.outer - self.inner))
            marker = min(255.0, m / 128 * 255)
        _caption(p, QRectF(0, 4 + size + 2, size + 16, 16), caption, fg)

        x0 = 8 + size + 24
        self._curve_box = QRectF(x0, 4, size, size)
        draw_curve(p, self._curve_box, self.curve, mid, marker)
        _caption(p, QRectF(x0, 4 + size + 2, size, 16), tr("courbe de sensibilité"), fg)
        p.end()


class TriggerPreview(CurvePreview):
    """Barre de course de la gâchette (zones, position en direct) + courbe."""

    def __init__(self):
        super().__init__()
        self.inner, self.outer, self.curve = 0, 200, [85, 85, 170, 170]
        self.raw = None          # 0-200
        self.setMinimumSize(300, 170)

    def set_values(self, inner, outer, curve):
        self.inner, self.outer, self.curve = inner, outer, list(curve)
        self.update()

    def set_raw(self, v):
        self.raw = v
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        fg, mid = pal.color(QPalette.WindowText), pal.color(QPalette.Mid)
        size = min(self.height() - 24, self.width() / 2 - 16)
        bar = QRectF(8 + size / 2 - 22, 4, 44, size)

        def y_of(v):
            return bar.bottom() - bar.height() * v / 200
        # zones : rouge = ignoré au début, bleu = course utile
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(220, 38, 38, 90))
        p.drawRect(QRectF(bar.left(), y_of(self.inner), bar.width(), bar.bottom() - y_of(self.inner)))
        p.setBrush(QColor(ACCENT.red(), ACCENT.green(), ACCENT.blue(), 60))
        p.drawRect(QRectF(bar.left(), y_of(self.outer), bar.width(), y_of(self.inner) - y_of(self.outer)))
        caption, marker = tr("course de la gâchette"), None
        trig = fp.Trigger(inner=self.inner, outer=self.outer, curve=self.curve)
        if self.raw is not None:
            out = fp.trigger_output(self.raw, trig)
            p.setBrush(RED)
            p.drawRect(QRectF(bar.right() + 6, y_of(out), 8, bar.bottom() - y_of(out)))
            p.setPen(QPen(QColor(60, 60, 60), 1))
            p.setBrush(QColor(255, 255, 255))
            yy = y_of(min(200, self.raw))
            p.drawRect(QRectF(bar.left() - 4, yy - 3, bar.width() + 8, 6))
            caption = tr("brut {a} %  →  sortie {b} %", a=round(min(200, self.raw) / 2), b=round(out / 2))
            v = max(0, min(200, self.raw))
            lin = 0 if v < self.inner else (200 if v > self.outer else (v - self.inner) * 200 / max(1, self.outer - self.inner))
            marker = lin / 200 * 255
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(fg, 1.2))
        p.drawRect(bar)
        _caption(p, QRectF(0, 4 + size + 2, size + 16, 16), caption, fg)

        x0 = 8 + size + 24
        self._curve_box = QRectF(x0, 4, size, size)
        draw_curve(p, self._curve_box, self.curve, mid, marker)
        _caption(p, QRectF(x0, 4 + size + 2, size, 16), tr("courbe de sensibilité"), fg)
        p.end()


# --------------------------------------------------------------------------- éditeurs
def _slider_spin(lo, hi, suffix=" %"):
    s = QSlider(Qt.Horizontal)
    s.setRange(lo, hi)
    b = QSpinBox()
    b.setRange(lo, hi)
    b.setSuffix(suffix)
    s.valueChanged.connect(b.setValue)
    b.valueChanged.connect(s.setValue)
    return s, b


class CurveEditor(QObject):
    """Liste de préréglages + 4 points ; émet changed."""
    changed = Signal()

    def __init__(self, grid: QGridLayout, row: int):
        super().__init__()
        self.preset = QComboBox()
        for key in [*fp.CURVE_PRESETS.keys(), "Personnalisée"]:
            self.preset.addItem(tr(key), key)
        grid.addWidget(QLabel(tr("Courbe de sensibilité")), row, 0)
        grid.addWidget(self.preset, row, 1, 1, 2)
        pts = QHBoxLayout()
        self.pts = []
        for lab in ("x1", "y1", "x2", "y2"):
            sb = QSpinBox()
            sb.setRange(0, 255)
            sb.setPrefix(f"{lab} ")
            self.pts.append(sb)
            pts.addWidget(sb)
            sb.valueChanged.connect(self._points_changed)
        grid.addWidget(QLabel(tr("Points de courbe (0–255)")), row + 1, 0)
        grid.addLayout(pts, row + 1, 1, 1, 2)
        self._lock = False
        self.preset.currentIndexChanged.connect(lambda i: self._preset_changed(self.preset.itemData(i)))

    def _select(self, key):
        self.preset.setCurrentIndex(max(0, self.preset.findData(key)))

    def _preset_changed(self, name):
        if name in fp.CURVE_PRESETS and not self._lock:
            self.set(fp.CURVE_PRESETS[name])
            self.changed.emit()

    def _points_changed(self, *_):
        if self._lock:
            return
        self._lock = True
        self._select(fp.preset_name(self.value()))
        self._lock = False
        self.changed.emit()

    def value(self):
        return [sb.value() for sb in self.pts]

    def set(self, curve):
        self._lock = True
        for sb, v in zip(self.pts, curve):
            sb.setValue(v)
        self._select(fp.preset_name(curve))
        self._lock = False

    def set_from_drag(self, curve):
        """Point déplacé à la souris : met à jour les champs (la courbe devient « Personnalisée »)."""
        self.set(curve)
        self.changed.emit()


class StickPanel(QGroupBox):
    changed = Signal()

    def __init__(self, title):
        super().__init__(title)
        g = QGridLayout(self)
        self.preview = StickPreview()
        g.addWidget(self.preview, 0, 0, 1, 3)
        self.inner_sl, self.inner = _slider_spin(0, 99)
        self.outer_sl, self.outer = _slider_spin(1, 100)
        g.addWidget(QLabel(tr("Zone morte centrale")), 1, 0)
        g.addWidget(self.inner_sl, 1, 1)
        g.addWidget(self.inner, 1, 2)
        g.addWidget(QLabel(tr("Bord extérieur (100 = aucun)")), 2, 0)
        g.addWidget(self.outer_sl, 2, 1)
        g.addWidget(self.outer, 2, 2)
        self.curve = CurveEditor(g, 3)
        inv = QHBoxLayout()
        self.inv_x = QCheckBox(tr("Inverser X"))
        self.inv_y = QCheckBox(tr("Inverser Y"))
        inv.addWidget(self.inv_x)
        inv.addWidget(self.inv_y)
        inv.addStretch()
        g.addLayout(inv, 5, 0, 1, 3)
        g.setColumnStretch(1, 1)
        g.setRowStretch(0, 1)
        self._lock = False
        for w in (self.inner, self.outer):
            w.valueChanged.connect(self._emit)
        for w in (self.inv_x, self.inv_y):
            w.toggled.connect(self._emit)
        self.curve.changed.connect(self._emit)
        self.preview.curve_edited.connect(self.curve.set_from_drag)

    def _emit(self, *_):
        if self.inner.value() >= self.outer.value():
            self.outer.setValue(min(100, self.inner.value() + 1))
        self.preview.set_values(self.inner.value(), self.outer.value(), self.curve.value())
        if not self._lock:
            self.changed.emit()

    def set_stick(self, s: fp.Stick):
        self._lock = True
        self.inner.setValue(s.inner)
        self.outer.setValue(s.outer)
        self.curve.set(s.curve)
        self.inv_x.setChecked(s.invert_x)
        self.inv_y.setChecked(s.invert_y)
        self._lock = False
        self._emit()

    def stick(self, swap: bool) -> fp.Stick:
        return fp.Stick(inner=self.inner.value(), outer=self.outer.value(), curve=self.curve.value(),
                        invert_x=self.inv_x.isChecked(), invert_y=self.inv_y.isChecked(), swap=swap)


class TriggerPanel(QGroupBox):
    """Les curseurs sont en % (0-100) ; la manette travaille en 0-200."""
    changed = Signal()

    def __init__(self, title):
        super().__init__(title)
        g = QGridLayout(self)
        self.preview = TriggerPreview()
        g.addWidget(self.preview, 0, 0, 1, 3)
        self.inner_sl, self.inner = _slider_spin(0, 99)
        self.outer_sl, self.outer = _slider_spin(1, 100)
        g.addWidget(QLabel(tr("Zone morte (début de course)")), 1, 0)
        g.addWidget(self.inner_sl, 1, 1)
        g.addWidget(self.inner, 1, 2)
        g.addWidget(QLabel(tr("Fin de course (100 = complète)")), 2, 0)
        g.addWidget(self.outer_sl, 2, 1)
        g.addWidget(self.outer, 2, 2)
        self.curve = CurveEditor(g, 3)
        g.setColumnStretch(1, 1)
        g.setRowStretch(0, 1)
        self._lock = False
        self._exact = None       # valeurs 0-200 lues, conservées si l'utilisateur ne touche pas aux curseurs
        for w in (self.inner, self.outer):
            w.valueChanged.connect(self._user_change)
        self.curve.changed.connect(self._emit)
        self.preview.curve_edited.connect(self.curve.set_from_drag)

    def _user_change(self, *_):
        if not self._lock:
            self._exact = None
        self._emit()

    def _scaled(self):
        if self._exact:
            return self._exact
        return self.inner.value() * 2, self.outer.value() * 2

    def _emit(self, *_):
        if self.inner.value() >= self.outer.value():
            self.outer.setValue(min(100, self.inner.value() + 1))
        i, o = self._scaled()
        self.preview.set_values(i, o, self.curve.value())
        if not self._lock:
            self.changed.emit()

    def set_trigger(self, t: fp.Trigger):
        self._lock = True
        self.inner.setValue(round(t.inner / 2))
        self.outer.setValue(round(t.outer / 2))
        self._exact = (t.inner, t.outer)
        self.curve.set(t.curve)
        self._lock = False
        self._emit()

    def trigger(self, swap: bool) -> fp.Trigger:
        i, o = self._scaled()
        return fp.Trigger(inner=i, outer=o, curve=self.curve.value(), swap=swap)


class MotorsPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        box = QGroupBox(tr("Intensité des vibrations"))
        g = QGridLayout(box)
        self.sliders = []
        for row, label in enumerate((tr("Moteur gauche"), tr("Moteur droit"))):
            sl, sb = _slider_spin(0, 100)
            g.addWidget(QLabel(label), row, 0)
            g.addWidget(sl, row, 1)
            g.addWidget(sb, row, 2)
            sb.valueChanged.connect(self._motor_changed)
            self.sliders.append(sb)
        g.setColumnStretch(1, 1)
        note = QLabel(tr("0 % coupe la vibration. Pour tester, lance un jeu qui fait vibrer la manette."))
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        g.addWidget(note, 2, 0, 1, 3)
        v.addWidget(box)

        box2 = QGroupBox(tr("Mise en veille automatique"))
        h = QHBoxLayout(box2)
        h.addWidget(QLabel(tr("Éteindre la manette après")))
        self.sleep = QSpinBox()
        self.sleep.setRange(1, 600)
        self.sleep.setSuffix(tr(" min d'inactivité"))
        self.never = QCheckBox(tr("Jamais"))
        h.addWidget(self.sleep)
        h.addWidget(self.never)
        h.addStretch()
        self.sleep.valueChanged.connect(self._emit)
        self.never.toggled.connect(lambda on: (self.sleep.setEnabled(not on), self._emit()))
        v.addWidget(box2)
        v.addStretch()
        self._extra = [0, 0]     # moteurs 3 et 4 : conservés tels quels
        self._exact = None
        self._lock = False

    def _motor_changed(self, *_):
        if not self._lock:
            self._exact = None
        self._emit()

    def _emit(self, *_):
        if not self._lock:
            self.changed.emit()

    def set_config(self, m: fp.MotorsConfig):
        self._lock = True
        for sb, val in zip(self.sliders, m.motors[:2]):
            sb.setValue(round(val / 255 * 100))
        self._extra = list(m.motors[2:4])
        self._exact = list(m.motors[:2])
        never = m.sleep_minutes >= fp.SLEEP_NEVER
        self.never.setChecked(never)
        self.sleep.setEnabled(not never)
        if not never:
            self.sleep.setValue(max(1, min(600, m.sleep_minutes)))
        self._lock = False

    def config(self, tag=8) -> fp.MotorsConfig:
        main = self._exact or [round(sb.value() / 100 * 255) for sb in self.sliders]
        minutes = fp.SLEEP_NEVER if self.never.isChecked() else self.sleep.value()
        return fp.MotorsConfig(motors=[*main, *self._extra], sleep_minutes=minutes, tag=tag)


class RemapPage(QWidget):
    """Remappage : chaque bouton physique -> bouton envoyé (ou désactivé)."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        info = QLabel(tr("Choisis ce que chaque bouton envoie. Appuie sur un bouton de la manette : "
                         "sa ligne s'allume (affichage en direct)."))
        info.setWordWrap(True)
        top.addWidget(info, 1)
        self.reset_btn = QPushButton(tr("Tout remettre par défaut"))
        top.addWidget(self.reset_btn)
        v.addLayout(top)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        v.addWidget(self.scroll, 1)
        self.buttons: list = []
        self.rows: dict = {}          # code -> (label, combo)
        self._lock = False
        self.reset_btn.clicked.connect(self.reset)
        self._build([])

    def _build(self, buttons):
        self.buttons = list(buttons)
        holder = QWidget()
        g = QGridLayout(holder)
        self.rows = {}
        options = [*self.buttons, fp.DISABLED]
        half = (len(self.buttons) + 1) // 2
        for col in (0, 3):
            g.addWidget(QLabel("<b>" + tr("Bouton de la manette") + "</b>"), 0, col)
            g.addWidget(QLabel("<b>" + tr("Envoie") + "</b>"), 0, col + 1)
        for i, code in enumerate(self.buttons):
            row, col = (i % half) + 1, (0 if i < half else 3)
            lab = QLabel(fp.button_name(code))
            lab.setMinimumWidth(150)
            lab.setAutoFillBackground(True)
            combo = QComboBox()
            for opt in options:
                combo.addItem(fp.button_name(opt), opt)
            combo.currentIndexChanged.connect(self._emit)
            g.addWidget(lab, row, col)
            g.addWidget(combo, row, col + 1)
            self.rows[code] = (lab, combo)
        g.setColumnMinimumWidth(2, 30)
        g.setColumnStretch(5, 1)
        g.setRowStretch(half + 1, 1)
        if not self.buttons:
            g.addWidget(QLabel(tr("Connecte la manette pour afficher ses boutons.")), 1, 0, 1, 2)
        self.scroll.setWidget(holder)

    def _emit(self, *_):
        for code, (lab, combo) in self.rows.items():
            f = lab.font()
            f.setBold(combo.currentData() != code)
            lab.setFont(f)
        if not self._lock:
            self.changed.emit()

    def set_config(self, r: fp.RemapConfig):
        self._lock = True
        if r.buttons != self.buttons:
            self._build(r.buttons)
        for code, target in zip(r.buttons, r.targets):
            combo = self.rows[code][1]
            idx = combo.findData(target)
            if idx < 0:                       # code inconnu de la liste : on l'ajoute
                combo.addItem(fp.button_name(target), target)
                idx = combo.count() - 1
            combo.setCurrentIndex(idx)
        self._lock = False
        self._emit()

    def config(self) -> fp.RemapConfig:
        return fp.RemapConfig(buttons=list(self.buttons),
                              targets=[self.rows[c][1].currentData() for c in self.buttons])

    def reset(self):
        self._lock = True
        for code, (_lab, combo) in self.rows.items():
            combo.setCurrentIndex(combo.findData(code))
        self._lock = False
        self._emit()

    def set_pressed(self, states: dict):
        for code, st in states.items():
            if code in self.rows:
                lab = self.rows[code][0]
                lab.setStyleSheet("background: #fde68a; color: black;" if st else "")


class LightsPage(QWidget):
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.v = QVBoxLayout(self)
        self.holder = QWidget()
        self.v.addWidget(self.holder)
        self.v.addStretch()
        self.zones_ui = []
        self._lock = False
        self._build(0)

    def _build(self, n):
        self.holder.deleteLater()
        self.holder = QWidget()
        lay = QVBoxLayout(self.holder)
        lay.setContentsMargins(0, 0, 0, 0)
        self.v.insertWidget(0, self.holder)
        self.zones_ui = []
        if n == 0:
            lay.addWidget(QLabel(tr("Connecte la manette pour afficher ses zones lumineuses.")))
        for i in range(n):
            box = QGroupBox(tr("Zone {n}", n=i + 1) if n > 1 else tr("Éclairage"))
            g = QGridLayout(box)
            swatch = QPushButton()
            swatch.setFixedSize(64, 28)
            swatch.setToolTip(tr("Choisir une couleur"))
            rgb = []
            hl = QHBoxLayout()
            hl.addWidget(swatch)
            for lab in (tr("R"), tr("V"), tr("B")):
                sb = QSpinBox()
                sb.setRange(0, 255)
                sb.setPrefix(f"{lab} ")
                hl.addWidget(sb)
                rgb.append(sb)
            hl.addStretch()
            g.addWidget(QLabel(tr("Couleur")), 0, 0)
            g.addLayout(hl, 0, 1, 1, 2)
            mode = QComboBox()
            mode.addItems([tr("Fixe"), tr("Respiration")])
            g.addWidget(QLabel(tr("Mode")), 1, 0)
            g.addWidget(mode, 1, 1, 1, 2)
            br_sl, br = _slider_spin(0, 100)
            g.addWidget(QLabel(tr("Luminosité")), 2, 0)
            g.addWidget(br_sl, 2, 1, 1, 1)
            g.addWidget(br, 2, 2)
            sp_sl, sp = _slider_spin(0, 2048, "")
            g.addWidget(QLabel(tr("Vitesse (respiration)")), 3, 0)
            g.addWidget(sp_sl, 3, 1, 1, 1)
            g.addWidget(sp, 3, 2)
            g.setColumnStretch(1, 1)
            ui = {"swatch": swatch, "rgb": rgb, "mode": mode, "br": br, "sp": sp, "sp_sl": sp_sl, "exact_br": None}
            swatch.clicked.connect(lambda _=False, u=ui: self._pick(u))
            for sb in rgb:
                sb.valueChanged.connect(lambda _v, u=ui: self._refresh(u))
            mode.currentIndexChanged.connect(lambda _v, u=ui: self._refresh(u))
            br.valueChanged.connect(lambda _v, u=ui: self._br_changed(u))
            sp.valueChanged.connect(lambda _v, u=ui: self._refresh(u))
            lay.addWidget(box)
            self.zones_ui.append(ui)

    def _pick(self, u):
        c = QColorDialog.getColor(QColor(*[sb.value() for sb in u["rgb"]]), self, tr("Couleur de la zone"))
        if c.isValid():
            for sb, v in zip(u["rgb"], (c.red(), c.green(), c.blue())):
                sb.setValue(v)

    def _br_changed(self, u):
        if not self._lock:
            u["exact_br"] = None
        self._refresh(u)

    def _refresh(self, u):
        r, g, b = (sb.value() for sb in u["rgb"])
        u["swatch"].setStyleSheet(f"background: rgb({r},{g},{b}); border: 1px solid #555;")
        breathing = u["mode"].currentIndex() == 1
        u["sp"].setEnabled(breathing)
        u["sp_sl"].setEnabled(breathing)
        if not self._lock:
            self.changed.emit()

    def set_config(self, cfg: fp.LightsConfig):
        self._lock = True
        if len(cfg.zones) != len(self.zones_ui):
            self._build(len(cfg.zones))
        for u, z in zip(self.zones_ui, cfg.zones):
            for sb, v in zip(u["rgb"], z.color):
                sb.setValue(v)
            u["mode"].setCurrentIndex(1 if z.breathing else 0)
            u["br"].setValue(round(z.brightness / 255 * 100))
            u["exact_br"] = z.brightness
            u["sp"].setValue(min(2048, z.speed))
            self._refresh(u)
        self._lock = False

    def config(self) -> fp.LightsConfig:
        zones = []
        for u in self.zones_ui:
            br = u["exact_br"] if u["exact_br"] is not None else round(u["br"].value() / 100 * 255)
            zones.append(fp.LightZone(color=[sb.value() for sb in u["rgb"]], breathing=u["mode"].currentIndex() == 1,
                                      brightness=br, speed=u["sp"].value()))
        return fp.LightsConfig(zones=zones)


class MacroPage(QWidget):
    """Éditeur de macros : étapes (durée + boutons + croix + sticks), boucle, enregistrement depuis la manette."""
    changed = Signal()
    COLS = ["Durée (ms)", "Boutons", "Croix", "Stick G", "Stick D"]

    def __init__(self):
        super().__init__()
        self.cfg: fp.MacrosConfig | None = None
        self.idx = 0
        self._lock = False
        self.recording = False
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        self.slot = QComboBox()
        self.loop = QCheckBox(tr("Répéter en boucle tant que le bouton est maintenu / activé"))
        self.interval = QSpinBox()
        self.interval.setRange(0, 20475)
        self.interval.setSingleStep(5)
        self.interval.setSuffix(tr(" ms entre deux répétitions"))
        top.addWidget(QLabel(tr("Macro")))
        top.addWidget(self.slot)
        top.addSpacing(16)
        top.addWidget(self.loop)
        top.addWidget(self.interval)
        top.addStretch()
        v.addLayout(top)
        note = QLabel(tr("Chaque étape maintient les boutons choisis pendant sa durée. Les macros se déclenchent "
                         "avec les boutons de macro de la manette (en général les boutons arrière)."))
        note.setWordWrap(True)
        note.setStyleSheet("color: palette(mid);")
        v.addWidget(note)
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([tr(c) for c in self.COLS])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        v.addWidget(self.table, 1)
        bar = QHBoxLayout()
        self.add_btn = QPushButton(tr("+ Étape"))
        self.del_btn = QPushButton(tr("Supprimer l'étape"))
        self.up_btn = QPushButton("↑")
        self.down_btn = QPushButton("↓")
        self.clear_btn = QPushButton(tr("Vider la macro"))
        self.rec_btn = QPushButton(tr("● Enregistrer depuis la manette"))
        for b in (self.add_btn, self.del_btn, self.up_btn, self.down_btn, self.clear_btn):
            bar.addWidget(b)
        bar.addStretch()
        self.rec_sticks = QCheckBox(tr("Inclure les sticks"))
        self.rec_sticks.setToolTip(tr("Enregistre aussi la direction des sticks (8 directions). "
                                      "Décoché : seuls les boutons et la croix sont enregistrés."))
        bar.addWidget(self.rec_sticks)
        bar.addWidget(self.rec_btn)
        v.addLayout(bar)
        self.add_btn.clicked.connect(self.add_step)
        self.del_btn.clicked.connect(self.del_step)
        self.up_btn.clicked.connect(lambda: self.move_step(-1))
        self.down_btn.clicked.connect(lambda: self.move_step(1))
        self.clear_btn.clicked.connect(self.clear_steps)
        self.rec_btn.clicked.connect(self.toggle_record)
        self.slot.currentIndexChanged.connect(self._slot_changed)
        self.loop.toggled.connect(self._meta_changed)
        self.interval.valueChanged.connect(self._meta_changed)
        self.setEnabled(False)

    # ---- modèle
    def macro(self) -> fp.Macro | None:
        if not self.cfg or not self.cfg.macros:
            return None
        return self.cfg.macros[self.idx]

    def set_config(self, cfg: fp.MacrosConfig):
        self._lock = True
        self.cfg = copy.deepcopy(cfg)
        self.slot.clear()
        for m in self.cfg.macros:
            self.slot.addItem(tr("Macro {n}", n=m.slot + 1))
        self.idx = min(self.idx, max(0, len(self.cfg.macros) - 1))
        self.slot.setCurrentIndex(self.idx)
        codes = set(self.cfg.codes)
        self.table.setColumnHidden(2, not (codes & set(fp.DPAD)))
        self.table.setColumnHidden(3, 18 not in codes)
        self.table.setColumnHidden(4, 19 not in codes)
        self.setEnabled(bool(self.cfg.macros))
        self._lock = False
        self._show()

    def config(self) -> fp.MacrosConfig | None:
        return copy.deepcopy(self.cfg) if self.cfg else None

    def _slot_changed(self, i):
        if self._lock or i < 0:
            return
        self.idx = i
        self._show()

    def _meta_changed(self, *_):
        m = self.macro()
        if self._lock or not m:
            return
        m.loop = self.loop.isChecked()
        m.interval = self.interval.value() // 5 * 5
        self.changed.emit()

    def _button_codes(self):
        return [c for c in (self.cfg.codes if self.cfg else []) if c not in fp.DPAD and c not in (18, 19)]

    def _show(self):
        m = self.macro()
        self._lock = True
        self.table.setRowCount(0)
        if m:
            self.loop.setChecked(m.loop)
            self.interval.setValue(m.interval)
            for st in m.steps:
                self._add_row(st)
        self._lock = False

    def _add_row(self, st: fp.MacroStep):
        r = self.table.rowCount()
        self.table.insertRow(r)
        dur = QSpinBox()
        dur.setRange(5, 60000)
        dur.setSingleStep(5)
        dur.setValue(st.duration)
        dur.valueChanged.connect(self._sync)
        self.table.setCellWidget(r, 0, dur)
        tb = QToolButton()
        tb.setPopupMode(QToolButton.InstantPopup)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        menu = QMenu(tb)
        for c in self._button_codes():
            a = menu.addAction(fp.button_name(c))
            a.setCheckable(True)
            a.setChecked(c in st.buttons)
            a.setData(c)
            a.toggled.connect(self._sync)
        tb.setMenu(menu)
        self.table.setCellWidget(r, 1, tb)
        for col, val in ((2, st.dpad), (3, st.lstick), (4, st.rstick)):
            cb = QComboBox()
            cb.addItems(fp.DIR_NAMES)
            cb.setCurrentIndex(val)
            cb.currentIndexChanged.connect(self._sync)
            self.table.setCellWidget(r, col, cb)
        self._label_buttons(r)

    def _label_buttons(self, r):
        tb = self.table.cellWidget(r, 1)
        names = [a.text() for a in tb.menu().actions() if a.isChecked()]
        tb.setText(" + ".join(names) if names else tr("(aucun bouton)"))

    def _row_step(self, r) -> fp.MacroStep:
        tb = self.table.cellWidget(r, 1)
        return fp.MacroStep(duration=self.table.cellWidget(r, 0).value() // 5 * 5,
                            buttons=sorted(a.data() for a in tb.menu().actions() if a.isChecked()),
                            dpad=self.table.cellWidget(r, 2).currentIndex(),
                            lstick=self.table.cellWidget(r, 3).currentIndex(),
                            rstick=self.table.cellWidget(r, 4).currentIndex())

    def _sync(self, *_):
        if self._lock or not self.macro():
            return
        for r in range(self.table.rowCount()):
            self._label_buttons(r)
        self.macro().steps = [self._row_step(r) for r in range(self.table.rowCount())]
        self.changed.emit()

    # ---- actions
    def add_step(self):
        if not self.macro():
            return
        self._add_row(fp.MacroStep(duration=100))
        self._sync()
        self.table.selectRow(self.table.rowCount() - 1)

    def del_step(self):
        r = self.table.currentRow()
        if r >= 0:
            self.table.removeRow(r)
            self._sync()

    def move_step(self, d):
        m = self.macro()
        r = self.table.currentRow()
        if not m or r < 0 or not 0 <= r + d < len(m.steps):
            return
        m.steps[r], m.steps[r + d] = m.steps[r + d], m.steps[r]
        self._show()
        self.table.selectRow(r + d)
        self.changed.emit()

    def clear_steps(self):
        if self.macro():
            self.macro().steps = []
            self._show()
            self.changed.emit()

    # ---- enregistrement depuis la manette (flux en direct)
    def toggle_record(self):
        if not self.macro():
            return
        if not self.recording:
            self.recording = True
            self._pressed, self._dirs = set(), {18: 0, 19: 0}
            self._rec_steps, self._t0, self._state = [], None, None
            self.rec_btn.setText(tr("■ Arrêter l'enregistrement"))
            self.rec_btn.setStyleSheet("color: #dc2626; font-weight: bold;")
        else:
            self._close_step()
            steps = self._rec_steps
            while steps and steps[0].is_empty():
                steps.pop(0)
            while steps and steps[-1].is_empty():
                steps.pop()
            self.recording = False
            self.rec_btn.setText(tr("● Enregistrer depuis la manette"))
            self.rec_btn.setStyleSheet("")
            if steps:
                self.macro().steps = steps
                self._show()
                self.changed.emit()

    def _current_state(self):
        allowed = set(self.cfg.codes)
        btn = tuple(sorted(c for c in self._pressed if c in allowed and c not in fp.DPAD and c not in (18, 19)))
        sticks = self.rec_sticks.isChecked()
        return (btn, fp.dpad_from_codes(self._pressed), self._dirs[18] if sticks and 18 in allowed else 0,
                self._dirs[19] if sticks and 19 in allowed else 0)

    def _close_step(self):
        import time
        now = time.monotonic()
        if self._state is not None and self._t0 is not None:
            dur = max(5, int(round((now - self._t0) * 1000 / 5)) * 5)
            b, d, l, r = self._state
            self._rec_steps.append(fp.MacroStep(duration=min(dur, 60000), buttons=list(b), dpad=d, lstick=l, rstick=r))
        self._t0 = now

    def feed(self, pos: dict):
        if not self.recording:
            return
        for code, st in pos.get("buttons", {}).items():
            (self._pressed.add if st else self._pressed.discard)(code)
        for code in (18, 19):
            if code in pos:
                self._dirs[code] = fp.dir_from_xy(*pos[code][:2])
        state = self._current_state()
        if state != self._state:
            self._close_step()
            self._state = state


# --------------------------------------------------------------------------- fenêtre principale
class MainWindow(QMainWindow):
    stream = Signal(object)

    def __init__(self, demo=False):
        super().__init__()
        self.demo = demo
        self.setWindowTitle(APP_NAME + (tr(" — mode démo") if demo else ""))
        self.runner = AsyncRunner()
        self.link = None
        self.loaded: dict = {}          # nom de bloc -> config lue dans la manette
        self.devices = []
        self._stream_seen = True

        root = QWidget()
        v = QVBoxLayout(root)

        bar = QHBoxLayout()
        self.scan_btn = QPushButton(tr("Rechercher"))
        self.dev_combo = QComboBox()
        self.dev_combo.setMinimumWidth(360)
        self.conn_btn = QPushButton(tr("Connecter"))
        bar.addWidget(self.scan_btn)
        bar.addWidget(self.dev_combo, 1)
        bar.addWidget(self.conn_btn)
        self.fav_btn = QPushButton(tr("☆ Favori"))
        self.fav_btn.setToolTip(tr("Mémoriser cette manette : l'appli s'y connectera automatiquement dès qu'elle la détecte."))
        bar.addWidget(self.fav_btn)
        v.addLayout(bar)
        self.status = QLabel(tr("Non connecté"))
        v.addWidget(self.status)
        hint = QLabel(tr("Mets la manette en mode Bluetooth (comme pour KeyLinker), puis Rechercher. "
                         "L'appareil marqué ★ expose le service de configuration."))
        hint.setWordWrap(True)
        hint.setStyleSheet("color: palette(mid);")
        v.addWidget(hint)

        self.tabs = QTabWidget()
        # joysticks
        w = QWidget()
        tv = QVBoxLayout(w)
        row = QHBoxLayout()
        self.left = StickPanel(tr("Stick gauche"))
        self.right = StickPanel(tr("Stick droit"))
        row.addWidget(self.left)
        row.addWidget(self.right)
        tv.addLayout(row, 1)
        self.swap = QCheckBox(tr("Échanger les sticks gauche et droit"))
        tv.addWidget(self.swap)
        self.tabs.addTab(w, tr("Joysticks"))
        # gâchettes
        w = QWidget()
        tv = QVBoxLayout(w)
        row = QHBoxLayout()
        self.lt = TriggerPanel(tr("Gâchette gauche (L2)"))
        self.rt = TriggerPanel(tr("Gâchette droite (R2)"))
        row.addWidget(self.lt)
        row.addWidget(self.rt)
        tv.addLayout(row, 1)
        self.tswap = QCheckBox(tr("Échanger les gâchettes gauche et droite"))
        tv.addWidget(self.tswap)
        self.tabs.addTab(w, tr("Gâchettes"))
        # boutons
        self.remap = RemapPage()
        self.tabs.addTab(self.remap, tr("Boutons"))
        # macros
        self.macros = MacroPage()
        self.tabs.addTab(self.macros, tr("Macros"))
        # lumières
        self.lights = LightsPage()
        self.tabs.addTab(self.lights, tr("Lumières"))
        # vibrations
        self.motors = MotorsPage()
        self.tabs.addTab(self.motors, tr("Vibrations et veille").replace("&", "&&"))   # & = raccourci clavier pour Qt
        v.addWidget(self.tabs, 1)

        opts = QHBoxLayout()
        self.live = QCheckBox(tr("Affichage en direct"))
        self.live.setChecked(True)
        self.live.setToolTip(tr("Blanc : position réelle.\nRouge : ce que reçoit le jeu avec les réglages "
                                "affichés (même avant Appliquer)."))
        self.read_btn = QPushButton(tr("Lire la manette"))
        self.apply_btn = QPushButton(tr("Appliquer à la manette"))
        self.apply_btn.setDefault(True)
        self.revert_btn = QPushButton(tr("Annuler les modifications"))
        self.save_btn = QPushButton(tr("Exporter…"))
        self.load_btn = QPushButton(tr("Importer…"))
        for b in (self.read_btn, self.apply_btn, self.revert_btn):
            opts.addWidget(b)
        opts.addStretch()
        opts.addWidget(self.live)
        opts.addWidget(self.save_btn)
        opts.addWidget(self.load_btn)
        v.addLayout(opts)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        v.addWidget(line)
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        self.logbox.setMaximumHeight(120)
        self.logbox.setFont(QFont("Consolas", 9))
        v.addWidget(self.logbox)
        self.setCentralWidget(root)
        self._build_menu()

        self.scan_btn.clicked.connect(lambda: self.scan(manual=True))
        self.fav_btn.clicked.connect(self.toggle_favorite)
        self.dev_combo.currentIndexChanged.connect(lambda _i: self._update_fav_btn())
        self.conn_btn.clicked.connect(self.toggle_connect)
        self.read_btn.clicked.connect(self.read)
        self.apply_btn.clicked.connect(self.apply)
        self.revert_btn.clicked.connect(self.revert)
        self.save_btn.clicked.connect(self.export_profile)
        self.load_btn.clicked.connect(self.import_profile)
        for wdg in (self.left, self.right, self.lt, self.rt, self.motors, self.remap, self.macros, self.lights):
            wdg.changed.connect(self._dirty)
        self.swap.toggled.connect(self._dirty)
        self.tswap.toggled.connect(self._dirty)
        self.live.toggled.connect(self._live_toggled)
        self.stream.connect(self._on_stream)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.macros.rec_btn.clicked.connect(lambda: self.live.setChecked(True))   # l'enregistrement utilise le flux
        self._set_connected(False)
        # favoris et reconnexion automatique
        self.settings = load_settings()
        self.favorites: dict = dict(self.settings.get("favorites", {}))     # adresse -> nom
        self._manual_off = False      # l'utilisateur a cliqué sur Déconnecter : pas de reconnexion auto
        self._connecting = False
        self._scanning = False
        self.connected_dev = None
        self._rescan = QTimer(self)
        self._rescan.setSingleShot(True)
        self._rescan.timeout.connect(lambda: self.scan(silent=True))
        self._update_fav_btn()
        QTimer.singleShot(400, self.scan)          # recherche automatique au démarrage

    # ---- menu Langue
    def _build_menu(self):
        menu = self.menuBar().addMenu("🌐 " + tr("Langue"))
        group = QActionGroup(self)
        group.setExclusive(True)
        for code, name in i18n.LANGS.items():
            a = menu.addAction(name)
            a.setCheckable(True)
            a.setChecked(code == i18n.language())
            a.setData(code)
            group.addAction(a)
        group.triggered.connect(lambda a: self._change_language(a.data()))
        self._lang_group = group

    def _change_language(self, code):
        old = i18n.language()
        if code == old:
            return
        settings = load_settings()
        settings["language"] = code
        save_settings(settings)
        if hasattr(self, "settings"):
            self.settings["language"] = code
        i18n.set_language(code)                 # message affiché dans la nouvelle langue
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(tr("La langue sera appliquée au redémarrage de PadTune. Redémarrer maintenant ?"))
        now = box.addButton(tr("Redémarrer maintenant"), QMessageBox.AcceptRole)
        box.addButton(tr("Plus tard"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is now:
            # dans l'exe, sys.executable est PadTune.exe lui-même ; sinon c'est python + le script
            args = sys.argv[1:] if FROZEN else [os.path.abspath(sys.argv[0]), *sys.argv[1:]]
            workdir = str(Path(sys.executable).parent) if FROZEN else str(APP_DIR)
            self.close()
            QProcess.startDetached(sys.executable, args, workdir)
        else:
            i18n.set_language(old)                # la session en cours reste dans l'ancienne langue

    # ---- utilitaires
    def log(self, msg):
        self.logbox.appendPlainText(f"[{dt.datetime.now():%H:%M:%S}] {msg}")

    def _thread_log(self, msg):
        self.runner.done.emit(lambda *_: self.log(msg), None, None)

    def _busy(self, on, text=None):
        for b in (self.scan_btn, self.conn_btn, self.read_btn, self.apply_btn):
            b.setEnabled(not on)
        if not on:
            self._set_connected(self.link is not None)
        if text:
            self.status.setText(text)

    def _set_connected(self, ok):
        self.conn_btn.setText(tr("Déconnecter") if ok else tr("Connecter"))
        for b in (self.read_btn, self.apply_btn, self.revert_btn):
            b.setEnabled(ok)
        self.tabs.setEnabled(ok or bool(self.loaded))

    def _error(self, title, exc):
        msg = str(exc) or exc.__class__.__name__
        self.log(tr("Erreur : {msg}", msg=msg))
        if not isinstance(exc, LinkError):
            self.log("".join(traceback.format_exception(exc)).strip())
        QMessageBox.warning(self, title, msg)

    def _clear_live(self):
        for pv in (self.left.preview, self.right.preview, self.lt.preview, self.rt.preview):
            pv.set_raw(None)

    # ---- valeurs affichées <-> configs
    def current(self) -> dict:
        out = {}
        tag = self.loaded.get("sticks").tag if "sticks" in self.loaded else 14
        sw = self.swap.isChecked()
        out["sticks"] = fp.SticksConfig(tag=tag, left=self.left.stick(sw), right=self.right.stick(sw))
        tag = self.loaded.get("triggers").tag if "triggers" in self.loaded else 14
        tsw = self.tswap.isChecked()
        out["triggers"] = fp.TriggersConfig(tag=tag, left=self.lt.trigger(tsw), right=self.rt.trigger(tsw))
        tag = self.loaded.get("motors").tag if "motors" in self.loaded else 8
        out["motors"] = self.motors.config(tag)
        if "remap" in self.loaded:
            out["remap"] = self.remap.config()
        if "lights" in self.loaded:
            out["lights"] = self.lights.config()
        if "macros" in self.loaded and self.macros.config():
            out["macros"] = self.macros.config()
        return out

    def changed_blocks(self) -> list:
        cur = self.current()
        return [n for n in ALL_BLOCKS if n in self.loaded and n in cur
                and cur[n].to_payload() != self.loaded[n].to_payload()]

    def show_config(self, cfgs: dict):
        if "sticks" in cfgs:
            c = cfgs["sticks"]
            self.left.set_stick(c.left)
            self.right.set_stick(c.right)
            self.swap.blockSignals(True)
            self.swap.setChecked(c.left.swap or c.right.swap)
            self.swap.blockSignals(False)
        if "triggers" in cfgs:
            c = cfgs["triggers"]
            self.lt.set_trigger(c.left)
            self.rt.set_trigger(c.right)
            self.tswap.blockSignals(True)
            self.tswap.setChecked(c.left.swap or c.right.swap)
            self.tswap.blockSignals(False)
        if "motors" in cfgs:
            self.motors.set_config(cfgs["motors"])
        if "remap" in cfgs:
            r = cfgs["remap"]
            if self.remap.buttons and r.buttons != self.remap.buttons:
                r = r.adapted_to(self.remap.buttons)
            self.remap.set_config(r)
        if "lights" in cfgs:
            self.lights.set_config(cfgs["lights"])
        if "macros" in cfgs:
            m = cfgs["macros"]
            dev = self.loaded.get("macros")
            if dev is not None and m is not dev:      # profil importé : adapter aux emplacements / boutons de la manette
                by_slot = {x.slot: x for x in m.macros}
                allowed = set(dev.codes)
                macros = []
                for d in dev.macros:
                    x = copy.deepcopy(by_slot.get(d.slot, d))
                    for st in x.steps:
                        st.buttons = [c for c in st.buttons if c in allowed]
                    macros.append(x)
                m = fp.MacrosConfig(codes=list(dev.codes), macros=macros, v2=dev.v2)
            self.macros.set_config(m)
        self._dirty()

    def _dirty(self, *_):
        try:
            n = len(self.changed_blocks())
        except ValueError:
            n = 1
        self.apply_btn.setText(tr("Appliquer à la manette") + (tr(" ({n} modif.)", n=n) if n else ""))

    # ---- actions
    # ---- favoris
    def _selected_device(self):
        if self.link and self.connected_dev:
            return self.connected_dev
        i = self.dev_combo.currentIndex()
        return self.devices[i] if 0 <= i < len(self.devices) else None

    def _update_fav_btn(self):
        dev = self._selected_device()
        fav = dev is not None and dev.address in self.favorites
        self.fav_btn.setText(tr("★ Favori") if fav else tr("☆ Favori"))
        self.fav_btn.setEnabled(dev is not None)

    def toggle_favorite(self):
        dev = self._selected_device()
        if dev is None:
            return
        if dev.address in self.favorites:
            del self.favorites[dev.address]
            self.log(tr("{name} retirée des favoris", name=dev.name or dev.address))
        else:
            self.favorites[dev.address] = dev.name or dev.address
            self.log(tr("{name} ajoutée aux favoris : connexion automatique dès qu'elle est détectée",
                        name=dev.name or dev.address))
        self.settings["favorites"] = self.favorites
        save_settings(self.settings)
        self._refresh_labels()
        self._update_fav_btn()

    def _label(self, d):
        return ("♥ " if d.address in self.favorites else "") + d.label()

    def _refresh_labels(self):
        for i, d in enumerate(self.devices):
            self.dev_combo.setItemText(i, self._label(d))

    def _schedule_rescan(self):
        if self.favorites and not self.link and not self._manual_off and not self._connecting:
            self._rescan.start(RESCAN_MS)

    # ---- actions
    def scan(self, manual=False, silent=False):
        if self._scanning or self._connecting or (silent and self.link):
            return
        if manual:
            self._manual_off = False
        self._rescan.stop()
        self._scanning = True
        if not silent:
            self._busy(True, tr("Recherche des appareils Bluetooth…"))
        cls = FakeLink if self.demo else BleLink

        def done(res, exc):
            self._scanning = False
            if not silent:
                self._busy(False)
            if exc:
                if silent:
                    self.log(tr("Recherche impossible : {err}", err=exc))
                    return self._schedule_rescan()
                self.status.setText(tr("Recherche impossible"))
                return self._error(tr("Recherche Bluetooth"), exc)
            if self.link:            # connecté entre-temps
                return
            res = sorted(res, key=lambda d: d.address not in self.favorites)   # favoris en premier
            self.devices = res
            self.dev_combo.blockSignals(True)
            self.dev_combo.clear()
            for d in res:
                self.dev_combo.addItem(self._label(d))
            if res:
                self.dev_combo.setCurrentIndex(0)      # favori, sinon manette compatible (★) en premier
            self.dev_combo.blockSignals(False)
            self._update_fav_btn()
            fav = next((d for d in res if d.address in self.favorites), None)
            n = sum(d.has_service for d in res)
            if fav and not self._manual_off:
                self.status.setText(tr("Favori détecté : connexion à {name}…", name=fav.name or fav.address))
                return self.toggle_connect(auto=True)
            if self.favorites and not self._manual_off:
                self.status.setText(tr("En attente de la manette favorite… (allume-la en mode Bluetooth)"))
                return self._schedule_rescan()
            if n:
                self.status.setText(tr("{n} manette(s) compatible(s) trouvée(s) : clique sur Connecter", n=n))
            else:
                self.status.setText(tr("{n} appareil(s) trouvé(s), aucun marqué ★ : vérifie que la manette "
                                       "est en mode Bluetooth, puis Rechercher", n=len(res)))
        self.runner.run(cls.scan(), done)

    def toggle_connect(self, auto=False):
        if self.link:
            link, self.link = self.link, None
            self.runner.run(link.disconnect())
            self._clear_live()
            self._manual_off = True
            self.status.setText(tr("Déconnecté (reconnexion automatique suspendue jusqu'à la prochaine recherche)")
                                if self.favorites else tr("Déconnecté"))
            self._set_connected(False)
            self._update_fav_btn()
            return
        if self._connecting:
            return
        if not auto:
            self._manual_off = False
        i = self.dev_combo.currentIndex()
        if i < 0 or i >= len(self.devices):
            return QMessageBox.information(self, APP_NAME, tr("Lance d'abord une recherche et choisis la manette."))
        dev = self.devices[i]
        link = FakeLink() if self.demo else BleLink()
        link.on_log = self._thread_log
        link.on_disconnect = lambda: self.runner.done.emit(lambda *_: self._lost(), None, None)
        link.on_stream = self.stream.emit
        self._busy(True, tr("Connexion à {name}…", name=dev.name or dev.address))
        self._connecting = True
        self._rescan.stop()

        async def go():
            await link.connect(dev.address)
            info = await link.device_info()
            return info, await link.read_all()

        def done(res, exc):
            self._connecting = False
            if exc:
                self._busy(False, tr("Échec de la connexion"))
                if auto:
                    self.log(tr("Connexion automatique impossible : {err}", err=exc))
                    return self._schedule_rescan()
                return self._error(tr("Connexion"), exc)
            self.link = link
            self.connected_dev = dev
            info, cfgs = res
            if info is not None:
                self.log(tr("Infos appareil : {hex}", hex=bytes(info).hex(' ')))
            if isinstance(cfgs.get("sticks"), Exception):
                self.link = None
                self.runner.run(link.disconnect())
                self._busy(False, tr("Échec de la lecture"))
                if auto:
                    self.log(tr("Lecture impossible : {err}", err=cfgs['sticks']))
                    return self._schedule_rescan()
                return self._error(tr("Connexion"), cfgs["sticks"])
            self._loaded(cfgs, backup=True)
            self._busy(False, tr("Connecté : {name}", name=dev.name or dev.address))
            self._update_fav_btn()
            self._tab_changed(self.tabs.currentIndex())
            self._live_toggled(self.live.isChecked())
        self.runner.run(go(), done)

    def _loaded(self, cfgs: dict, backup=False):
        ok = {n: c for n, c in cfgs.items() if not isinstance(c, Exception)}
        for n, c in cfgs.items():
            idx = TAB_OF[n]
            if isinstance(c, Exception):
                self.log(tr("Réglages {what} non lus : {err}", what=block_label(n), err=c))
                if n not in self.loaded:
                    self.tabs.setTabEnabled(idx, False)
                    self.tabs.setTabToolTip(idx, tr("Non pris en charge par cette manette (ou pas de réponse)"))
            else:
                self.tabs.setTabEnabled(idx, True)
        self.loaded.update(ok)
        self.show_config(ok)
        if "sticks" in ok:
            s = ok["sticks"]
            self.log(tr("Joysticks : G {a}%–{b}% | D {c}%–{d}%", a=s.left.inner, b=s.left.outer,
                        c=s.right.inner, d=s.right.outer))
        if "triggers" in ok:
            t = ok["triggers"]
            self.log(tr("Gâchettes : G {a}%–{b}% | D {c}%–{d}%", a=f"{t.left.inner / 2:g}", b=f"{t.left.outer / 2:g}",
                        c=f"{t.right.inner / 2:g}", d=f"{t.right.outer / 2:g}"))
        if "motors" in ok:
            m = ok["motors"]
            veille = tr("jamais") if m.sleep_minutes >= fp.SLEEP_NEVER else f"{m.sleep_minutes} min"
            self.log(tr("Vibrations : {a}/{b} (sur 255) | veille : {sleep}", a=m.motors[0], b=m.motors[1], sleep=veille))
        if "remap" in ok:
            r = ok["remap"]
            changes = [f"{fp.button_name(b)} → {fp.button_name(t)}" for b, t in zip(r.buttons, r.targets) if b != t]
            self.log(tr("Boutons : {list}", list=", ".join(changes) if changes else tr("aucun remappage")))
        if "lights" in ok:
            self.log(tr("Lumières : {n} zone(s)", n=len(ok['lights'].zones)))
        if "macros" in ok:
            used = [tr("{slot} ({n} étapes)", slot=m.slot + 1, n=len(m.steps)) for m in ok["macros"].macros if m.steps]
            self.log(tr("Macros : {n} emplacement(s)", n=len(ok['macros'].macros))
                     + (tr(", utilisées : {list}", list=", ".join(used)) if used else tr(", toutes vides")))
        if backup and ok:
            try:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                f = DATA_DIR / f"backup-{dt.datetime.now():%Y%m%d-%H%M%S}.json"
                f.write_text(json.dumps({n: c.to_dict() for n, c in ok.items()}, indent=2), encoding="utf-8")
                self.log(tr("Sauvegarde des réglages d'origine : {path}", path=f))
            except OSError as e:
                self.log(tr("Sauvegarde impossible : {err}", err=e))

    def read(self):
        self._busy(True, tr("Lecture…"))

        def done(res, exc):
            self._busy(False, tr("Connecté"))
            if exc:
                return self._error(tr("Lecture"), exc)
            self._loaded(res)
        self.runner.run(self.link.read_all(), done)

    def apply(self):
        try:
            cur = self.current()
            names = self.changed_blocks()
            for n in names:
                cur[n].to_payload()
        except ValueError as e:
            return QMessageBox.warning(self, APP_NAME, str(e))
        if not names:
            self.status.setText(tr("Rien à appliquer : la manette a déjà ces réglages."))
            return
        self._busy(True, tr("Écriture dans la manette…"))
        link = self.link

        async def go():
            res = {}
            for n in names:
                res[n] = await link.write(n, cur[n])
            return res

        def done(res, exc):
            self._busy(False, tr("Connecté"))
            if exc:
                return self._error(tr("Écriture"), exc)
            bad = [n for n in names if res[n].to_payload() != cur[n].to_payload()]
            if bad:
                what = ", ".join(block_label(n) for n in bad)
                self.log(tr("Attention : relecture différente pour {list}", list=what))
                QMessageBox.warning(self, APP_NAME, tr("La manette a répondu, mais la relecture diffère des valeurs "
                                                       "envoyées pour : {list}", list=what))
            else:
                self.log(tr("Appliqué et vérifié par relecture ✔ : {list}", list=", ".join(block_label(n) for n in names)))
                self.status.setText(tr("Réglages appliqués ✔"))
            self._loaded(res)
        self.runner.run(go(), done)

    def revert(self):
        if self.loaded:
            self.show_config(copy.deepcopy(self.loaded))

    # ---- affichage en direct
    def _live_toggled(self, on):
        if not on:
            self._clear_live()
        if self.link:
            self.runner.run(self.link.set_live(on))
            if on:
                self._stream_seen = False
                QTimer.singleShot(3000, self._check_stream)

    def _check_stream(self):
        if self.link and self.live.isChecked() and not self._stream_seen:
            self.log(tr("Aucune position reçue pour l'instant : bouge un stick. "
                        "Si rien ne s'affiche, copie ce journal pour analyse."))

    def _on_stream(self, pos):
        if not self.live.isChecked():
            return
        if not self._stream_seen:
            self._stream_seen = True
            self.log(tr("Affichage en direct actif ✔"))
        if fp.STREAM_LEFT in pos:
            self.left.preview.set_raw(pos[fp.STREAM_LEFT][:2])
        if fp.STREAM_RIGHT in pos:
            self.right.preview.set_raw(pos[fp.STREAM_RIGHT][:2])
        if fp.STREAM_LT in pos:
            self.lt.preview.set_raw(pos[fp.STREAM_LT])
        if fp.STREAM_RT in pos:
            self.rt.preview.set_raw(pos[fp.STREAM_RT])
        if "buttons" in pos:
            self.remap.set_pressed(pos["buttons"])
        self.macros.feed(pos)

    def _tab_changed(self, idx):
        # La page boutons de KeyLinker utilise le mode 8, les pages sticks/gâchettes le mode 7
        if self.link:
            self.link.live_page = LIVE_PAGE_OF_TAB.get(idx, 7)

    def _lost(self):
        if self.link:
            self.link = None
            self.status.setText(tr("Connexion perdue"))
            self._clear_live()
            self.log(tr("La manette s'est déconnectée."))
            self._set_connected(False)
            if self.favorites and not self._manual_off:
                self.status.setText(tr("Connexion perdue : reconnexion automatique dès que la manette est détectée…"))
                self._schedule_rescan()

    # ---- profils
    def export_profile(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Exporter le profil"), str(DATA_DIR / "profile.json"), "JSON (*.json)")
        if not path:
            return
        try:
            cur = self.current()
            data = {n: cur[n].to_dict() for n in ALL_BLOCKS if n in cur and (n in self.loaded or n == "sticks")}
            Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
            self.log(tr("Profil exporté : {path}", path=path))
        except (OSError, ValueError) as e:
            QMessageBox.warning(self, APP_NAME, tr("Export impossible : {err}", err=e))

    def import_profile(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Importer un profil"), str(DATA_DIR), "JSON (*.json)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
            if "left" in data:                       # ancien format (joysticks seuls)
                data = {"sticks": data}
            cfgs = {n: BLOCK_CLASSES[n].from_dict(d) for n, d in data.items() if n in BLOCK_CLASSES}
            for c in cfgs.values():
                c.to_payload()
        except Exception as e:  # noqa: BLE001
            return QMessageBox.warning(self, APP_NAME, tr("Profil invalide : {err}", err=e))
        self.show_config(cfgs)
        self.log(tr("Profil importé : {path} (clique sur Appliquer pour l'envoyer)", path=path))

    def closeEvent(self, e):
        if self.link:
            fut = asyncio.run_coroutine_threadsafe(self.link.disconnect(), self.runner.loop)
            try:
                fut.result(timeout=3)
            except Exception:  # noqa: BLE001
                pass
        e.accept()


def selftest(out_path: str) -> int:
    """Vérification rapide de l'exe (utilisée par la construction automatique) : ressources et modules."""
    report = {"version": VERSION, "frozen": bool(FROZEN), "icon": ICON_FILE.exists()}
    try:
        import translations
        report["languages"] = sorted(translations.TRANSLATIONS)
    except Exception as e:  # noqa: BLE001
        report["languages"] = f"ERREUR {e}"
    try:
        import bleak  # noqa: F401
        from bleak import BleakScanner  # noqa: F401
        if sys.platform == "win32":
            import bleak.backends.winrt.scanner  # noqa: F401
        report["bleak"] = "ok"
    except Exception as e:  # noqa: BLE001
        report["bleak"] = f"ERREUR {e}"
    ok = report["icon"] and isinstance(report["languages"], list) and report["bleak"] == "ok"
    report["ok"] = ok
    Path(out_path).write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if ok else 1


def main():
    if "--selftest" in sys.argv:
        i = sys.argv.index("--selftest")
        sys.exit(selftest(sys.argv[i + 1] if i + 1 < len(sys.argv) else "padtune-selftest.json"))
    demo = "--demo" in sys.argv
    if sys.platform == "win32":
        try:   # icône propre dans la barre des tâches (sinon celle de Python)
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("PadTune.App")
        except Exception:  # noqa: BLE001
            pass
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    lang = i18n.set_language(load_settings().get("language") or i18n.system_language())
    QLocale.setDefault(QLocale(lang))
    qt_tr = QTranslator(app)                  # boutons standard (OK, Annuler, sélecteur de couleur…)
    if qt_tr.load(QLocale(lang), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(qt_tr)
    if ICON_FILE.exists():
        app.setWindowIcon(QIcon(str(ICON_FILE)))
    w = MainWindow(demo=demo)
    w.resize(1000, 780)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
