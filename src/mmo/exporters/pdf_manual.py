"""Deterministic PDF builder for the MMO User Manual.

Reads docs/manual/manual.yaml and chapter .md files, renders a multi-chapter PDF
with a clickable table of contents, glossary, and auto-generated appendices.

Design philosophy: the PDF should be a pleasure to read for musicians with zero
technical background, art critics, and 20-year veteran mixing engineers alike.
Clean typographic hierarchy, dark-mode-style code blocks, and enough white space
to breathe.

ReportLab is an optional dependency (``pip install .[pdf]``).  All public
functions guard against a missing installation and raise ``ImportError`` with
a clear message.
"""

from __future__ import annotations

import html
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
except ImportError:  # pragma: no cover
    _yaml = None

try:
    from reportlab.lib import colors as _colors
    from reportlab.lib.pagesizes import A4 as _A4
    from reportlab.lib.styles import ParagraphStyle as _ParagraphStyle
    from reportlab.lib.styles import getSampleStyleSheet as _getSampleStyleSheet
    from reportlab.lib.units import cm as _cm
    from reportlab.platypus import (
        BaseDocTemplate as _BaseDocTemplate,
    )
    from reportlab.platypus import (
        Frame as _Frame,
    )
    from reportlab.platypus import (
        HRFlowable as _HRFlowable,
    )
    from reportlab.platypus import (
        ListFlowable as _ListFlowable,
    )
    from reportlab.platypus import (
        ListItem as _ListItem,
    )
    from reportlab.platypus import (
        PageBreak as _PageBreak,
    )
    from reportlab.platypus import (
        PageTemplate as _PageTemplate,
    )
    from reportlab.platypus import (
        Paragraph as _Paragraph,
    )
    from reportlab.platypus import (
        Preformatted as _Preformatted,
    )
    from reportlab.platypus import (
        Spacer as _Spacer,
    )
    from reportlab.platypus import (
        Table as _Table,
    )
    from reportlab.platypus import (
        TableStyle as _TableStyle,
    )
    from reportlab.platypus.tableofcontents import TableOfContents as _TOC
    _REPORTLAB = True
except ImportError:  # pragma: no cover
    _REPORTLAB = False
    _colors = None
    _A4 = None
    _ParagraphStyle = None
    _getSampleStyleSheet = None
    _cm = None
    _BaseDocTemplate = object
    _Frame = None
    _HRFlowable = None
    _ListFlowable = None
    _ListItem = None
    _PageBreak = None
    _PageTemplate = None
    _Paragraph = None
    _Preformatted = None
    _Spacer = None
    _Table = None
    _TableStyle = None
    _TOC = None

# ---------------------------------------------------------------------------
# Colour palette (dark/rich studio aesthetic)
# ---------------------------------------------------------------------------

