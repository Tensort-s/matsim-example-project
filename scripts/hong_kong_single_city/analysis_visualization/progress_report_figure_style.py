"""Shared visual style for the 2026 Hong Kong progress-report figures."""

from __future__ import annotations

from pathlib import Path

import matplotlib as mpl


PALETTE = {
    "background": "#FFFFFF",
    "land": "#EEF1EF",
    "land_alt": "#F6F7F6",
    "boundary": "#777D7C",
    "text": "#202629",
    "muted": "#6F7676",
    "grid": "#D9DEDC",
    "blue": "#2F7895",
    "blue_light": "#8EB6C5",
    "brick": "#C45139",
    "brick_light": "#E3A08F",
    "green": "#4B8A72",
    "gold": "#D1A04A",
    "purple": "#7868A6",
    "red": "#B83E32",
}


MODE_COLORS = {
    "car": PALETTE["brick"],
    "pt": PALETTE["blue"],
    "taxi": PALETTE["purple"],
    "walk": PALETTE["green"],
    "school_bus": PALETTE["gold"],
    "car_passenger": PALETTE["brick_light"],
}


def apply_progress_report_style() -> None:
    """Apply the restrained map-first style used by the supplied reference."""
    mpl.rcParams.update(
        {
            "figure.facecolor": PALETTE["background"],
            "axes.facecolor": PALETTE["background"],
            "savefig.facecolor": PALETTE["background"],
            "font.family": "DejaVu Sans",
            "font.size": 10.5,
            "axes.titlesize": 17,
            "axes.titleweight": "normal",
            "axes.labelsize": 10.5,
            "axes.edgecolor": PALETTE["boundary"],
            "axes.labelcolor": PALETTE["text"],
            "xtick.color": PALETTE["muted"],
            "ytick.color": PALETTE["muted"],
            "text.color": PALETTE["text"],
            "legend.frameon": True,
            "legend.facecolor": PALETTE["background"],
            "legend.edgecolor": "#C8CCCB",
            "legend.framealpha": 0.94,
            "legend.fontsize": 9,
            "lines.solid_capstyle": "round",
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
        }
    )


def save_figure(fig, output_dir: Path, stem: str, *, dpi: int = 240) -> tuple[Path, Path]:
    """Write a presentation PNG and vector PDF with identical layout."""
    output_dir.mkdir(parents=True, exist_ok=True)
    png = output_dir / f"{stem}.png"
    pdf = output_dir / f"{stem}.pdf"
    fig.savefig(png, dpi=dpi, bbox_inches="tight", pad_inches=0.18)
    fig.savefig(pdf, bbox_inches="tight", pad_inches=0.18)
    return png, pdf


def add_method_note(fig, text: str, *, y: float = 0.012) -> None:
    """Add the compact centered methodology note used by the reference map."""
    fig.text(
        0.5,
        y,
        text,
        ha="center",
        va="bottom",
        color=PALETTE["muted"],
        fontsize=7.4,
        linespacing=1.08,
    )


def clean_map_axis(ax) -> None:
    ax.set_axis_off()
    ax.set_aspect("equal", adjustable="datalim")
