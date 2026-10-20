"""Matplotlib charts for an analysis, rendered to PNG (ported from the notebook's infographic)."""
import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.patches as mpatches  # noqa: E402
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


def _quantile(values, q):
    return float(np.quantile(values, q)) if values else 0.0


def _valid(files):
    return [f for f in files if f["avg_cc"] is not None and f["mi"] is not None]


def bubble(results):
    files = _valid(results["files"])
    fig = Figure(figsize=(12, 5.5))
    ax = fig.subplots()
    _style(ax)
    ax.scatter([f["change_rate"] for f in files], [f["avg_cc"] for f in files],
               s=np.clip([f["loc"] * 1.5 for f in files], 20, 800),
               c=[RANK_COLOUR.get(f["cc_rank"], GREY) for f in files],
               alpha=0.7, edgecolors="#1f293740", linewidths=0.5)
    cc_threshold = _quantile([f["avg_cc"] for f in files], 0.80)
    cr_threshold = _quantile([f["change_rate"] for f in files], 0.70)
    for f in files:
        if f["avg_cc"] >= cc_threshold and f["change_rate"] >= cr_threshold:
            ax.annotate(_short(f["file"]), (f["change_rate"], f["avg_cc"]),
                        xytext=(6, 4), textcoords="offset points", fontsize=7, color=TEXT)
    ax.set_xlabel("Commits per month (change rate)", color=DIM)
    ax.set_ylabel("Avg cyclomatic complexity", color=DIM)
    ax.axhline(5, color="#f39c12", lw=0.8, ls="--", alpha=0.7)
    ax.axhline(10, color="#e74c3c", lw=0.8, ls="--", alpha=0.7)
    ax.legend(handles=[mpatches.Patch(color=c, label=f"Rank {r}") for r, c in RANK_COLOUR.items()],
              loc="upper right", ncol=6, fontsize=7.5, frameon=False)
    return fig


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


def churn_loc(results):
    files = results["files"]
    fig = Figure(figsize=(12, 5))
    ax = fig.subplots()
    _style(ax)
    ax.scatter([f["loc"] for f in files], [f["churn"] for f in files], s=40,
               c=[RANK_COLOUR.get(f["cc_rank"], GREY) for f in files],
               alpha=0.75, edgecolors="#1f293740", linewidths=0.4)
    threshold = _quantile([f["churn"] for f in files], 0.90)
    for f in files:
        if f["churn"] and f["churn"] >= threshold:
            ax.annotate(_short(f["file"]), (f["loc"], f["churn"]),
                        xytext=(5, 3), textcoords="offset points", fontsize=7, color=TEXT)
    ax.set_xlabel("Lines of code (non-blank, non-comment)", color=DIM)
    ax.set_ylabel("Total churn (lines added + deleted)", color=DIM)
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
    "bubble": bubble,
    "top_cc": top_cc,
    "top_change_rate": top_change_rate,
    "mi_hist": mi_hist,
    "rank_donut": rank_donut,
    "churn_loc": churn_loc,
    "coupling_heatmap": coupling_heatmap,
}


def render_png(name: str, results: dict) -> bytes:
    fig = CHARTS[name](results)
    fig.set_layout_engine("tight")
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, facecolor="white")
    return buf.getvalue()
