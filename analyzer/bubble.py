"""Geometry for the interactive scatter charts (complexity vs change rate, churn vs LOC), rendered as inline SVG."""
import math
from collections import Counter

from .charts import GREY, RANK_COLOUR

WIDTH, HEIGHT = 1000, 470
LEFT, RIGHT, TOP, BOTTOM = 64, 24, 16, 48
LABELLED = 12   # top-N files get a name label
CHAR_WIDTH, LABEL_HEIGHT = 6.7, 12   # approx. 11px monospace label metrics
LOG_TICKS = [0, 0.1, 0.25, 0.5] + [m * 10 ** k for k in range(7) for m in (1, 2, 5)]
MIN_TICK_GAP = {"x": 36, "y": 22}   # px between tick labels on a log axis
SCALES = [("log", "Log"), ("linear", "Linear")]


def nice_ticks(maximum: float, target: int = 6) -> list[float]:
    """0..≥maximum in round steps (1, 2, 2.5, 5 × 10^k)."""
    if maximum <= 0:
        return [0, 1]
    raw = maximum / target
    magnitude = 10 ** math.floor(math.log10(raw))
    step = next(m * magnitude for m in (1, 2, 2.5, 5, 10) if m * magnitude >= raw)
    count = math.ceil(maximum / step - 1e-9)
    return [round(i * step, 10) for i in range(count + 1)]


def log_ticks(maximum: float, length: float, min_gap: float, minimum: float = 0, integer: bool = False) -> list[float]:
    """From the last tick ≤ minimum (0, 0.1 … 1, 2, 5, 10 …) to the first ≥ maximum, thinned so labels don't collide.

    Integer quantities (lines, churn) skip the fractional ticks.
    """
    candidates = [t for t in LOG_TICKS if not integer or t == 0 or t >= 1]
    start = max(t for t in candidates if t <= max(minimum, 0))
    ticks = [t for t in candidates if start <= t < maximum] + [next((t for t in candidates if t >= maximum), maximum)]
    span = math.log1p(ticks[-1]) - math.log1p(start)
    kept = [ticks[0]]
    for t in ticks[1:]:
        if (math.log1p(t) - math.log1p(kept[-1])) / span * length >= min_gap:
            kept.append(t)
        elif t == ticks[-1]:
            kept[-1] = t  # always keep the axis end
    return kept


class Axis:
    def __init__(self, values: list[float], log: bool, start: float, length: float, flip: bool, min_gap: float,
                 minimum_max: float = 1, integer: bool = False):
        self.transform = math.log1p if log else (lambda v: v)
        maximum = max(max(values, default=1), minimum_max)
        if log:
            self.ticks = log_ticks(maximum, length, min_gap, min(values, default=0), integer)
        else:
            self.ticks = nice_ticks(maximum)
        self.start, self.length, self.flip = start, length, flip
        self.low = self.transform(self.ticks[0])
        self.span = (self.transform(self.ticks[-1]) - self.low) or 1

    def __call__(self, value: float) -> float:
        offset = (self.transform(value) - self.low) / self.span * self.length
        return self.start + self.length - offset if self.flip else self.start + offset


def _fmt(value: float) -> str:
    return f"{value:,.0f}" if value >= 1000 else f"{value:g}"


def _label(path: str, duplicate_names: set[str]) -> str:
    """File name, plus its parent directory when another file shares the name (e.g. two utils.py)."""
    parts = path.split("/")
    return "/".join(parts[-2:]) if parts[-1] in duplicate_names else parts[-1]


def _place_labels(candidates: list[dict]):
    """Greedy label placement: try four spots around each bubble, skip the label if all collide."""
    taken = []  # (x0, y0, x1, y1)
    for p in candidates:
        width = len(p["label"]) * CHAR_WIDTH
        for left, above in ((False, True), (False, False), (True, True), (True, False)):
            x0 = p["x"] - p["r"] - 3 - width if left else p["x"] + p["r"] + 3
            y1 = p["y"] - 2 if above else p["y"] + LABEL_HEIGHT + 2
            box = (x0, y1 - LABEL_HEIGHT, x0 + width, y1)
            inside = LEFT <= box[0] and box[2] <= WIDTH - RIGHT and TOP <= box[1] and box[3] <= HEIGHT - BOTTOM
            if inside and not any(box[0] < t[2] and t[0] < box[2] and box[1] < t[3] and t[1] < box[3] for t in taken):
                taken.append(box)
                p["label_x"], p["label_y"] = round(x0, 1), round(y1 - 2, 1)
                break
        else:
            p["label"] = None


