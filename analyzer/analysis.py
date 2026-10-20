"""
Git repository code-quality analysis.

Ported from notebooks/git_code_quality.ipynb: per-file cyclomatic complexity and
maintainability (radon), rate of change and churn from git history, a composite
risk score, and logical coupling between files that change together.

Everything here is plain Python with no Django dependency so it can be reused
from the notebook, a management command or the web UI.
"""
import datetime
import math
import os
import subprocess
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from radon.complexity import cc_rank, cc_visit
from radon.metrics import mi_visit

DEFAULT_EXCLUDE_DIRS = ["migrations", "__pycache__", ".git", "venv", ".venv", "node_modules"]
DEFAULT_EXCLUDE_FILES = ["__init__.py"]
DEFAULT_MAX_CHANGESET = 100   # commits touching more files than this are ignored for coupling
HEATMAP_SIZE = 25             # files shown in the coupling heatmap
MAX_STORED_PAIRS = 2000       # coupled pairs kept in the results

COMMIT_MARKER = "@@commit@@"


class GitError(Exception):
    pass


# ── git plumbing ───────────────────────────────────────────────────────────────

def _git_env() -> dict:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"                  # never block waiting for credentials
    env["GIT_ALLOW_PROTOCOL"] = "https:ssh:file"      # no ext::, git:// etc.
    env.setdefault("GIT_SSH_COMMAND", "ssh -o BatchMode=yes")
    return env


