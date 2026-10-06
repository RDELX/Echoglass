"""The two-column Original | Translation area, in line-by-line or paragraph layout."""

import html
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtWidgets import (QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
                             QSizePolicy, QStackedWidget, QTextBrowser, QVBoxLayout, QWidget)

from ..translation.languages import name as lang_name
from . import theme

MAX_ENTRIES = 1000
PARAGRAPH_GAP_S = 2.5   # a pause longer than this starts a new paragraph


@dataclass
class Entry:
    id: int
    start: float
    language: str
    text: str
    translation: str | None = None
    state: str = "pending"   # pending | done | same | failed | off


def _fmt_time(s: float) -> str:
    m, s = divmod(int(s), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _translation_text(e: Entry) -> tuple[str, str]:
    """(text, style) for an entry's translation cell."""
    if e.state == "done":
        return e.translation or "", ""
    if e.state == "pending":
        return "translating…", "pending"
    if e.state == "same":
        return e.text, ""
    if e.state == "off":
        return "", ""
    return "translation failed", "failed"


def _divider() -> QFrame:
    d = QFrame()
    d.setObjectName("divider")
    d.setFixedWidth(1)
    return d


class _StickyScroll:
    """Keeps a scroll area pinned to the bottom unless the user has scrolled up."""

    def __init__(self, bar, on_unseen):
        self.bar = bar
        self.stick = True
        self._on_unseen = on_unseen
        bar.valueChanged.connect(self._moved)
        bar.rangeChanged.connect(self._range)

    def _moved(self, v):
        self.stick = v >= self.bar.maximum() - 6

    def _range(self, _lo, hi):
        if self.stick:
            self.bar.setValue(hi)
        else:
            self._on_unseen()

    def to_bottom(self):
        self.stick = True
        self.bar.setValue(self.bar.maximum())


# ---------------------------------------------------------------------------------------
# Line-by-line: one row per utterance, original and translation side by side, aligned.
# ---------------------------------------------------------------------------------------

class _Row(QWidget):
    def __init__(self, e: Entry, font_pt: float):
        super().__init__()
        grid = QGridLayout(self)
        grid.setContentsMargins(20, 10, 20, 10)
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(2)
        self.time = QLabel(_fmt_time(e.start))
        self.time.setObjectName("rowTime")
        self.original = self._text_label("rowOriginal")
        self.translation = self._text_label("rowTranslation")
        grid.addWidget(self.time, 0, 0)
        grid.addWidget(self.original, 1, 0)
        grid.addWidget(_divider(), 0, 1, 2, 1)
        grid.addWidget(self.translation, 1, 2)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(2, 1)
        self._src_lang = e.language
        self._tgt_lang: str | None = None
        self.set_font(font_pt)
        self.update_entry(e)

    def set_live(self, live: bool) -> None:
        """Dimmed style for the sentence that's still being spoken."""
        for lbl in (self.original, self.translation):
            lbl.setProperty("live", live)
            lbl.style().unpolish(lbl)
            lbl.style().polish(lbl)
        self.time.setText("live" if live else self.time.text())

    @staticmethod
    def _text_label(obj: str) -> QLabel:
        lbl = QLabel()
        lbl.setObjectName(obj)
        lbl.setWordWrap(True)
        lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lbl.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        return lbl

    def set_font(self, pt: float) -> None:
        self._pt = pt
        self.original.setFont(theme.ui_font(pt, language=self._src_lang))
        self.translation.setFont(theme.ui_font(pt, language=self._tgt_lang))

    def set_target_language(self, code: str) -> None:
        if code != self._tgt_lang:
            self._tgt_lang = code
            self.translation.setFont(theme.ui_font(self._pt, language=code))

    def update_entry(self, e: Entry) -> None:
        self.original.setText(e.text)
        text, style = _translation_text(e)
        self.translation.setText(text)
        self.translation.setProperty("pending", style == "pending")
        self.translation.setProperty("failed", style == "failed")
        self.translation.style().unpolish(self.translation)
        self.translation.style().polish(self.translation)


class LineView(QScrollArea):
    unseen = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget()
        inner.setObjectName("rows")
        self._layout = QVBoxLayout(inner)
        self._layout.setContentsMargins(0, 6, 0, 6)
        self._layout.setSpacing(0)
        self._layout.addStretch(1)
        self.setWidget(inner)
        self._rows: dict[int, _Row] = {}
        self._font_pt = 13.0
        self.target_language: str | None = None
        self._live_row: _Row | None = None
        self.sticky = _StickyScroll(self.verticalScrollBar(), self.unseen.emit)

    def add(self, e: Entry) -> None:
        row = _Row(e, self._font_pt)
        row.set_target_language(self.target_language)
        self._rows[e.id] = row
        # Finished rows go above the live row (if any), which stays last.
        at = self._layout.count() - (2 if self._live_row is not None else 1)
        self._layout.insertWidget(at, row)
        while len(self._rows) > MAX_ENTRIES:
            oldest = next(iter(self._rows))
            self._rows.pop(oldest).deleteLater()

    def update_entry(self, e: Entry) -> None:
        if e.id in self._rows:
            self._rows[e.id].update_entry(e)

    def set_live(self, e: Entry | None) -> None:
        if e is None:
            if self._live_row is not None:
                self._live_row.deleteLater()
                self._live_row = None
            return
        if self._live_row is None:
            self._live_row = _Row(e, self._font_pt)
            self._live_row.set_target_language(self.target_language)
            self._live_row.set_live(True)
            self._layout.insertWidget(self._layout.count() - 1, self._live_row)
        else:
            self._live_row.update_entry(e)

    def rebuild(self, entries: list[Entry]) -> None:
        self.clear()
        for e in entries:
            self.add(e)
        QTimer.singleShot(0, self.sticky.to_bottom)

    def clear(self) -> None:
        for r in self._rows.values():
            r.deleteLater()
        self._rows.clear()

    def set_font_size(self, pt: float) -> None:
        self._font_pt = pt
        for r in self._rows.values():
            r.set_font(pt)


# ---------------------------------------------------------------------------------------
# Paragraph: continuous text per side, broken into paragraphs at pauses.
# ---------------------------------------------------------------------------------------

class ParagraphView(QWidget):
    unseen = pyqtSignal()

    def __init__(self):
        super().__init__()
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.left, self.right = QTextBrowser(), QTextBrowser()
        for b in (self.left, self.right):
            b.setOpenLinks(False)
            b.document().setDocumentMargin(20)
            b.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(self.left, 1)
        lay.addWidget(_divider())
        lay.addWidget(self.right, 1)
        self._stickies = [_StickyScroll(b.verticalScrollBar(), self.unseen.emit)
                          for b in (self.left, self.right)]
        self.target_language: str | None = None
        self.set_font_size(13.0)

    @property
    def sticky(self):
        return self._stickies[0]

    def render(self, entries: list[Entry], live: Entry | None = None) -> None:
        paras_l, paras_r, cur_l, cur_r = [], [], [], []
        prev_end, prev_lang = None, None
        for e in entries:
            if prev_end is not None and (e.start - prev_end > PARAGRAPH_GAP_S
                                         or e.language != prev_lang):
                paras_l.append(cur_l); paras_r.append(cur_r)
                cur_l, cur_r = [], []
            cur_l.append(self._span(e.text, e.language))
            text, style = _translation_text(e)
            if style == "pending":
                cur_r.append(f'<span style="color:{theme.MUTED}">…</span>')
            elif style == "failed":
                cur_r.append(f'<span style="color:{theme.ERROR}">[translation failed]</span>')
            elif text:
                cur_r.append(self._span(text, e.language if style == "" and e.state == "same"
                                        else self.target_language))
            prev_end, prev_lang = e.start, e.language
        if live is not None:
            dim = f'<span style="color:{theme.TEXT_2}">'
            cur_l.append(dim + self._span(live.text, live.language) + "</span>")
            text, style = _translation_text(live)
            if style != "pending" and text:
                cur_r.append(dim + self._span(text, self.target_language) + "</span>")
        if cur_l:
            paras_l.append(cur_l); paras_r.append(cur_r)

        def to_html(paras):
            return "".join(f'<p style="margin:0 0 14px 0; line-height:150%">{" ".join(p)}</p>'
                           for p in paras)
        for browser, sticky, paras in ((self.left, self._stickies[0], paras_l),
                                       (self.right, self._stickies[1], paras_r)):
            bar = browser.verticalScrollBar()
            keep = bar.value()
            stick = sticky.stick
            browser.setHtml(to_html(paras))
            bar.setValue(bar.maximum() if stick else keep)
            sticky.stick = stick

    @staticmethod
    def _span(text: str, language: str | None) -> str:
        fams = ", ".join(f"'{f}'" for f in theme.families_for(language))
        return f'<span style="font-family:{fams}">{html.escape(text)}</span>'

    def to_bottom(self):
        for s in self._stickies:
            s.to_bottom()

    def set_font_size(self, pt: float) -> None:
        for b in (self.left, self.right):
            b.setFont(theme.ui_font(pt))


# ---------------------------------------------------------------------------------------
# The framed area: shared header + empty state + the two layouts.
# ---------------------------------------------------------------------------------------

class TranscriptView(QFrame):
    def __init__(self):
        super().__init__()
        self.setObjectName("transcriptFrame")
        self.entries: list[Entry] = []
        self._by_id: dict[int, Entry] = {}
        self.live: Entry | None = None
        self.mode = "lines"
        self._font_pt = 13.0

        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.setSpacing(0)
        outer.addWidget(self._build_header())

        self.stack = QStackedWidget()
        self.empty = self._build_empty()
        self.lines = LineView()
        self.paragraphs = ParagraphView()
        for w in (self.empty, self.lines, self.paragraphs):
            self.stack.addWidget(w)
        outer.addWidget(self.stack, 1)

        self.jump = QPushButton("↓  New lines", self)
        self.jump.setObjectName("jump")
        self.jump.setCursor(Qt.CursorShape.PointingHandCursor)
        self.jump.hide()
        self.jump.clicked.connect(self._jump_to_latest)
        self.lines.unseen.connect(self._show_jump)
        self.paragraphs.unseen.connect(self._show_jump)
        self.lines.verticalScrollBar().valueChanged.connect(self._maybe_hide_jump)
        self.paragraphs.left.verticalScrollBar().valueChanged.connect(self._maybe_hide_jump)

    def _build_header(self) -> QWidget:
        head = QWidget()
        head.setObjectName("panelHeader")
        lay = QHBoxLayout(head)
        lay.setContentsMargins(20, 10, 12, 10)
        lay.setSpacing(8)

        def side(title: str):
            box = QHBoxLayout()
            box.setSpacing(8)
            t = QLabel(title.upper())
            t.setObjectName("panelTitle")
            chip = QLabel()
            chip.setObjectName("langChip")
            chip.hide()
            copy = QPushButton("Copy")
            copy.setObjectName("ghost")
            copy.setCursor(Qt.CursorShape.PointingHandCursor)
            box.addWidget(t)
            box.addWidget(chip)
            box.addStretch(1)
            box.addWidget(copy)
            return box, chip, copy

        l, self.src_chip, copy_l = side("Original")
        r, self.tgt_chip, copy_r = side("Translation")
        copy_l.clicked.connect(lambda: self._copy(copy_l, original=True))
        copy_r.clicked.connect(lambda: self._copy(copy_r, original=False))
        lay.addLayout(l, 1)
        lay.addSpacing(20)
        lay.addLayout(r, 1)
        return head

    def _build_empty(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.addStretch(1)
        self.empty_title = QLabel("Nothing yet")
        self.empty_title.setObjectName("emptyTitle")
        self.empty_hint = QLabel("Press Start, then play a video or song.\n"
                                 "Speech appears here as it's recognised.")
        self.empty_hint.setObjectName("emptyHint")
        for lbl in (self.empty_title, self.empty_hint):
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lay.addWidget(lbl)
        lay.addStretch(1)
        return w

    # ---- data ------------------------------------------------------------------------

    def add_original(self, entry_id: int, t, translating: bool) -> None:
        e = Entry(entry_id, t.start, t.language, t.text, state="pending" if translating else "off")
        self.entries.append(e)
        self._by_id[e.id] = e
        if len(self.entries) > MAX_ENTRIES:
            self._by_id.pop(self.entries.pop(0).id, None)
        self.src_chip.setText(lang_name(t.language))
        self.src_chip.show()
        if self.mode == "lines":
            self.lines.add(e)
        else:
            self.paragraphs.render(self.entries, self.live)
        self._show_content()

    def set_translation(self, entry_id: int, r) -> None:
        e = self._by_id.get(entry_id)
        if e is None:
            return
        if r.translation:
            e.translation, e.state = r.translation, "done"
        elif r.error:
            e.state = "failed"
        elif e.state == "pending":
            e.state = "same"  # no translation, no error: already in the target language
        if self.mode == "lines":
            self.lines.update_entry(e)
        else:
            self.paragraphs.render(self.entries, self.live)

    def set_live(self, e: Entry | None) -> None:
        """Show (or clear) the sentence that's still being spoken, below the finished lines."""
        self.live = e
        if self.mode == "lines":
            self.lines.set_live(e)
        else:
            self.paragraphs.render(self.entries, e)
        if e is not None:
            self._show_content(force=True)

    def set_target_language(self, code: str) -> None:
        self.tgt_chip.setText(lang_name(code))
        self.tgt_chip.show()
        self.lines.target_language = code
        self.paragraphs.target_language = code

    def clear(self) -> None:
        self.entries.clear()
        self._by_id.clear()
        self.lines.clear()
        self.paragraphs.render([])
        self.src_chip.hide()
        self.jump.hide()
        self.stack.setCurrentWidget(self.empty)

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "lines":
            self.lines.rebuild(self.entries)
        else:
            self.paragraphs.render(self.entries, self.live)
            QTimer.singleShot(0, self.paragraphs.to_bottom)
        self.jump.hide()
        self._show_content()

    def set_empty_message(self, title: str, hint: str) -> None:
        self.empty_title.setText(title)
        self.empty_hint.setText(hint)

    def change_font_size(self, delta: float) -> None:
        self._font_pt = max(9.0, min(32.0, self._font_pt + delta))
        self.lines.set_font_size(self._font_pt)
        self.paragraphs.set_font_size(self._font_pt)

    # ---- helpers ---------------------------------------------------------------------

    def _show_content(self, force: bool = False) -> None:
        if not self.entries and not force:
            self.stack.setCurrentWidget(self.empty)
        else:
            self.stack.setCurrentWidget(self.lines if self.mode == "lines" else self.paragraphs)

    def _copy(self, button: QPushButton, original: bool) -> None:
        sep = "\n" if self.mode == "lines" else " "
        if original:
            text = sep.join(e.text for e in self.entries)
        else:
            text = sep.join(_translation_text(e)[0] for e in self.entries if e.state in ("done", "same"))
        QGuiApplication.clipboard().setText(text)
        button.setText("Copied")
        QTimer.singleShot(1200, lambda: button.setText("Copy"))

    def _active_sticky(self):
        return self.lines.sticky if self.mode == "lines" else self.paragraphs.sticky

    def _show_jump(self) -> None:
        if self.stack.currentWidget() is not self.empty:
            self.jump.adjustSize()
            self._place_jump()
            self.jump.show()
            self.jump.raise_()

    def _maybe_hide_jump(self) -> None:
        if self._active_sticky().stick:
            self.jump.hide()

    def _jump_to_latest(self) -> None:
        if self.mode == "lines":
            self.lines.sticky.to_bottom()
        else:
            self.paragraphs.to_bottom()
        self.jump.hide()

    def _place_jump(self) -> None:
        self.jump.move((self.width() - self.jump.width()) // 2,
                       self.height() - self.jump.height() - 16)

    def resizeEvent(self, ev) -> None:
        super().resizeEvent(ev)
        self._place_jump()
