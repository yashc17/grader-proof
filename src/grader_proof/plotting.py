"""Figures for the write-up (M5): one restrained style, and the hero figure.

The hero figure reads only the table `make rq3` writes (`results/rq3.csv`), its rows for all
tasks. Each condition gets its exploit rate with the 95% interval, replay and adaptive run apart,
next to its oracle acceptance. Colour is never the only cue: the two measurements also differ in
marker shape and fill, and in vertical position, so the figure reads in grayscale.

    python -m grader_proof.plotting --table results/rq3.csv --out figures [--label pilot]
"""

import argparse
import csv
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from pydantic import BaseModel, ConfigDict

from grader_proof.task_builder import CONDITIONS

Measurement = Literal["replay", "adaptive"]

CONDITION_LABELS = {
    "baseline": "Baseline",
    "h1": "H1 restore tests",
    "h2": "H2 integrity check",
    "h3": "H3 held-out tests",
    "h4": "H4 property checks",
    "all": "All",
}
INK = "#222222"
MUTED = "#6b6b6b"
GRID = "#e3e3e3"
ORACLE_BAR = "#bdbdbd"
# Dark blue and burnt orange differ in lightness as well as hue.
COLORS: dict[Measurement, str] = {"replay": "#1f4e79", "adaptive": "#c55a11"}
MARKERS: dict[Measurement, str] = {"replay": "o", "adaptive": "s"}
LEGEND_LABELS: dict[Measurement, str] = {
    "replay": "Replay of Baseline attacks",
    "adaptive": "Adaptive red team",
}
OFFSETS: dict[Measurement, float] = {"replay": -0.17, "adaptive": 0.17}
# README width. PNGs are saved at twice that, so they stay sharp on high-density screens.
WIDTH_INCHES = 8.0
PNG_DPI = 200


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class RatePoint(Frozen):
    condition: str
    measurement: Measurement
    rate: float
    low: float
    high: float
    exploits: int
    graded: int
    ungraded: int

    @property
    def label(self) -> str:
        text = f"{self.exploits}/{self.graded}"
        return f"{text} ({self.ungraded} ungraded)" if self.ungraded else text


class OraclePoint(Frozen):
    condition: str
    accepted: int
    runs: int


def hero_series(table: Path) -> tuple[list[RatePoint], list[OraclePoint]]:
    """The exploit rates and oracle counts for all tasks, in `CONDITIONS` order.

    A rate needs at least one graded attempt; a condition with none, or without the run, has no
    point. Only the rows for all tasks carry intervals, so only they are read.
    """
    with table.open() as file:
        rows = {row["condition"]: row for row in csv.DictReader(file) if row["scope"] == "all"}
    rates: list[RatePoint] = []
    oracle: list[OraclePoint] = []
    for condition in (c for c in CONDITIONS if c in rows):
        row = rows[condition]
        for measurement in ("replay", "adaptive"):
            if row[f"{measurement}_rate"]:
                rates.append(
                    RatePoint(
                        condition=condition,
                        measurement=measurement,
                        rate=float(row[f"{measurement}_rate"]),
                        low=float(row[f"{measurement}_rate_low"]),
                        high=float(row[f"{measurement}_rate_high"]),
                        exploits=int(row[f"{measurement}_exploits"]),
                        graded=int(row[f"{measurement}_attempts"])
                        - int(row[f"{measurement}_ungraded"]),
                        ungraded=int(row[f"{measurement}_ungraded"]),
                    )
                )
        if int(row["oracle_runs"]):
            oracle.append(
                OraclePoint(
                    condition=condition,
                    accepted=int(row["oracle_accepted"]),
                    runs=int(row["oracle_runs"]),
                )
            )
    return rates, oracle


def apply_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 11,
            "axes.titlesize": 12,
            "axes.labelsize": 11,
            "axes.edgecolor": MUTED,
            "axes.labelcolor": INK,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.grid.axis": "x",
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "xtick.color": INK,
            "ytick.color": INK,
            "ytick.major.size": 0,
            "text.color": INK,
            "legend.frameon": False,
            # Fixed ids, so the same data gives the same SVG.
            "svg.hashsalt": "grader-proof",
        }
    )


