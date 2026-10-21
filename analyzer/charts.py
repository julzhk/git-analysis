"""Matplotlib charts for an analysis, rendered to PNG (ported from the notebook's infographic)."""
import io

import matplotlib

matplotlib.use("Agg")

import numpy as np  # noqa: E402
from matplotlib import colormaps  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402

RANK_COLOUR = {"A": "#2ecc71", "B": "#82e0aa", "C": "#f4d03f",
               "D": "#f0b27a", "E": "#e59866", "F": "#e74c3c"}
GREY = "#aab7b8"
TEXT = "#374151"
DIM = "#6b7280"
GRID = "#e5e7eb"


def _short(path: str) -> str:
    return path.split("/")[-1].removesuffix(".py")


def _style(ax, title=""):
    ax.set_facecolor("white")
    ax.tick_params(colors=DIM, labelsize=8)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("bottom", "left"):
        ax.spines[side].set_color("#d1d5db")
    ax.grid(color=GRID, lw=0.6)
    ax.set_axisbelow(True)
    if title:
        ax.set_title(title, color=TEXT, fontsize=11, loc="left", pad=8)


def _valid(files):
    return [f for f in files if f["avg_cc"] is not None and f["mi"] is not None]


def _top_bars(files, key, xlabel, fmt):
    top = sorted(files, key=lambda f: f[key], reverse=True)[:20]
    fig = Figure(figsize=(6, 6))
    ax = fig.subplots()
    _style(ax)
    ax.grid(axis="y", visible=False)
    values = [f[key] for f in top]
    bars = ax.barh(range(len(top)), values, color=[RANK_COLOUR.get(f["cc_rank"], GREY) for f in top])
    ax.set_yticks(range(len(top)), [_short(f["file"]) for f in top], fontsize=8, color=TEXT)
    ax.invert_yaxis()
    ax.set_xlabel(xlabel, color=DIM)
    pad = (max(values) if values else 1) * 0.01
    for bar, value in zip(bars, values):
        ax.text(value + pad, bar.get_y() + bar.get_height() / 2, fmt.format(value),
                va="center", fontsize=7, color=DIM)
    return fig


def top_cc(results):
    return _top_bars(_valid(results["files"]), "avg_cc", "Avg CC", "{:.1f}")


def top_change_rate(results):
    return _top_bars(_valid(results["files"]), "change_rate", "Commits / month", "{:.2f}")


def mi_hist(results):
    values = [f["mi"] for f in results["files"] if f["mi"] is not None]
    fig = Figure(figsize=(6, 4))
    ax = fig.subplots()
    _style(ax)
    _, bins, patches = ax.hist(values, bins=25, edgecolor="white")
    for patch, left in zip(patches, bins[:-1]):
        patch.set_facecolor("#2ecc71" if left >= 65 else "#f39c12" if left >= 20 else "#e74c3c")
    ax.axvline(65, color="#2ecc71", lw=1, ls="--", label="Maintainable (≥65)")
    ax.axvline(20, color="#e74c3c", lw=1, ls="--", label="Unmaintainable (<20)")
    ax.set_xlabel("Maintainability Index", color=DIM)
    ax.set_ylabel("# files", color=DIM)
    ax.legend(fontsize=8, frameon=False)
    return fig


def rank_donut(results):
    counts = {}
    for f in results["files"]:
        if f["cc_rank"] in RANK_COLOUR:
            counts[f["cc_rank"]] = counts.get(f["cc_rank"], 0) + 1
    ranks = sorted(counts)
    fig = Figure(figsize=(6, 4))
    ax = fig.subplots()
    if ranks:
        _, _, autotexts = ax.pie(
            [counts[r] for r in ranks], labels=ranks, colors=[RANK_COLOUR[r] for r in ranks],
            autopct="%1.0f%%", startangle=90, pctdistance=0.72,
            wedgeprops=dict(width=0.55, edgecolor="white"), textprops=dict(color=TEXT, fontsize=10),
        )
        for t in autotexts:
            t.set_fontsize(8)
    ax.set_aspect("equal")
    return fig


def coupling_heatmap(results):
    files = results["heatmap"]["files"]
    n = len(files)
    matrix = np.array(results["heatmap"]["matrix"], dtype=float).reshape(n, n)
    np.fill_diagonal(matrix, np.nan)
    fig = Figure(figsize=(10, 8.5))
    ax = fig.subplots()
    cmap = colormaps["YlOrRd"].copy()
    cmap.set_bad("#f3f4f6")
    im = ax.imshow(np.ma.masked_invalid(matrix), cmap=cmap, aspect="auto")
    cb = fig.colorbar(im, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("co-commits", color=DIM)
    cb.ax.tick_params(colors=DIM, labelsize=8)
    labels = [_short(f) for f in files]
    ax.set_xticks(range(n), labels, rotation=45, ha="right", fontsize=7.5, color=TEXT)
    ax.set_yticks(range(n), labels, fontsize=7.5, color=TEXT)
    for spine in ax.spines.values():
        spine.set_visible(False)
    if n > 1:
        threshold = np.nanpercentile(matrix, 90)
        vmin, vmax = np.nanmin(matrix), np.nanmax(matrix)
        for i in range(n):
            for j in range(n):
                if not np.isnan(matrix[i, j]) and matrix[i, j] and matrix[i, j] >= threshold:
                    dark_cell = (matrix[i, j] - vmin) > (vmax - vmin) * 0.6
                    ax.text(j, i, str(int(matrix[i, j])), ha="center", va="center", fontsize=6,
                            color="white" if dark_cell else "#1f2937", fontweight="bold")
    return fig


CHARTS = {
    "top_cc": top_cc,
    "top_change_rate": top_change_rate,
    "mi_hist": mi_hist,
    "rank_donut": rank_donut,
    "coupling_heatmap": coupling_heatmap,
}


def render_png(name: str, results: dict) -> bytes:
    fig = CHARTS[name](results)
    fig.set_layout_engine("tight")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="white")
    return buf.getvalue()