def scatter(files, *, x_key, y_key, x_log, y_log, label_key, radius, y_min_max=1, integer=False, thresholds=()):
    """Shared layout: axes, ticks, one point per file, labels for the top LABELLED files by `label_key`."""
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM
    sx = Axis([f[x_key] for f in files], x_log, LEFT, plot_w, False, MIN_TICK_GAP["x"], integer=integer)
    sy = Axis([f[y_key] for f in files], y_log, TOP, plot_h, True, MIN_TICK_GAP["y"], y_min_max, integer)

    ranked = sorted((f for f in files if f[label_key]), key=lambda f: f[label_key], reverse=True)
    rank_of = {f["file"]: i for i, f in enumerate(ranked[:LABELLED])}
    name_counts = Counter(f["file"].rsplit("/", 1)[-1] for f in files)
    duplicate_names = {name for name, count in name_counts.items() if count > 1}

    points = [{
        "file": f,
        "x": round(sx(f[x_key]), 1),
        "y": round(sy(f[y_key]), 1),
        "r": round(radius(f), 1),
        "colour": RANK_COLOUR.get(f["cc_rank"], GREY),
        "label": _label(f["file"], duplicate_names) if f["file"] in rank_of else None,
    } for f in files]
    _place_labels(sorted((p for p in points if p["label"]), key=lambda p: rank_of[p["file"]["file"]]))
    points.sort(key=lambda p: -p["r"])  # big bubbles underneath, so small ones stay hoverable

    return {
        "width": WIDTH,
        "height": HEIGHT,
        "x_log": x_log,
        "y_log": y_log,
        "plot": {"left": LEFT, "right": WIDTH - RIGHT, "top": TOP, "bottom": TOP + plot_h,
                 "cx": LEFT + plot_w / 2, "cy": TOP + plot_h / 2},
        "x_ticks": [{"x": round(sx(t), 1), "label": _fmt(t)} for t in sx.ticks],
        "y_ticks": [{"y": round(sy(t), 1), "label": _fmt(t)} for t in sy.ticks],
        "thresholds": [{"y": round(sy(v), 1), "value": v, "colour": c}
                       for v, c in thresholds if sy.ticks[0] <= v <= sy.ticks[-1]],
        "points": points,
        "labelled_count": sum(1 for p in points if p["label"]),
        "legend": list(RANK_COLOUR.items()),
        "scales": SCALES,
    }


def bubble_chart(files: list[dict], scale: str = "log") -> dict:
    """Avg CC (linear) vs commits/month (log or linear); bubble area ∝ LOC, labels on the riskiest files."""
    log = scale != "linear"
    chart = scatter(
        [f for f in files if f["avg_cc"] is not None],
        x_key="change_rate", y_key="avg_cc", x_log=log, y_log=False, label_key="risk_score", y_min_max=6,
        radius=lambda f: math.sqrt(min(max(f["loc"] * 1.5, 20), 800) / math.pi),
        thresholds=((5, "#f39c12"), (10, "#e74c3c")),
    )
    return chart | {
        "id": "bubble",
        "scale": "log" if log else "linear",
        "title": "Complexity vs rate of change",
        "description": "Bubble size = lines of code. The highest-risk files are labelled; "
                       "top-right is complex <em>and</em> frequently changed.",
        "x_label": "Commits per month (change rate)",
        "y_label": "Average cyclomatic complexity",
        "aria_label": "Scatter of average cyclomatic complexity against commits per month, one bubble per file",
        "threshold_prefix": "CC",
    }


def churn_chart(files: list[dict], scale: str = "log") -> dict:
    """Churn vs LOC, both axes log or linear; labels on the most-churned files."""
    log = scale != "linear"
    chart = scatter(files, x_key="loc", y_key="churn", x_log=log, y_log=log, label_key="churn",
                    radius=lambda f: 5.5, integer=True)
    return chart | {
        "id": "churn",
        "scale": "log" if log else "linear",
        "title": "Churn vs lines of code",
        "description": "Total lines added + deleted over the file's history, coloured by CC rank. "
                       "The most-churned files are labelled; files high above the others churn a lot for their size.",
        "x_label": "Lines of code (non-blank, non-comment)",
        "y_label": "Total churn (lines added + deleted)",
        "aria_label": "Scatter of total churn against lines of code, one dot per file",
        "threshold_prefix": "",
    }


CHARTS = {"bubble": bubble_chart, "churn": churn_chart}