def hero_figure(
    rates: Sequence[RatePoint], oracle: Sequence[OraclePoint], label: str | None = None
) -> Figure:
    """Exploit rate per condition with 95% intervals (left) next to oracle acceptance (right)."""
    shown = {p.condition for p in rates} | {p.condition for p in oracle}
    conditions = [c for c in CONDITIONS if c in shown]
    row_of = {condition: i for i, condition in enumerate(conditions)}
    height = 1.75 + 0.55 * len(conditions)
    fig, (left, right) = plt.subplots(
        1,
        2,
        figsize=(WIDTH_INCHES, height),
        sharey=True,
        gridspec_kw={"width_ratios": [3, 1], "wspace": 0.08},
    )

    for p in rates:
        y = row_of[p.condition] + OFFSETS[p.measurement]
        color = COLORS[p.measurement]
        left.errorbar(
            p.rate * 100,
            y,
            xerr=[[(p.rate - p.low) * 100], [(p.high - p.rate) * 100]],
            fmt=MARKERS[p.measurement],
            color=color,
            markerfacecolor=color if p.measurement == "replay" else "white",
            markeredgewidth=1.5,
            markersize=7,
            elinewidth=1.5,
            capsize=3,
        )
        left.annotate(
            p.label,
            (p.high * 100, y),
            xytext=(8, 0),
            textcoords="offset points",
            va="center",
            fontsize=9,
            color=MUTED,
        )
    left.set_xlim(-4, 112)
    left.set_xticks([0, 25, 50, 75, 100])
    left.set_xlabel("Exploit rate (%), 95% interval")
    left.set_yticks(range(len(conditions)), [CONDITION_LABELS[c] for c in conditions])
    left.set_ylim(len(conditions) - 0.5, -0.5)

    for p in oracle:
        y = row_of[p.condition]
        right.barh(y, p.accepted / p.runs * 100, height=0.5, color=ORACLE_BAR)
        right.text(4, y, f"{p.accepted}/{p.runs}", va="center", fontsize=9, color=INK)
    right.set_xlim(0, 100)
    right.set_xticks([0, 50, 100])
    right.set_xlabel("Oracle accepted (%)")
    right.tick_params(axis="y", left=False)

    title = "Exploit rate and oracle acceptance by condition"
    if label:
        title = f"{label.upper()} DATA, NOT A RESULT. " + title
    fig.suptitle(title, x=0.02, ha="left", fontsize=12, fontweight="bold")  # pyright: ignore[reportUnknownMemberType]
    handles = [
        Line2D(
            [],
            [],
            marker=MARKERS[m],
            linestyle="",
            color=COLORS[m],
            markerfacecolor=COLORS[m] if m == "replay" else "white",
            markeredgewidth=1.5,
            markersize=7,
            label=LEGEND_LABELS[m],
        )
        for m in ("replay", "adaptive")
    ]
    # Heights in inches, so the layout holds for any number of conditions.
    fig.legend(  # pyright: ignore[reportUnknownMemberType]
        handles=handles,
        loc="upper left",
        bbox_to_anchor=(0.01, 1 - 0.42 / height),
        ncol=2,
        handletextpad=0.3,
        columnspacing=1.5,
    )
    fig.text(  # pyright: ignore[reportUnknownMemberType]
        0.02,
        0.12 / height,
        "Labels: exploits / graded patches (patches that did not apply are not graded). "
        "Replay cannot test H3, or H3 within All, fairly (ADR 0010).",
        fontsize=8,
        color=MUTED,
    )
    fig.subplots_adjust(left=0.23, right=0.98, top=1 - 0.95 / height, bottom=0.8 / height)
    return fig


def save(fig: Figure, out_dir: Path, name: str) -> list[Path]:
    """Writes `name.svg` and `name.png`, without timestamps, so reruns give the same files."""
    out_dir.mkdir(parents=True, exist_ok=True)
    svg, png = out_dir / f"{name}.svg", out_dir / f"{name}.png"
    fig.savefig(svg, metadata={"Date": None})  # pyright: ignore[reportUnknownMemberType]
    fig.savefig(png, dpi=PNG_DPI, metadata={"Software": None})  # pyright: ignore[reportUnknownMemberType]
    plt.close(fig)
    return [svg, png]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--table", type=Path, default=Path("results/rq3.csv"))
    parser.add_argument("--out", type=Path, default=Path("figures"))
    parser.add_argument("--label", help="marks the title, e.g. 'pilot', so it is not a result")
    args = parser.parse_args()
    if not args.table.exists():
        raise SystemExit(f"{args.table} does not exist; run `make rq3` first")
    apply_style()
    rates, oracle = hero_series(args.table)
    for path in save(hero_figure(rates, oracle, args.label), args.out, "hero"):
        print(path)


if __name__ == "__main__":
    main()
