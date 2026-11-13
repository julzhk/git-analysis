# /// script
# requires-python = ">=3.10"
# dependencies = ["radon>=6", "jinja2>=3.1"]
# ///
"""Analyse a git repository's Python code quality: complexity, change rate, churn, risk and logical coupling.

    uv run analyse.py [TARGET] [--branch B] [--exclude-dir D ...] [--exclude-file F ...]
                      [--max-changeset N] [--working-tree] [--out DIR]

TARGET is a local repository (default: the current directory) or a remote URL (https://, ssh://, git@host:org/repo).
Writes results.json and report.html to --out, and prints a Markdown summary to stdout. Progress goes to stderr.
"""
import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from gitquality import analysis, report  # noqa: E402

REMOTE_URL = re.compile(r"^(https://[^\s]+|ssh://[^\s]+|[\w.-]+@[\w.-]+:[^\s]+)$")
BRANCH_NAME = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)[\w./-]+(?<![./])$")


def log(message: str):
    print(message, file=sys.stderr, flush=True)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Analyse a git repository's Python code quality.")
    parser.add_argument("target", nargs="?", default=".", help="local repo path or remote URL (default: .)")
    parser.add_argument("--branch", help="branch to analyse (default: remote default branch / local HEAD)")
    parser.add_argument("--exclude-dir", action="append", dest="exclude_dirs", metavar="DIR",
                        help=f"directory name to skip, repeatable (default: {', '.join(analysis.DEFAULT_EXCLUDE_DIRS)})")
    parser.add_argument("--exclude-file", action="append", dest="exclude_files", metavar="FILE",
                        help=f"file name to skip, repeatable (default: {', '.join(analysis.DEFAULT_EXCLUDE_FILES)})")
    parser.add_argument("--max-changeset", type=int, default=analysis.DEFAULT_MAX_CHANGESET,
                        help="ignore commits touching more files than this for coupling (default: %(default)s)")
    parser.add_argument("--working-tree", action="store_true",
                        help="local repos only: measure the checked-out files in place, including uncommitted edits")
    parser.add_argument("--out", type=Path, help="output directory (default: a new temporary directory)")
    args = parser.parse_args(argv)
    if args.branch and not BRANCH_NAME.match(args.branch):
        parser.error(f"invalid branch name: {args.branch!r}")
    if args.max_changeset < 2:
        parser.error("--max-changeset must be at least 2")
    return args


def resolve_target(target: str) -> tuple[str, bool]:
    """(url or absolute path, is_remote). Rejects option-like and non-https/ssh URLs (ext::, git://, file://…)."""
    if target.startswith("-"):
        raise ValueError(f"not a repository: {target!r}")
    if REMOTE_URL.match(target):
        return target, True
    if "://" in target or "::" in target:
        raise ValueError(f"unsupported URL scheme (use https:// or ssh://): {target!r}")
    path = Path(target).expanduser().resolve()
    if not (path / ".git").exists():
        raise ValueError(f"not a git repository: {path}")
    return str(path), False


def current_branch(repo: str) -> str | None:
    branch = analysis.run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=Path(repo)).strip()
    return None if branch == "HEAD" else branch  # detached HEAD


def run(args) -> int:
    try:
        source, remote = resolve_target(args.target)
    except ValueError as error:
        log(f"error: {error}")
        return 2
    if args.working_tree and (remote or args.branch):
        log("error: --working-tree only works on a local repo's checked-out branch (drop --branch)")
        return 2

    name = report.repo_name(source)
    with tempfile.TemporaryDirectory(prefix="git-quality-") as tmp:
        if args.working_tree:
            branch, repo_dir = current_branch(source) or "HEAD", Path(source)
        else:
            if remote:
                log(f"Finding branches of {report.display_url(source)}")
                branches, default = analysis.list_branches(source)
                branch = args.branch or default or (branches[0] if branches else None)
                if not branch or branch not in branches:
                    log(f"error: branch {branch!r} not found (available: {', '.join(branches[:20]) or 'none'})")
                    return 2
            else:
                branch = args.branch or current_branch(source)
                if not branch:
                    log("error: detached HEAD; pass --branch or --working-tree")
                    return 2
            log(f"Cloning {report.display_url(source)} ({branch})")
            repo_dir = analysis.clone(source, branch, Path(tmp) / name)

        results = analysis.analyse_repository(
            repo_dir,
            exclude_dirs=args.exclude_dirs or analysis.DEFAULT_EXCLUDE_DIRS,
            exclude_files=args.exclude_files or analysis.DEFAULT_EXCLUDE_FILES,
            max_changeset=args.max_changeset,
            progress=lambda stage, message: log(message),
        )

    meta = {"repo": name, "repo_url": source, "branch": branch}
    out = args.out or Path(tempfile.mkdtemp(prefix=f"git-quality-{name}-"))
    out.mkdir(parents=True, exist_ok=True)
    (out / "results.json").write_text(json.dumps({"meta": meta | {"repo_url": report.display_url(source)},
                                                  **results}, indent=1))
    (out / "report.html").write_text(report.render_html(results, meta))

    print(report.markdown_summary(results, meta))
    print(f"Full results: {out / 'results.json'}")
    print(f"HTML report:  {out / 'report.html'}")
    return 0


def main(argv=None) -> int:
    args = parse_args(argv)
    try:
        return run(args)
    except analysis.GitError as error:
        log(f"git error: {error}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
