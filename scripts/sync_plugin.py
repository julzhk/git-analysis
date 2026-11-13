"""Copy the framework-free analysis modules from the Django app into the Claude Code plugin.

Run after changing analyzer/analysis.py, bubble.py or links.py:  python scripts/sync_plugin.py
(analyzer.tests.PluginTests fails while the copies are stale.)
"""
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "plugins/git-code-quality/skills/git-code-quality/scripts/gitquality"
SHARED = {  # app module -> plugin module
    "analyzer/analysis.py": "analysis.py",
    "analyzer/bubble.py": "svg.py",
    "analyzer/links.py": "links.py",
}


def main():
    for source, target in SHARED.items():
        shutil.copyfile(ROOT / source, PACKAGE / target)
        print(f"{source} -> {(PACKAGE / target).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
