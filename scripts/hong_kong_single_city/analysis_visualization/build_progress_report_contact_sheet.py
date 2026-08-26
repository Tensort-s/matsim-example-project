"""Build a compact visual index of the eight Hong Kong progress figures."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
DEFAULT_OUTPUT = REPO / "runs/hongkong/outputs/progress_report_figures_20260824"

FIGURES = [
    ("1  Model evolution", "01_hong_kong_model_evolution.png"),
    ("2  School-bus timing repair", "figure02_school_bus_walk_timing_repair.png"),
    ("3  Household physical car", "figure03_household_joint_car_timeline.png"),
    ("4  Private-car cost anatomy", "figure_04_private_car_cost_anatomy.png"),
    ("5  Finite Taxi fleet", "05_hong_kong_finite_taxi_operations.png"),
    ("8  Experienced PT fare network", "figure_8_pt_fare_network_central.png"),
    ("A  Signals and green wave", "figure_a_candidate11_signals_greenwave.png"),
    ("B  Monetary-cost geography", "figure_b_hong_kong_monetary_cost_maps.png"),
]


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/segoeui.ttf"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def build(output_dir: Path) -> Path:
    columns, rows = 2, 4
    cell_w, cell_h = 1280, 610
    header_h, gap = 52, 18
    canvas = Image.new("RGB", (columns * cell_w + gap, rows * cell_h + gap), "white")
    draw = ImageDraw.Draw(canvas)
    title_font = _font(28)
    muted = (86, 94, 94)
    divider = (220, 224, 222)
    for index, (title, filename) in enumerate(FIGURES):
        source = output_dir / filename
        if not source.exists():
            raise FileNotFoundError(source)
        image = Image.open(source).convert("RGB")
        image.thumbnail((cell_w - 36, cell_h - header_h - 28), Image.Resampling.LANCZOS)
        col, row = index % columns, index // columns
        x0 = col * cell_w + (gap if col else 0)
        y0 = row * cell_h + (gap if row else 0)
        draw.text((x0 + 18, y0 + 10), title, font=title_font, fill=muted)
        paste_x = x0 + (cell_w - image.width) // 2
        paste_y = y0 + header_h + (cell_h - header_h - image.height) // 2
        canvas.paste(image, (paste_x, paste_y))
        if col == 0:
            draw.line((cell_w + gap / 2, y0, cell_w + gap / 2, y0 + cell_h), fill=divider, width=2)
        if row < rows - 1:
            draw.line((x0, y0 + cell_h + gap / 2, x0 + cell_w, y0 + cell_h + gap / 2), fill=divider, width=2)
    target = output_dir / "00_hong_kong_progress_report_contact_sheet.png"
    canvas.save(target, quality=94, optimize=True)
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    print(build(args.output_dir))


if __name__ == "__main__":
    main()