_C_INK = "#0d0d1a"           # Near-black page text
_C_NAVY = "#0a0a1e"          # Deep title-page background
_C_MIDNIGHT = "#12122a"      # Chapter heading accent background
_C_TEAL = "#00c9a7"          # Accent / active colour
_C_GOLD = "#f4a261"          # Warm accent for TOC dots, borders
_C_STEEL = "#4a5568"         # Muted body text / secondary
_C_RULE = "#2d3748"          # Horizontal rule colour
_C_CODE_BG = "#1a1a2e"       # Code block background (dark IDE style)
_C_CODE_FG = "#d4d4f0"       # Code block text (soft lavender-white)
_C_TABLE_HDR = "#0a0a1e"     # Table header background
_C_TABLE_ALT = "#f7f7fb"     # Table alternating row
_C_LINK = "#00c9a7"          # Hyperlink teal

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_manual_pdf(
    manifest_path: Path,
    out_path: Path,
    *,
    strict: bool = False,
    version_override: str | None = None,
) -> None:
    """Build the User Manual PDF from *manifest_path* to *out_path*.

    Args:
        manifest_path: Path to ``manual.yaml``.
        out_path: Destination PDF file path.
        strict: If ``True``, raise ``FileNotFoundError`` for any missing chapter.
        version_override: Override the version string shown on the title page.

    Raises:
        ImportError: If ``reportlab`` is not installed.
        FileNotFoundError: If manifest or (in strict mode) a chapter is missing.
        ValueError: If the manifest YAML is malformed.
    """
    if not _REPORTLAB:
        raise ImportError(
            "reportlab is not installed. Install with: pip install .[pdf]"
        )
    if _yaml is None:
        raise ImportError(
            "PyYAML is not installed. Install with: pip install pyyaml"
        )

    manifest_path = Path(manifest_path)
    out_path = Path(out_path)

    if not manifest_path.is_file():
        raise FileNotFoundError(f"Manual manifest not found: {manifest_path}")

    manifest = _yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError(
            f"manual.yaml must be a mapping; got {type(manifest).__name__}"
        )

    chapters_dir = manifest_path.parent
    chapters: list[dict[str, Any]] = manifest.get("chapters", [])
    version: str = version_override or manifest.get("version", "dev")
    glossary_file = manifest.get("glossary_file", "glossary.yaml")

    glossary_terms: list[dict[str, Any]] = []
    glossary_path = chapters_dir / glossary_file
    if glossary_path.is_file():
        gdata = _yaml.safe_load(glossary_path.read_text(encoding="utf-8"))
        if isinstance(gdata, dict):
            glossary_terms = gdata.get("terms", [])

    git_sha = _get_git_sha()
    version_label = f"v{version}" if not version.startswith("v") else version
    if git_sha:
        version_label = f"{version_label} ({git_sha})"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    builder = _ManualBuilder(
        chapters=chapters,
        chapters_dir=chapters_dir,
        glossary_terms=glossary_terms,
        version_label=version_label,
        strict=strict,
    )
    builder.build(out_path)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_git_sha() -> str:
    """Return short git SHA, or empty string if unavailable."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.strip()
    except Exception:  # noqa: BLE001
        return ""


def _esc(text: str) -> str:
    """Escape plain text for ReportLab XML Paragraphs."""
    return html.escape(str(text), quote=False)


def _inline_markup(text: str) -> str:
    """Convert ``**bold**`` and `` `code` `` to ReportLab XML tags.

    Operates on already-escaped text.
    """
    # Bold spans that survived escaping (we escape first, then substitute tags)
    text = re.sub(r"\*\*(.+?)\*\*", lambda m: f"<b>{m.group(1)}</b>", text)
    # Inline code
    text = re.sub(
        r"`([^`]+)`",
        lambda m: (
            f'<font name="Courier" color="{_C_TEAL}">{m.group(1)}</font>'
        ),
        text,
    )
    return text


def _safe_xml(raw: str) -> str:
    """Escape plain text then apply inline markup."""
    return _inline_markup(_esc(raw))


# ---------------------------------------------------------------------------
# BaseDocTemplate subclass (registers TOC headings via afterFlowable)
# ---------------------------------------------------------------------------

class _ManualDocTemplate(_BaseDocTemplate):  # type: ignore[misc]
    def __init__(self, filename: str, toc: Any, **kwargs: Any) -> None:
        super().__init__(filename, **kwargs)
        self._toc = toc

    def afterFlowable(self, flowable: Any) -> None:
        """Register TOC entries from tagged Paragraphs."""
        if not isinstance(flowable, _Paragraph):
            return
        toc_level = getattr(flowable, "_toc_level", None)
        if toc_level is None:
            return
        text = flowable.getPlainText()
        self.notify("TOCEntry", (toc_level, text, self.page))


# ---------------------------------------------------------------------------
# Numbered canvas (page numbers + running header)
# ---------------------------------------------------------------------------

def _make_canvas_factory(project_name: str, version_label: str) -> type:
    from reportlab.pdfgen.canvas import Canvas  # noqa: PLC0415

    class _NumberedCanvas(Canvas):  # type: ignore[misc]
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self._saved_page_states: list[dict[str, Any]] = []

        def showPage(self) -> None:  # noqa: N802
            self._saved_page_states.append(dict(self.__dict__))
            self._startPage()

        def save(self) -> None:
            total = len(self._saved_page_states)
            for state in self._saved_page_states:
                self.__dict__.update(state)
                self._draw_chrome(total)
                super().showPage()
            super().save()

        def _draw_chrome(self, total_pages: int) -> None:
            """Draw footer rule + page number."""
            w, h = self._pagesize  # type: ignore[attr-defined]
            page_num = self._pageNumber  # type: ignore[attr-defined]

            # Skip chrome on cover page (page 1)
            if page_num <= 1:
                return

            self.saveState()

            # Footer rule
            rule_y = 1.35 * _cm
            self.setStrokeColor(_colors.HexColor(_C_RULE))
            self.setLineWidth(0.5)
            self.line(2.5 * _cm, rule_y, w - 2.5 * _cm, rule_y)

            # Page number — right-aligned
            self.setFont("Helvetica", 7.5)
            self.setFillColor(_colors.HexColor(_C_STEEL))
            self.drawRightString(
                w - 2.5 * _cm,
                0.8 * _cm,
                f"{page_num} / {total_pages}",
            )

            # Running header — project name left, version right
            self.drawString(2.5 * _cm, 0.8 * _cm, project_name)
            self.drawRightString(w - 2.5 * _cm, 0.8 * _cm, version_label)

            self.restoreState()

    return _NumberedCanvas


# ---------------------------------------------------------------------------
# Styles
# ---------------------------------------------------------------------------

def _build_styles() -> dict[str, Any]:
    base = _getSampleStyleSheet()
    normal = base["Normal"]

    def _ps(name: str, **kw: Any) -> Any:
        parent = kw.pop("parent", normal)
        return _ParagraphStyle(name, parent=parent, **kw)

    # ---- Headings ----
    h1 = _ps(
        "ManualH1",
        fontSize=20,
        leading=25,
        spaceBefore=22,
        spaceAfter=10,
        textColor=_colors.HexColor(_C_INK),
        fontName="Helvetica-Bold",
        borderPad=0,
    )
    h2 = _ps(
        "ManualH2",
        fontSize=13,
        leading=17,
        spaceBefore=16,
        spaceAfter=6,
        textColor=_colors.HexColor(_C_INK),
        fontName="Helvetica-Bold",
        leftIndent=0,
        borderPad=0,
    )
    h3 = _ps(
        "ManualH3",
        fontSize=10.5,
        leading=14,
        spaceBefore=12,
        spaceAfter=4,
        textColor=_colors.HexColor(_C_STEEL),
        fontName="Helvetica-Bold",
    )

    # ---- Body ----
    body = _ps(
        "ManualBody",
        fontSize=10,
        leading=15,
        spaceBefore=4,
        spaceAfter=4,
        fontName="Helvetica",
        textColor=_colors.HexColor(_C_INK),
    )
    bullet = _ps(
        "ManualBullet",
        fontSize=10,
        leading=14,
        spaceBefore=2,
        spaceAfter=2,
        leftIndent=14,
        fontName="Helvetica",
        textColor=_colors.HexColor(_C_INK),
    )

    # ---- Code (Preformatted style — dark IDE look) ----
    code_pre = _ps(
        "ManualCodePre",
        fontSize=7.5,
        leading=10.5,
        fontName="Courier",
        textColor=_colors.HexColor(_C_CODE_FG),
        backColor=_colors.HexColor(_C_CODE_BG),
        leftIndent=10,
        rightIndent=10,
        spaceBefore=6,
        spaceAfter=6,
        borderWidth=0,
        borderPad=8,
    )

    # ---- TOC ----
    toc0 = _ps(
        "ManualTOC0",
        fontSize=11,
        leading=16,
        fontName="Helvetica-Bold",
        textColor=_colors.HexColor(_C_INK),
        spaceBefore=4,
        spaceAfter=2,
    )
    toc1 = _ps(
        "ManualTOC1",
        fontSize=9.5,
        leading=14,
        fontName="Helvetica",
        leftIndent=18,
        textColor=_colors.HexColor(_C_STEEL),
    )
    toc2 = _ps(
        "ManualTOC2",
        fontSize=8.5,
        leading=12,
        fontName="Helvetica",
        leftIndent=36,
        textColor=_colors.HexColor(_C_STEEL),
    )

    # ---- Title page ----
    title_main = _ps(
        "ManualTitleMain",
        fontSize=36,
        leading=42,
        fontName="Helvetica-Bold",
        textColor=_colors.white,
        spaceAfter=8,
        alignment=1,  # centred
    )
    title_sub = _ps(
        "ManualTitleSub",
        fontSize=14,
        leading=20,
        fontName="Helvetica",
        textColor=_colors.HexColor("#aaaacc"),
        spaceAfter=4,
        alignment=1,
    )
    title_version = _ps(
        "ManualTitleVersion",
        fontSize=10,
        leading=14,
        fontName="Courier",
        textColor=_colors.HexColor(_C_TEAL),
        spaceAfter=0,
        alignment=1,
    )
    title_tagline = _ps(
        "ManualTitleTagline",
        fontSize=12,
        leading=18,
        fontName="Helvetica-Oblique",
        textColor=_colors.HexColor("#ccccee"),
        spaceAfter=0,
        alignment=1,
    )

    # ---- Appendix label ----
    appendix_label = _ps(
        "ManualAppendixLabel",
        fontSize=10,
        leading=14,
        fontName="Courier",
        textColor=_colors.HexColor(_C_TEAL),
        spaceBefore=0,
        spaceAfter=4,
    )

    return {
        "h1": h1,
        "h2": h2,
        "h3": h3,
        "body": body,
        "bullet": bullet,
        "code_pre": code_pre,
        "toc0": toc0,
        "toc1": toc1,
        "toc2": toc2,
        "title_main": title_main,
        "title_sub": title_sub,
        "title_version": title_version,
        "title_tagline": title_tagline,
        "appendix_label": appendix_label,
    }


# ---------------------------------------------------------------------------
# Code block — Preformatted (splits across pages) with IDE-dark look
# ---------------------------------------------------------------------------

def _make_code_block(text: str, styles: dict[str, Any]) -> Any:
    """Return a Preformatted flowable with dark IDE background.

    ``Preformatted`` is a ReportLab built-in that preserves whitespace and
    splits across page boundaries, unlike a single-cell Table.
    """
    return _Preformatted(text.rstrip(), styles["code_pre"])


# ---------------------------------------------------------------------------
# Decorative section divider
# ---------------------------------------------------------------------------

def _divider(styles: dict[str, Any]) -> list[Any]:
    """Thin teal rule with a little breathing room."""
    return [
        _Spacer(1, 0.25 * _cm),
        _HRFlowable(
            width="100%",
            thickness=0.75,
            color=_colors.HexColor(_C_TEAL),
            spaceAfter=0.2 * _cm,
        ),
    ]


# ---------------------------------------------------------------------------
# Minimal Markdown parser
# ---------------------------------------------------------------------------

_IMG_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


def _parse_markdown(
    text: str,
    styles: dict[str, Any],
    *,
    chapters_dir: Path | None = None,
    usable_width: float | None = None,
) -> list[Any]:
    """Parse a minimal Markdown subset into ReportLab flowables.

    Supported:
    - ATX headings: ``#`` ``##`` ``###``
    - Fenced code blocks (``` or ~~~) — splittable Preformatted
    - Bullet lists (``- `` / ``* ``)
    - Blank-line-separated paragraphs
    - Inline ``**bold**`` and `` `code` ``
    - Images: ``![alt](relative/path.png)`` — embedded if file exists,
      otherwise rendered as a ``[IMAGE: alt]`` placeholder paragraph.
    """
    flowables: list[Any] = []
    lines = text.splitlines()
    i = 0
    para_buf: list[str] = []
    bullet_buf: list[str] = []

    def _flush_para() -> None:
        if para_buf:
            content = " ".join(para_buf).strip()
            if content:
                flowables.append(
                    _Paragraph(_safe_xml(content), styles["body"])
                )
            para_buf.clear()

    def _flush_bullets() -> None:
        if bullet_buf:
            items = [
                _ListItem(
                    _Paragraph(_safe_xml(b), styles["bullet"]),
                    bulletColor=_colors.HexColor(_C_TEAL),
                    leftIndent=20,
                )
                for b in bullet_buf
            ]
            flowables.append(_ListFlowable(items, bulletType="bullet"))
            bullet_buf.clear()

    while i < len(lines):
        line = lines[i]

        # Fenced code block
        if line.startswith("```") or line.startswith("~~~"):
            _flush_para()
            _flush_bullets()
            fence_char = line[:3]
            i += 1
            code_lines: list[str] = []
            while i < len(lines) and not lines[i].startswith(fence_char):
                code_lines.append(lines[i])
                i += 1
            i += 1  # skip closing fence
            flowables.append(_make_code_block("\n".join(code_lines), styles))
            continue

        # Image reference: ![alt](path)
        img_match = _IMG_RE.fullmatch(line.strip())
        if img_match:
            _flush_para()
            _flush_bullets()
            alt_text = img_match.group(1)
            img_ref = img_match.group(2).strip()
            img_embedded = False
            if (
                _REPORTLAB
                and chapters_dir is not None
                and not img_ref.startswith(("http://", "https://"))
            ):
                img_path = (chapters_dir / img_ref).resolve()
                if img_path.is_file():
                    try:
                        from PIL import Image as _PILImage  # noqa: PLC0415
                        from reportlab.platypus import Image as _RLImage  # noqa: PLC0415
                        max_w = usable_width if usable_width is not None else 14.0 * _cm
                        with _PILImage.open(img_path) as _pil:
                            orig_w, orig_h = _pil.size
                        embed_h = max_w * orig_h / orig_w if orig_w > 0 else max_w
                        flowables.append(
                            _RLImage(str(img_path), width=max_w, height=embed_h)
                        )
                        flowables.append(_Spacer(1, 0.3 * _cm))
                        img_embedded = True
                    except Exception:  # noqa: BLE001
                        pass
            if not img_embedded:
                placeholder = f"[IMAGE: {_esc(alt_text or img_ref)}]"
                flowables.append(_Paragraph(placeholder, styles["body"]))
            i += 1
            continue

        # ATX headings
        if line.startswith("#"):
            _flush_para()
            _flush_bullets()
            level = len(line) - len(line.lstrip("#"))
            heading_text = line.lstrip("#").strip()
            if level == 1:
                flowables.extend(_divider(styles))
                p = _Paragraph(_esc(heading_text), styles["h1"])
                p._toc_level = 0  # type: ignore[attr-defined]
            elif level == 2:
                p = _Paragraph(_esc(heading_text), styles["h2"])
                p._toc_level = 1  # type: ignore[attr-defined]
            else:
                p = _Paragraph(_esc(heading_text), styles["h3"])
                p._toc_level = 2  # type: ignore[attr-defined]
            flowables.append(p)
            i += 1
            continue

        # Bullet list items
        if line.startswith("- ") or line.startswith("* "):
            _flush_para()
            bullet_buf.append(line[2:].strip())
            i += 1
            continue

        # Blank line → flush
        if not line.strip():
            _flush_para()
            _flush_bullets()
            i += 1
            continue

        # Continuation of a bullet (indented)
        if bullet_buf and line.startswith("  "):
            bullet_buf[-1] = bullet_buf[-1] + " " + line.strip()
            i += 1
            continue

        # Body paragraph line
        if bullet_buf:
            _flush_bullets()
        para_buf.append(line)
        i += 1

    _flush_para()
    _flush_bullets()
    return flowables


# ---------------------------------------------------------------------------
# Data table
# ---------------------------------------------------------------------------

def _data_table(
    headers: list[str],
    rows: list[list[str]],
    col_widths: list[float | str],
    styles: dict[str, Any],
) -> Any:
    """Build a styled data table."""
    cell_style = _ParagraphStyle(
        "CellStyle",
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=_colors.HexColor(_C_INK),
    )
    hdr_style = _ParagraphStyle(
        "CellHdrStyle",
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=_colors.white,
    )

    header_row = [_Paragraph(h, hdr_style) for h in headers]
    body_rows = [
        [_Paragraph(_esc(str(cell)), cell_style) for cell in row]
        for row in rows
    ]
    data = [header_row] + body_rows

    tbl_style = [
        ("BACKGROUND", (0, 0), (-1, 0), _colors.HexColor(_C_TABLE_HDR)),
        ("TOPPADDING", (0, 0), (-1, 0), 7),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 1), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 1), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [
            _colors.white,
            _colors.HexColor(_C_TABLE_ALT),
        ]),
        ("GRID", (0, 0), (-1, -1), 0.25, _colors.HexColor("#d0d0e0")),
        ("LINEBELOW", (0, 0), (-1, 0), 1.5, _colors.HexColor(_C_TEAL)),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]

    tbl = _Table(data, colWidths=col_widths, repeatRows=1)
    tbl.setStyle(_TableStyle(tbl_style))
    return tbl


