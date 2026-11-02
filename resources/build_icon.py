"""Icon generator for Audacity to REAPER Project Converter.

Ensures the letter 'A' and letter 'R' use the exact same font, size, weight,
and baseline height alongside a clean directional arrow.
"""

import sys
from pathlib import Path
from PIL import Image
from PySide6.QtCore import QPointF, QRectF
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QFontMetricsF,
    QGuiApplication,
    QImage,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PySide6.QtSvg import QSvgRenderer

SVG_CONTENT = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512" width="512" height="512">
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" stop-color="#1e2330"/>
      <stop offset="100%" stop-color="#101217"/>
    </linearGradient>
    <linearGradient id="arrowGrad" x1="0%" y1="0%" x2="100%" y2="0%">
      <stop offset="0%" stop-color="#0ea5e9"/>
      <stop offset="100%" stop-color="#38bdf8"/>
    </linearGradient>
    <filter id="glow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="2" stdDeviation="4" flood-color="#0ea5e9" flood-opacity="0.35"/>
    </filter>
  </defs>

  <!-- Container with subtle border -->
  <rect x="16" y="16" width="480" height="480" rx="104" ry="104" fill="url(#bg)" stroke="#334155" stroke-width="6"/>

  <!-- Bold Letter 'A' (exact same font, size, and baseline as R) -->
  <text x="125" y="322" font-family="Arial, 'Segoe UI', -apple-system, sans-serif" font-size="185" font-weight="900" fill="#f8fafc" text-anchor="middle">A</text>

  <!-- High-contrast Arrow (pointing from A to R) -->
  <g filter="url(#glow)">
    <rect x="214" y="240" width="56" height="32" rx="6" ry="6" fill="url(#arrowGrad)"/>
    <path d="M 264 218 L 306 256 L 264 294 Z" fill="url(#arrowGrad)"/>
  </g>

  <!-- Bold Letter 'R' (exact same font, size, and baseline as A) -->
  <text x="387" y="322" font-family="Arial, 'Segoe UI', -apple-system, sans-serif" font-size="185" font-weight="900" fill="#f8fafc" text-anchor="middle">R</text>
</svg>"""


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    res_dir = Path("resources")
    res_dir.mkdir(parents=True, exist_ok=True)

    # 1. Write SVG file
    svg_path = res_dir / "icon.svg"
    svg_path.write_text(SVG_CONTENT, encoding="utf-8")

    # 2. Render pixel-perfect 512x512 master image using PySide6 font engine
    size = 512
    qimg = QImage(size, size, QImage.Format_ARGB32)
    qimg.fill(0)

    p = QPainter(qimg)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)

    # Background gradient
    bg_grad = QLinearGradient(0, 0, size, size)
    bg_grad.setColorAt(0.0, QColor(30, 35, 48))
    bg_grad.setColorAt(1.0, QColor(16, 18, 24))

    p.setBrush(QBrush(bg_grad))
    p.setPen(QPen(QColor(51, 65, 85), 6))
    p.drawRoundedRect(QRectF(16, 16, 480, 480), 104, 104)

    # Single font specification applied identically to both 'A' and 'R'
    font = QFont("Arial")
    font.setPixelSize(185)
    font.setBold(True)
    font.setWeight(QFont.Weight.Black)
    p.setFont(font)

    fm = QFontMetricsF(font)
    cap_h = fm.capHeight()
    y_base = 256.0 + (cap_h / 2.0) - 2.0

    w_A = fm.horizontalAdvance("A")
    w_R = fm.horizontalAdvance("R")

    x_A = 125.0 - (w_A / 2.0)
    x_R = 387.0 - (w_R / 2.0)

    # Draw 'A'
    path_A = QPainterPath()
    path_A.addText(QPointF(x_A, y_base), font, "A")
    p.setPen(QPen(QColor(248, 250, 252), 0))
    p.setBrush(QBrush(QColor(248, 250, 252)))
    p.drawPath(path_A)

    # Draw 'R' (identical font, size, weight, baseline)
    path_R = QPainterPath()
    path_R.addText(QPointF(x_R, y_base), font, "R")
    p.drawPath(path_R)

    # Draw Arrow in center
    arrow_grad = QLinearGradient(214, 0, 306, 0)
    arrow_grad.setColorAt(0.0, QColor(14, 165, 233))
    arrow_grad.setColorAt(1.0, QColor(56, 189, 248))

    arrow_path = QPainterPath()
    arrow_path.addRoundedRect(QRectF(214, 240, 56, 32), 6, 6)
    arrow_head = QPainterPath()
    arrow_head.moveTo(264, 218)
    arrow_head.lineTo(306, 256)
    arrow_head.lineTo(264, 294)
    arrow_head.closeSubpath()
    arrow_path = arrow_path.united(arrow_head)

    p.setPen(QPen(QColor(14, 165, 233), 0))
    p.setBrush(QBrush(arrow_grad))
    p.drawPath(arrow_path)

    p.end()

    png_512_path = res_dir / "icon_512.png"
    qimg.save(str(png_512_path))

    # 3. Generate multi-resolution ICO file for Windows
    pil_img = Image.open(png_512_path)
    ico_sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    ico_path = res_dir / "icon.ico"
    pil_img.save(ico_path, format="ICO", sizes=ico_sizes)

    # 4. Generate standard resolution PNGs
    for s in [16, 24, 32, 48, 64, 128, 256]:
        resized = pil_img.resize((s, s), Image.Resampling.LANCZOS)
        resized.save(res_dir / f"icon_{s}.png")

    print("Successfully built icon.svg, icon.ico, and PNGs with matching typography.")


if __name__ == "__main__":
    main()