def run_git(args: list[str], cwd: Path | None = None, timeout: int = 60) -> str:
    try:
        result = subprocess.run(
            ["git", "-c", "core.quotePath=false", *args],
            cwd=cwd, env=_git_env(), capture_output=True, text=True,
            errors="replace", timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise GitError(f"git {args[0]} timed out after {timeout}s")
    if result.returncode != 0:
        lines = [l for l in result.stderr.strip().splitlines() if l.strip()]
        raise GitError(lines[-1] if lines else f"git {args[0]} failed")
    return result.stdout


def list_branches(repo_url: str, timeout: int = 30) -> tuple[list[str], str | None]:
    """Return (branch names, default branch) for a remote without cloning it."""
    out = run_git(["ls-remote", "--symref", "--", repo_url, "HEAD", "refs/heads/*"], timeout=timeout)
    branches, default = [], None
    for line in out.splitlines():
        ref_part, _, name = line.partition("\t")
        if ref_part.startswith("ref: ") and name == "HEAD":
            default = ref_part.removeprefix("ref: refs/heads/")
        elif name.startswith("refs/heads/"):
            branches.append(name.removeprefix("refs/heads/"))
    branches.sort(key=lambda b: (b != default, b.lower()))
    return branches, default


def clone(repo_url: str, branch: str, dest: Path, timeout: int = 900) -> Path:
    run_git(["clone", "--quiet", "--single-branch", "--branch", branch, "--", repo_url, str(dest)],
            timeout=timeout)
    return dest


def read_history(repo_dir: Path, timeout: int = 900) -> list[dict]:
    """All commits on HEAD with per-file line stats: [{sha, date, files: {path: churn}}]."""
    out = run_git(
        ["log", "--no-renames", "--numstat", f"--format={COMMIT_MARKER}%H %ct"],
        cwd=repo_dir, timeout=timeout,
    )
    commits = []
    for line in out.splitlines():
        if line.startswith(COMMIT_MARKER):
            sha, ts = line.removeprefix(COMMIT_MARKER).split()
            commits.append({
                "sha": sha,
                "date": datetime.datetime.fromtimestamp(int(ts), tz=datetime.timezone.utc),
                "files": {},
            })
        elif line and commits:
            ins, dels, path = line.split("\t", 2)
            # binary files report "-" for both counts
            churn = (int(ins) if ins.isdigit() else 0) + (int(dels) if dels.isdigit() else 0)
            commits[-1]["files"][path] = churn
    return commits


# ── metrics ────────────────────────────────────────────────────────────────────

def make_exclusion_filter(exclude_dirs, exclude_files):
    exclude_dirs, exclude_files = set(exclude_dirs), set(exclude_files)

    def is_excluded(filepath: str) -> bool:
        parts = filepath.split("/")
        return bool(set(parts) & exclude_dirs) or parts[-1] in exclude_files

    return is_excluded


def analyse_source(source: str) -> dict:
    """Avg/max cyclomatic complexity, CC rank, maintainability index and LOC for Python source."""
    try:
        blocks = cc_visit(source)
        if blocks:
            complexities = [b.complexity for b in blocks]
            avg_cc = sum(complexities) / len(complexities)
            max_cc = max(complexities)
            rank = cc_rank(max_cc)
        else:
            avg_cc, max_cc, rank = 1.0, 1, "A"
    except Exception:
        avg_cc, max_cc, rank = None, None, None

    try:
        mi = mi_visit(source, multi=True)
    except Exception:
        mi = None

    loc = len([l for l in source.splitlines() if l.strip() and not l.strip().startswith("#")])
    return {"avg_cc": avg_cc, "max_cc": max_cc, "cc_rank": rank, "mi": mi, "loc": loc}


def change_rate(dates: list[datetime.datetime]) -> tuple[float, int]:
    """(commits per month over the file's active lifespan, lifespan in days)."""
    if len(dates) < 2:
        return 0.0, 0
    age_days = max((max(dates) - min(dates)).days, 1)
    return round(len(dates) / age_days * 30, 3), age_days


def risk_score(avg_cc: float | None, rate: float) -> float | None:
    if avg_cc is None:
        return None
    return round(avg_cc * math.log1p(rate), 3)


def _round(value, ndigits=2):
    return None if value is None else round(value, ndigits)


def analyse_repository(
    repo_dir: Path,
    exclude_dirs=DEFAULT_EXCLUDE_DIRS,
    exclude_files=DEFAULT_EXCLUDE_FILES,
    max_changeset: int = DEFAULT_MAX_CHANGESET,
    progress=lambda stage, message: None,
) -> dict:
    repo_dir = Path(repo_dir)
    is_excluded = make_exclusion_filter(exclude_dirs, exclude_files)
    is_relevant = lambda path: path.endswith(".py") and not is_excluded(path)

    # ── git history per file ──
    progress("history", "Reading git history")
    commits = read_history(repo_dir)
    file_dates: dict[str, list] = defaultdict(list)
    file_churn: dict[str, int] = defaultdict(int)
    file_commit_sets: dict[str, set] = defaultdict(set)
    for commit in commits:
        for path, churn in commit["files"].items():
            if is_relevant(path):
                file_dates[path].append(commit["date"])
                file_churn[path] += churn
                file_commit_sets[path].add(commit["sha"])

    # ── complexity per file in the working tree ──
    py_files = [p for p in repo_dir.rglob("*.py")
                if p.is_file() and not is_excluded(p.relative_to(repo_dir).as_posix())]
    rows = []
    for i, py_file in enumerate(py_files, 1):
        if i % 25 == 0 or i == len(py_files):
            progress("metrics", f"Measuring complexity ({i}/{len(py_files)} files)")
        rel = py_file.relative_to(repo_dir).as_posix()
        try:
            metrics = analyse_source(py_file.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        dates = file_dates.get(rel, [])
        rate, age_days = change_rate(dates)
        rows.append({
            "file": rel,
            "module": "/".join(rel.split("/")[:-1]) or "root",
            "loc": metrics["loc"],
            "avg_cc": _round(metrics["avg_cc"]),
            "max_cc": metrics["max_cc"],
            "cc_rank": metrics["cc_rank"],
            "mi": _round(metrics["mi"]),
            "n_commits": len(dates),
            "churn": file_churn.get(rel, 0),
            "change_rate": rate,
            "first_seen": min(dates).isoformat() if dates else None,
            "last_seen": max(dates).isoformat() if dates else None,
            "age_days": age_days,
            "risk_score": risk_score(metrics["avg_cc"], rate),
        })

    # ── logical coupling ──
    progress("coupling", "Analysing logical coupling")
    pair_count: dict[tuple, int] = defaultdict(int)
    skipped_commits = 0
    for commit in commits:
        changed = sorted(p for p in commit["files"] if is_relevant(p))
        if len(changed) < 2:
            continue
        if len(changed) > max_changeset:
            skipped_commits += 1
            continue
        for a, b in combinations(changed, 2):
            pair_count[(a, b)] += 1

    degree: dict[str, int] = defaultdict(int)
    for a, b in pair_count:
        degree[a] += 1
        degree[b] += 1

    pairs = []
    for (a, b), count in sorted(pair_count.items(), key=lambda kv: kv[1], reverse=True)[:MAX_STORED_PAIRS]:
        union = len(file_commit_sets[a] | file_commit_sets[b])
        pairs.append({
            "file_a": a,
            "file_b": b,
            "co_commits": count,
            "commits_a": len(file_commit_sets[a]),
            "commits_b": len(file_commit_sets[b]),
            "coupling_strength": round(count / union, 3) if union else 0.0,
        })

    top_files = [f for f, _ in sorted(degree.items(), key=lambda kv: kv[1], reverse=True)[:HEATMAP_SIZE]]
    idx = {f: i for i, f in enumerate(top_files)}
    matrix = [[0] * len(top_files) for _ in top_files]
    for (a, b), count in pair_count.items():
        if a in idx and b in idx:
            matrix[idx[a]][idx[b]] = matrix[idx[b]][idx[a]] = count

    for row in rows:
        row["coupling_degree"] = degree.get(row["file"], 0)
    rows.sort(key=lambda r: (r["risk_score"] is None, -(r["risk_score"] or 0)))

    return {
        "head_sha": commits[0]["sha"] if commits else None,
        "total_commits": len(commits),
        "tracked_files": len(file_dates),
        "files": rows,
        "pairs": pairs,
        "pair_total": len(pair_count),
        "skipped_commits": skipped_commits,
        "max_changeset": max_changeset,
        "degree": sorted(({"file": f, "coupling_degree": d} for f, d in degree.items()),
                         key=lambda r: r["coupling_degree"], reverse=True)[:200],
        "heatmap": {"files": top_files, "matrix": matrix},
    }