# ---------------------------------------------------------------------------
# Title page canvas drawing
# ---------------------------------------------------------------------------

def _make_title_page_flowable(version_label: str) -> Any:
    """Return a Flowable that draws a full-bleed dark cover page."""
    from reportlab.platypus.flowables import Flowable  # noqa: PLC0415

    class _TitlePage(Flowable):  # type: ignore[misc]
        def __init__(self) -> None:
            super().__init__()
            self.width = 0
            self.height = 0

        def wrap(self, avail_w: float, avail_h: float) -> tuple[float, float]:
            self.width = avail_w
            self.height = avail_h
            return avail_w, avail_h

        def draw(self) -> None:  # noqa: D102
            c = self.canv
            w = self.width
            h = self.height

            # Background rectangle
            c.setFillColor(_colors.HexColor(_C_NAVY))
            c.rect(0, 0, w, h, fill=1, stroke=0)

            # Subtle bottom gradient band (a series of thin rectangles)
            band_h = h * 0.25
            for step in range(30):
                alpha = step / 30.0
                grey = 0.05 + alpha * 0.08
                c.setFillColorRGB(grey * 0.4, grey * 0.4, grey * 0.7)
                y = step * (band_h / 30)
                c.rect(0, y, w, band_h / 30, fill=1, stroke=0)

            # Teal accent line
            c.setStrokeColor(_colors.HexColor(_C_TEAL))
            c.setLineWidth(2.5)
            c.line(w * 0.1, h * 0.38, w * 0.9, h * 0.38)

            # Gold thin rule above teal
            c.setStrokeColor(_colors.HexColor(_C_GOLD))
            c.setLineWidth(0.75)
            c.line(w * 0.1, h * 0.38 + 5, w * 0.9, h * 0.38 + 5)

            # Title text — "MMO"
            c.setFillColor(_colors.white)
            c.setFont("Helvetica-Bold", 56)
            c.drawCentredString(w / 2, h * 0.58, "MMO")

            # Subtitle
            c.setFont("Helvetica-Bold", 22)
            c.setFillColor(_colors.HexColor("#aaaacc"))
            c.drawCentredString(w / 2, h * 0.50, "User Manual")

            # Tagline
            c.setFont("Helvetica-Oblique", 12)
            c.setFillColor(_colors.HexColor("#9999bb"))
            c.drawCentredString(
                w / 2,
                h * 0.44,
                "Mix Marriage Offline — offline, deterministic stem mixing",
            )

            # Version chip
            chip_w = 180
            chip_h = 22
            chip_x = (w - chip_w) / 2
            chip_y = h * 0.36 - chip_h
            c.setFillColor(_colors.HexColor(_C_TEAL))
            c.roundRect(chip_x, chip_y, chip_w, chip_h, 4, fill=1, stroke=0)
            c.setFillColor(_colors.HexColor(_C_NAVY))
            c.setFont("Courier-Bold", 10)
            c.drawCentredString(w / 2, chip_y + 6, version_label)

            # Footer credit
            c.setFont("Helvetica", 8)
            c.setFillColor(_colors.HexColor("#666688"))
            c.drawCentredString(
                w / 2,
                h * 0.05,
                "Generated deterministically — no timestamps, no drift.",
            )

    return _TitlePage()


