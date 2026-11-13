"""Turn analysis results into a compact Markdown summary (for Claude) and a self-contained HTML report (for people)."""
import datetime
import re
from collections import Counter
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import svg
from .links import RepoLinks

TEMPLATES = Path(__file__).resolve().parent.parent.parent / "templates"
SUMMARY_ROWS = 10
TABLE_ROWS = 30


def display_url(repo_url: str) -> str:
    """The repo URL with any embedded credentials (e.g. a personal access token) masked."""
    return re.sub(r"//[^/@]+@", "//***@", repo_url)


def repo_name(repo_url: str) -> str:
    return repo_url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1].removesuffix(".git") or repo_url


def kpis(results: dict) -> dict:
    files = results["files"]
    with_cc = [f["avg_cc"] for f in files if f["avg_cc"] is not None]
    with_mi = [f["mi"] for f in files if f["mi"] is not None]
    return {
        "files": len(files),
        "commits": results["total_commits"],
        "loc": sum(f["loc"] for f in files),
        "mean_cc": sum(with_cc) / len(with_cc) if with_cc else None,
        "maintainable_pct": 100 * sum(mi >= 65 for mi in with_mi) / len(with_mi) if with_mi else None,
        "complex_files": sum(f["cc_rank"] in ("D", "E", "F") for f in files),
    }


def rank_counts(results: dict) -> list[tuple[str, int, str]]:
    counts = Counter(f["cc_rank"] for f in results["files"] if f["cc_rank"] in svg.RANK_COLOUR)
    return [(rank, counts[rank], colour) for rank, colour in svg.RANK_COLOUR.items() if counts[rank]]


def _num(value, digits=2):
    return "—" if value is None else f"{value:,.{digits}f}"


# ── Markdown summary (printed to stdout, read by Claude) ──────────────────────

def markdown_summary(results: dict, meta: dict) -> str:
    k = kpis(results)
    lines = [
        f"# Code quality: {meta['repo']} @ {meta['branch']} ({(results['head_sha'] or '')[:10]})",
        "",
        f"- Python files: {k['files']} · LOC: {k['loc']:,} · commits: {k['commits']:,}",
        f"- Mean avg CC: {_num(k['mean_cc'])} · maintainable (MI ≥ 65): {_num(k['maintainable_pct'], 0)}%"
        f" · rank D–F files: {k['complex_files']}",
        "- Rank distribution: " + (", ".join(f"{r} {n}" for r, n, _ in rank_counts(results)) or "—"),
        f"- Coupled pairs: {results['pair_total']:,} · commits skipped for coupling "
        f"(> {results['max_changeset']} files): {results['skipped_commits']}",
        "",
        f"## Top {SUMMARY_ROWS} hotspots (risk = avg CC × ln(1 + commits/month))",
        "",
        "| file | LOC | avg CC | max CC | rank | MI | commits | /month | churn | coupled | risk |",
        "|---|---:|---:|---:|:-:|---:|---:|---:|---:|---:|---:|",
    ]
    hotspots = [f for f in results["files"] if f["risk_score"]][:SUMMARY_ROWS]
    if not hotspots:
        lines.append("| _none: no file has both measurable complexity and a change rate above 0 "
                     "(too little history?)_ |||||||||||")
    for f in hotspots:
        lines.append(f"| {f['file']} | {f['loc']} | {_num(f['avg_cc'])} | {f['max_cc']} | {f['cc_rank']} "
                     f"| {_num(f['mi'], 1)} | {f['n_commits']} | {_num(f['change_rate'])} | {f['churn']} "
                     f"| {f['coupling_degree']} | {_num(f['risk_score'])} |")
    lines += ["", "## Most complex files (max CC)", "", "| file | max CC | rank | avg CC | LOC |", "|---|---:|:-:|---:|---:|"]
    for f in sorted((f for f in results["files"] if f["max_cc"]), key=lambda f: -f["max_cc"])[:5]:
        lines.append(f"| {f['file']} | {f['max_cc']} | {f['cc_rank']} | {_num(f['avg_cc'])} | {f['loc']} |")
    lines += ["", f"## Top {SUMMARY_ROWS} coupled pairs", "",
              "| file A | file B | co-commits | strength |", "|---|---|---:|---:|"]
    for p in results["pairs"][:SUMMARY_ROWS]:
        lines.append(f"| {p['file_a']} | {p['file_b']} | {p['co_commits']} | {p['coupling_strength']:.2f} |")
    if not results["files"]:
        lines += ["", "_No Python files found (after exclusions)._"]
    return "\n".join(lines) + "\n"


# ── HTML report ────────────────────────────────────────────────────────────────

def render_html(results: dict, meta: dict) -> str:
    links = RepoLinks(meta["repo_url"], results["head_sha"], meta.get("custom_hosts"))
    current = {f["file"] for f in results["files"]}
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=select_autoescape(["html", "j2"]),
                      trim_blocks=True, lstrip_blocks=True)
    env.filters["num"] = _num
    env.globals["file_url"] = lambda path: links.file(path) if path in current else None
    files = results["files"]
    return env.get_template("report.html.j2").render(
        results=results,
        meta=meta | {"repo_url": display_url(meta["repo_url"])},
        commit_url=links.commit(),
        generated=datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        kpis=kpis(results),
        ranks=rank_counts(results),
        scatters=[{scale: build(files, scale) for scale, _ in svg.SCALES}
                  for build in (svg.bubble_chart, svg.churn_chart)],
        bars=[svg.top_cc_chart(files), svg.top_rate_chart(files)],
        hotspots=[f for f in files if f["risk_score"]][:TABLE_ROWS],
        pairs=results["pairs"][:TABLE_ROWS],
        scales=svg.SCALES,
        legend=list(svg.RANK_COLOUR.items()),
        rank_colour=svg.RANK_COLOUR,
    )