# ---------------------------------------------------------------------------
# Main builder class
# ---------------------------------------------------------------------------

class _ManualBuilder:
    def __init__(
        self,
        *,
        chapters: list[dict[str, Any]],
        chapters_dir: Path,
        glossary_terms: list[dict[str, Any]],
        version_label: str,
        strict: bool,
    ) -> None:
        self._chapters = chapters
        self._chapters_dir = chapters_dir
        self._glossary_terms = glossary_terms
        self._version_label = version_label
        self._strict = strict
        self._styles = _build_styles()

    def build(self, out_path: Path) -> None:
        toc = _TOC()
        toc.levelStyles = [
            self._styles["toc0"],
            self._styles["toc1"],
            self._styles["toc2"],
        ]
        toc.dotsMinLevel = 0
        toc.tableStyle = _TableStyle([
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 1),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
        ])

        canvas_factory = _make_canvas_factory(
            "Mix Marriage Offline", self._version_label
        )

        page_w, page_h = _A4
        margin_l = 2.5 * _cm
        margin_r = 2.5 * _cm
        margin_t = 2.5 * _cm
        margin_b = 2.2 * _cm

        doc = _ManualDocTemplate(
            str(out_path),
            toc,
            pagesize=_A4,
            leftMargin=margin_l,
            rightMargin=margin_r,
            topMargin=margin_t,
            bottomMargin=margin_b,
        )

        frame = _Frame(
            margin_l,
            margin_b,
            page_w - margin_l - margin_r,
            page_h - margin_t - margin_b,
            id="main",
        )
        doc.addPageTemplates([_PageTemplate(id="main", frames=[frame])])

        usable_width = page_w - margin_l - margin_r
        story = self._build_story(toc, usable_width=usable_width)
        doc.multiBuild(story, canvasmaker=canvas_factory)

    def _build_story(self, toc: Any, *, usable_width: float | None = None) -> list[Any]:
        s = self._styles
        story: list[Any] = []

        # ---- Cover page ----
        story.append(_make_title_page_flowable(self._version_label))
        story.append(_PageBreak())

        # ---- Table of Contents ----
        toc_h = _Paragraph("Contents", s["h1"])
        toc_h._toc_level = None  # type: ignore[attr-defined]
        story.append(toc_h)
        story.append(_Spacer(1, 0.4 * _cm))
        story.append(toc)
        story.append(_PageBreak())

        # ---- Chapters ----
        for ch in self._chapters:
            chapter_file = ch.get("file", "")
            chapter_path = self._chapters_dir / chapter_file
            if not chapter_path.is_file():
                if self._strict:
                    raise FileNotFoundError(
                        f"Chapter file missing (strict mode): {chapter_path}"
                    )
                story.append(
                    _Paragraph(
                        f"[MISSING CHAPTER: {_esc(chapter_file)}]",
                        s["body"],
                    )
                )
                story.append(_PageBreak())
                continue

            text = chapter_path.read_text(encoding="utf-8")
            story.extend(
                _parse_markdown(
                    text,
                    s,
                    chapters_dir=self._chapters_dir,
                    usable_width=usable_width,
                )
            )
            story.append(_PageBreak())

        # ---- Glossary ----
        story.extend(self._build_glossary())
        story.append(_PageBreak())

        # ---- Appendices ----
        story.extend(self._build_appendix_help())
        story.append(_PageBreak())
        story.extend(self._build_appendix_targets())
        story.append(_PageBreak())
        story.extend(self._build_appendix_locks())
        story.append(_PageBreak())
        story.extend(self._build_appendix_layouts())
        story.append(_PageBreak())
        story.extend(self._build_appendix_presets())

        return story

    def _section_heading(self, text: str, level: int = 0) -> Any:
        style = {0: "h1", 1: "h2", 2: "h3"}.get(level, "h2")
        p = _Paragraph(_esc(text), self._styles[style])
        p._toc_level = level  # type: ignore[attr-defined]
        return p

    def _appendix_header(self, label: str, title: str) -> list[Any]:
        """Return [label paragraph, h1-level title paragraph]."""
        s = self._styles
        return [
            _Paragraph(_esc(label), s["appendix_label"]),
            self._section_heading(title, 0),
            _Spacer(1, 0.2 * _cm),
        ]

    # ------------------------------------------------------------------
    # Glossary
    # ------------------------------------------------------------------

    def _build_glossary(self) -> list[Any]:
        s = self._styles
        flowables: list[Any] = [
            _Paragraph("Glossary", s["appendix_label"]),
            self._section_heading("Glossary", 0),
            _Spacer(1, 0.3 * _cm),
        ]

        terms = sorted(
            self._glossary_terms, key=lambda t: t.get("term", "").lower()
        )
        for entry in terms:
            term = str(entry.get("term", ""))
            definition = str(entry.get("definition", "")).strip()
            pro_note = str(entry.get("pro_note", "") or "").strip()
            see_also: list[str] = entry.get("see_also", []) or []

            # Term name in teal bold
            term_para = _Paragraph(
                f'<font color="{_C_TEAL}"><b>{_esc(term)}</b></font>',
                s["h3"],
            )
            flowables.append(term_para)

            if definition:
                flowables.append(
                    _Paragraph(_safe_xml(definition), s["body"])
                )
            if pro_note:
                flowables.append(
                    _Paragraph(
                        f'<i>Pro note:</i> {_safe_xml(pro_note)}',
                        s["body"],
                    )
                )
            if see_also:
                also_text = ", ".join(
                    f'<i>{_esc(t)}</i>' for t in see_also
                )
                flowables.append(
                    _Paragraph(f"See also: {also_text}", s["body"])
                )
            flowables.append(_Spacer(1, 0.2 * _cm))

        return flowables

    # ------------------------------------------------------------------
    # Appendix A — CLI reference
    # ------------------------------------------------------------------

    def _build_appendix_help(self) -> list[Any]:
        s = self._styles
        flowables: list[Any] = self._appendix_header(
            "Appendix A", "CLI Reference"
        )
        flowables.append(
            _Paragraph(
                "Full output of <font name='Courier'>python -m mmo --help</font>, "
                "generated deterministically from the installed CLI.",
                s["body"],
            )
        )
        flowables.append(_Spacer(1, 0.2 * _cm))

        try:
            result = subprocess.run(
                [sys.executable, "-m", "mmo", "--help"],
                capture_output=True,
                text=True,
                check=False,
            )
            help_text = result.stdout or result.stderr or "(no output)"
        except Exception as exc:  # noqa: BLE001
            help_text = f"(error running mmo --help: {exc})"

        flowables.append(_make_code_block(help_text.rstrip(), s))
        return flowables

    # ------------------------------------------------------------------
    # Appendix B — Render targets
    # ------------------------------------------------------------------

    def _build_appendix_targets(self) -> list[Any]:
        s = self._styles
        flowables: list[Any] = self._appendix_header(
            "Appendix B", "Render Targets"
        )
        flowables.append(
            _Paragraph(
                "All render target IDs from the registry, sorted deterministically.",
                s["body"],
            )
        )
        flowables.append(_Spacer(1, 0.2 * _cm))

        try:
            from mmo.core.registries.render_targets_registry import (  # noqa: PLC0415
                load_render_targets_registry,
            )
            reg = load_render_targets_registry()
            rows: list[list[str]] = []
            for tid in sorted(reg.list_target_ids()):
                t = reg.get_target(tid)
                layout_id = str(t.get("layout_id", ""))
                label = str(t.get("label", ""))
                aliases = ", ".join(
                    str(a) for a in (t.get("aliases") or [])
                )
                rows.append([tid, layout_id, label, aliases])
        except Exception as exc:  # noqa: BLE001
            rows = [[f"(error: {exc})", "", "", ""]]

        page_w, _ = _A4
        usable = page_w - 5.0 * _cm
        flowables.append(
            _data_table(
                ["Target ID", "Layout ID", "Label", "Aliases"],
                rows,
                [usable * 0.30, usable * 0.22, usable * 0.24, usable * 0.24],
                s,
            )
        )
        return flowables

    # ------------------------------------------------------------------
    # Appendix C — Scene locks
    # ------------------------------------------------------------------

    def _build_appendix_locks(self) -> list[Any]:
        s = self._styles
        flowables: list[Any] = self._appendix_header(
            "Appendix C", "Scene Locks"
        )
        flowables.append(
            _Paragraph(
                "All scene lock IDs from the registry, sorted deterministically.",
                s["body"],
            )
        )
        flowables.append(_Spacer(1, 0.2 * _cm))

        try:
            from mmo.core.scene_locks import list_scene_locks  # noqa: PLC0415
            locks = list_scene_locks()
            rows: list[list[str]] = []
            for lock in sorted(locks, key=lambda lk: lk.get("lock_id", "")):
                rows.append([
                    str(lock.get("lock_id", "")),
                    str(lock.get("label", "")),
                    str(lock.get("description", "")),
                    str(lock.get("severity", "")),
                ])
        except Exception as exc:  # noqa: BLE001
            rows = [[f"(error: {exc})", "", "", ""]]

        page_w, _ = _A4
        usable = page_w - 5.0 * _cm
        flowables.append(
            _data_table(
                ["Lock ID", "Label", "Description", "Severity"],
                rows,
                [usable * 0.26, usable * 0.18, usable * 0.42, usable * 0.14],
                s,
            )
        )
        return flowables

    # ------------------------------------------------------------------
    # Appendix D — Layout standards
    # ------------------------------------------------------------------

    def _build_appendix_layouts(self) -> list[Any]:
        s = self._styles
        flowables: list[Any] = self._appendix_header(
            "Appendix D", "Layout Standards"
        )
        flowables.append(
            _Paragraph(
                "The five channel-ordering standards supported by MMO. "
                "SMPTE is the canonical internal standard; all others are "
                "remapped at the import/export boundary.",
                s["body"],
            )
        )
        flowables.append(_Spacer(1, 0.2 * _cm))

        _DESCRIPTIONS = {
            "SMPTE": "Canonical internal processing standard.",
            "FILM": "Pro Tools / cinema standard.",
            "LOGIC_PRO": "Logic Pro / DTS standard.",
            "VST3": "Steinberg VST3 standard.",
            "AAF": "AAF/OMF/XML interchange standard.",
        }

        try:
            from mmo.core.speaker_layout import LayoutStandard  # noqa: PLC0415
            rows: list[list[str]] = [
                [ls.value, _DESCRIPTIONS.get(ls.value, "")]
                for ls in LayoutStandard
            ]
        except Exception as exc:  # noqa: BLE001
            rows = [[f"(error: {exc})", ""]]

        page_w, _ = _A4
        usable = page_w - 5.0 * _cm
        flowables.append(
            _data_table(
                ["Standard", "Description"],
                rows,
                [usable * 0.25, usable * 0.75],
                s,
            )
        )
        return flowables

    # ------------------------------------------------------------------
    # Appendix E — Presets
    # ------------------------------------------------------------------

    def _build_appendix_presets(self) -> list[Any]:
        s = self._styles
        flowables: list[Any] = self._appendix_header(
            "Appendix E", "Built-in Presets"
        )
        flowables.append(
            _Paragraph(
                "All built-in presets, sorted deterministically by preset ID.",
                s["body"],
            )
        )
        flowables.append(_Spacer(1, 0.2 * _cm))

        try:
            from mmo.core.presets import list_presets  # noqa: PLC0415
            from mmo.resources import presets_dir  # noqa: PLC0415
            presets = list_presets(presets_dir())
            rows: list[list[str]] = []
            for p in sorted(presets, key=lambda x: x.get("preset_id", "")):
                rows.append([
                    str(p.get("preset_id", "")),
                    str(p.get("label", "")),
                    str(p.get("description", "")),
                ])
        except Exception as exc:  # noqa: BLE001
            rows = [[f"(error: {exc})", "", ""]]

        page_w, _ = _A4
        usable = page_w - 5.0 * _cm
        flowables.append(
            _data_table(
                ["Preset ID", "Label", "Description"],
                rows,
                [usable * 0.32, usable * 0.20, usable * 0.48],
                s,
            )
        )
        return flowables
