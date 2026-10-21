import math
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from django.urls import reverse

from . import analysis as git_analysis
from .models import Analysis

COMPLEX_SOURCE = """
def classify(x, y):
    if x > 0 and y > 0:
        return "both"
    elif x > 0 or y > 0:
        for i in range(x):
            if i % 2:
                return "odd"
        return "one"
    try:
        return "none" if x == 0 else "neg"
    except ValueError:
        return "err"
"""


def make_repo() -> Path:
    """A small repo: app/core.py and app/utils.py change together twice; migrations are excluded."""
    root = Path(tempfile.mkdtemp(prefix="git-analysis-test-"))

    def git(*args, date="2024-01-01T12:00:00"):
        env = {**os.environ, "GIT_AUTHOR_DATE": date, "GIT_COMMITTER_DATE": date}
        subprocess.run(["git", "-c", "user.name=Test", "-c", "user.email=t@example.com", *args],
                       cwd=root, check=True, capture_output=True, env=env)

    git("init", "--initial-branch=main")
    (root / "app" / "migrations").mkdir(parents=True)
    (root / "app" / "__init__.py").write_text("")
    (root / "app" / "core.py").write_text(COMPLEX_SOURCE)
    (root / "app" / "utils.py").write_text("def add(a, b):\n    return a + b\n")
    (root / "app" / "migrations" / "0001.py").write_text("x = 1\n")
    git("add", "-A")
    git("commit", "-m", "initial", date="2024-01-01T12:00:00")

    (root / "app" / "core.py").write_text(COMPLEX_SOURCE + "\n# tweak\n")
    (root / "app" / "utils.py").write_text("def add(a, b):\n    return b + a\n")
    git("commit", "-am", "change both", date="2024-01-31T12:00:00")

    (root / "app" / "core.py").write_text(COMPLEX_SOURCE + "\n# tweak 2\n")
    git("commit", "-am", "change core", date="2024-03-01T12:00:00")
    git("branch", "feature")
    return root


class RepoTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.repo = make_repo()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.repo, ignore_errors=True)
        super().tearDownClass()


class AnalysisServiceTests(RepoTestCase):
    def test_list_branches(self):
        branches, default = git_analysis.list_branches(str(self.repo))
        self.assertEqual(default, "main")
        self.assertEqual(branches, ["main", "feature"])

    def test_analyse_repository(self):
        stages = []
        results = git_analysis.analyse_repository(self.repo, progress=lambda stage, msg: stages.append(stage))
        files = {f["file"]: f for f in results["files"]}

        self.assertEqual(set(files), {"app/core.py", "app/utils.py"})  # __init__ and migrations excluded
        self.assertEqual(results["total_commits"], 3)
        self.assertEqual(stages[0], "history")
        self.assertIn("coupling", stages)

        core = files["app/core.py"]
        self.assertEqual(core["n_commits"], 3)
        self.assertEqual(core["max_cc"], 9)
        self.assertEqual(core["cc_rank"], "B")
        self.assertEqual(core["age_days"], 60)
        self.assertEqual(core["change_rate"], 1.5)  # 3 commits / 60 days * 30
        self.assertGreater(core["risk_score"], files["app/utils.py"]["risk_score"])
        self.assertEqual(results["files"][0]["file"], "app/core.py")  # sorted by risk

        self.assertEqual(results["pairs"], [{
            "file_a": "app/core.py", "file_b": "app/utils.py", "co_commits": 2,
            "commits_a": 3, "commits_b": 2, "coupling_strength": 0.667,
        }])
        self.assertEqual(core["coupling_degree"], 1)
        self.assertEqual(results["heatmap"]["matrix"], [[0, 2], [2, 0]])

    def test_max_changeset_skips_large_commits(self):
        results = git_analysis.analyse_repository(self.repo, max_changeset=1)
        self.assertEqual(results["pairs"], [])
        self.assertEqual(results["skipped_commits"], 2)

    def test_unreachable_repo_raises_git_error(self):
        with self.assertRaises(git_analysis.GitError):
            git_analysis.list_branches(str(self.repo / "missing"))


@override_settings(GIT_ANALYSIS_ALLOW_LOCAL=True, GIT_ANALYSIS_RUN_SYNC=True)
class WizardViewTests(RepoTestCase):
    def test_index(self):
        response = self.client.get(reverse("index"))
        self.assertContains(response, "Analyse a git repository")
        self.assertContains(response, 'hx-post="/analyses/inspect/"')

    def test_inspect_lists_branches(self):
        response = self.client.post(reverse("inspect_repo"), {"repo_url": str(self.repo)}, HTTP_HX_REQUEST="true")
        self.assertContains(response, '<option value="main" selected>main (default)</option>', html=True)
        self.assertContains(response, 'value="feature"')

    def test_inspect_rejects_bad_urls(self):
        for url, message in [
            ("-uhoh", "doesn&#x27;t look like a repository URL"),
            ("http://example.com/repo.git", "Enter an https:// URL"),
            (str(self.repo / "missing"), "No such directory"),
        ]:
            response = self.client.post(reverse("inspect_repo"), {"repo_url": url})
            self.assertContains(response, message)

    @override_settings(GIT_ANALYSIS_ALLOW_LOCAL=False, GIT_ANALYSIS_ALLOW_SSH=False)
    def test_local_and_ssh_disabled_by_setting(self):
        response = self.client.post(reverse("inspect_repo"), {"repo_url": str(self.repo)})
        self.assertContains(response, "Local paths are disabled")
        response = self.client.post(reverse("inspect_repo"), {"repo_url": "git@github.com:org/repo.git"})
        self.assertContains(response, "SSH URLs are disabled")

    def test_create_runs_analysis_and_redirects(self):
        response = self.client.post(reverse("create_analysis"), {
            "repo_url": str(self.repo), "branch": "main",
            "exclude_dirs": "migrations, .git", "exclude_files": "__init__.py", "max_changeset": 100,
        }, HTTP_HX_REQUEST="true")
        analysis = Analysis.objects.get()
        self.assertEqual(response["HX-Redirect"], analysis.get_absolute_url())
        self.assertEqual(analysis.status, Analysis.Status.DONE, analysis.error)
        self.assertEqual(analysis.exclude_dirs, ["migrations", ".git"])
        self.assertEqual(len(analysis.results["files"]), 2)

    def test_create_with_invalid_options_rerenders_step(self):
        response = self.client.post(reverse("create_analysis"), {
            "repo_url": str(self.repo), "branch": "--evil", "max_changeset": 1, "branches": ["main"],
        })
        self.assertContains(response, "Invalid branch name")
        self.assertContains(response, 'value="main"')
        self.assertFalse(Analysis.objects.exists())

    def test_failed_analysis_shows_error(self):
        analysis = Analysis.objects.create(repo_url=str(self.repo), branch="does-not-exist")
        from . import runner
        with self.assertLogs("analyzer.runner", "ERROR"):
            runner.run(analysis.pk)
        response = self.client.get(analysis.get_absolute_url())
        self.assertContains(response, "The analysis failed")
        self.assertContains(response, "does-not-exist")


@override_settings(GIT_ANALYSIS_ALLOW_LOCAL=True, GIT_ANALYSIS_RUN_SYNC=True)
class ResultsViewTests(RepoTestCase):
    def setUp(self):
        from . import runner
        self.analysis = Analysis.objects.create(
            repo_url=str(self.repo), branch="main",
            exclude_dirs=git_analysis.DEFAULT_EXCLUDE_DIRS, exclude_files=git_analysis.DEFAULT_EXCLUDE_FILES,
        )
        runner.run(self.analysis.pk)

    def test_progress_refreshes_when_finished(self):
        response = self.client.get(reverse("analysis_progress", args=[self.analysis.pk]))
        self.assertEqual(response["HX-Refresh"], "true")

    def test_progress_polls_while_running(self):
        Analysis.objects.filter(pk=self.analysis.pk).update(status="running", stage="metrics", message="Measuring")
        response = self.client.get(reverse("analysis_progress", args=[self.analysis.pk]))
        self.assertContains(response, 'hx-trigger="every 1s"')
        self.assertContains(response, "Measuring")

    def test_every_tab_renders_full_and_partial(self):
        for tab in ["overview", "files", "hotspots", "coupling", "guide"]:
            url = reverse("analysis_tab", args=[self.analysis.pk, tab])
            full = self.client.get(url)
            self.assertContains(full, "<html", msg_prefix=tab)
            partial = self.client.get(url, HTTP_HX_REQUEST="true", HTTP_HX_TARGET="results-body")
            self.assertEqual(partial.status_code, 200, tab)
            self.assertNotContains(partial, "<html", msg_prefix=tab)
            self.assertContains(partial, 'aria-current="page"', msg_prefix=tab)

    def test_unknown_tab_404s(self):
        self.assertEqual(self.client.get(reverse("analysis_tab", args=[self.analysis.pk, "nope"])).status_code, 404)

    def test_files_table_sort_and_filter(self):
        url = reverse("files_table", args=[self.analysis.pk])
        response = self.client.get(url, {"sort": "loc", "dir": "asc"})
        content = response.content.decode()
        self.assertLess(content.index("utils.py"), content.index("core.py"))
        response = self.client.get(url, {"q": "utils"})
        self.assertContains(response, "utils.py")
        self.assertNotContains(response, "core.py")

    def test_file_detail_shows_partners(self):
        response = self.client.get(reverse("file_detail", args=[self.analysis.pk]), {"path": "app/core.py"})
        self.assertContains(response, "app/utils.py")
        self.assertContains(response, "2×")

    def test_charts_render_png(self):
        for name in ["top_cc", "top_change_rate", "mi_hist", "rank_donut", "coupling_heatmap"]:
            response = self.client.get(reverse("chart", args=[self.analysis.pk, name]))
            self.assertEqual(response["Content-Type"], "image/png", name)
            self.assertTrue(response.content.startswith(b"\x89PNG"), name)

    def test_bubble_chart_svg(self):
        response = self.client.get(reverse("analysis_detail", args=[self.analysis.pk]))
        self.assertContains(response, 'data-path="app/core.py"')
        self.assertContains(response, ">core.py</text>")  # highest risk file is labelled
        self.assertContains(response, f'hx-get="/analyses/{self.analysis.pk}/files/detail/?path=app/core.py"')
        self.assertContains(response, "log scale")  # default
        response = self.client.get(reverse("scatter_chart", args=[self.analysis.pk, "bubble"]), {"scale": "linear"})
        self.assertNotContains(response, "log scale")
        self.assertContains(response, 'aria-pressed="true">Linear</button>')
        response = self.client.get(reverse("scatter_chart", args=[self.analysis.pk, "nope"]))
        self.assertEqual(response.status_code, 404)

    def test_churn_chart_svg(self):
        response = self.client.get(reverse("analysis_detail", args=[self.analysis.pk]))
        self.assertContains(response, 'id="churn-chart"')
        self.assertContains(response, "Lines of code (non-blank, non-comment) — log scale")
        self.assertContains(response, "Total churn (lines added + deleted) — log")
        url = reverse("scatter_chart", args=[self.analysis.pk, "churn"])
        response = self.client.get(url, {"scale": "linear"})
        self.assertNotContains(response, "log scale")
        self.assertContains(response, 'data-path="app/core.py"')
        self.assertContains(response, f'hx-get="{url}?scale=log" hx-target="#churn-chart"')

    def test_log_ticks_are_thinned_and_cover_the_maximum(self):
        from .bubble import log_ticks
        ticks = log_ticks(9606, 900, 36)
        self.assertEqual(ticks[0], 0)
        self.assertGreaterEqual(ticks[-1], 9606)
        self.assertIn(1000, ticks)
        positions = [math.log1p(t) / math.log1p(ticks[-1]) * 900 for t in ticks]
        self.assertTrue(all(b - a >= 36 for a, b in zip(positions, positions[1:])))
        # integer axes start at the tick just below the smallest value and skip fractions
        self.assertEqual(log_ticks(9606, 900, 36, minimum=12, integer=True)[0], 10)
        self.assertNotIn(0.5, log_ticks(50, 900, 36, integer=True))

    def test_bubble_labels_disambiguate_duplicate_names(self):
        from .bubble import bubble_chart
        files = [{"file": path, "avg_cc": cc, "change_rate": rate, "loc": 50, "cc_rank": "A", "risk_score": cc * rate}
                 for path, cc, rate in [("src/pkg/utils.py", 2, 1), ("tests/utils.py", 6, 8), ("src/pkg/app.py", 1, 0.1)]]
        labels = {p["file"]["file"]: p["label"] for p in bubble_chart(files)["points"]}
        self.assertEqual(labels, {"src/pkg/utils.py": "pkg/utils.py", "tests/utils.py": "tests/utils.py",
                                  "src/pkg/app.py": "app.py"})

    def test_bubble_labels_do_not_overlap(self):
        from .bubble import CHAR_WIDTH, LABEL_HEIGHT, bubble_chart
        files = [{"file": f"pkg/module_{i}.py", "avg_cc": 4.0, "change_rate": 1.0, "loc": 100, "cc_rank": "A",
                  "risk_score": 10 - i} for i in range(5)]  # identical positions
        chart = bubble_chart(files)
        labelled = [p for p in chart["points"] if p["label"]]
        self.assertTrue(1 <= len(labelled) < 5)
        boxes = [(p["label_x"], p["label_y"], p["label_x"] + len(p["label"]) * CHAR_WIDTH) for p in labelled]
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a[0] < b[2] and b[0] < a[2] and abs(a[1] - b[1]) < LABEL_HEIGHT)

    def test_csv_export(self):
        response = self.client.get(reverse("files_csv", args=[self.analysis.pk]))
        lines = response.content.decode().splitlines()
        self.assertTrue(lines[0].startswith("file,module,loc"))
        self.assertEqual(len(lines), 3)

    def test_rerun_and_delete(self):
        response = self.client.post(reverse("rerun_analysis", args=[self.analysis.pk]), HTTP_HX_REQUEST="true")
        self.assertEqual(Analysis.objects.count(), 2)
        self.assertIn("HX-Redirect", response)
        self.client.delete(reverse("delete_analysis", args=[self.analysis.pk]))
        self.assertEqual(Analysis.objects.count(), 1)


class RepoLinksTests(TestCase):
    SHA = "0123456789abcdef0123456789abcdef01234567"

    def test_hosts_and_url_forms(self):
        from .links import RepoLinks
        cases = [
            ("https://github.com/psf/requests.git", f"https://github.com/psf/requests/blob/{self.SHA}/src/a b.py"),
            ("https://TOKEN@github.com/org/repo", f"https://github.com/org/repo/blob/{self.SHA}/src/a b.py"),
            ("git@github.com:org/repo.git", f"https://github.com/org/repo/blob/{self.SHA}/src/a b.py"),
            ("https://gitlab.com/group/sub/repo.git", f"https://gitlab.com/group/sub/repo/-/blob/{self.SHA}/src/a b.py"),
            ("ssh://git@bitbucket.org/team/repo.git", f"https://bitbucket.org/team/repo/src/{self.SHA}/src/a b.py"),
        ]
        for repo_url, expected in cases:
            self.assertEqual(RepoLinks(repo_url, self.SHA).file("src/a b.py"), expected.replace(" ", "%20"), repo_url)

    def test_unknown_hosts_and_local_paths_have_no_links(self):
        from .links import RepoLinks
        for repo_url in ["https://git.example.com/org/repo.git", "/tmp/repo"]:
            links = RepoLinks(repo_url, self.SHA)
            self.assertFalse(links)
            self.assertIsNone(links.file("x.py"))
        self.assertFalse(RepoLinks("https://github.com/org/repo.git", None))

    @override_settings(GIT_ANALYSIS_REPO_HOSTS={"git.example.com": "gitlab"})
    def test_custom_host_mapping(self):
        from .links import RepoLinks
        links = RepoLinks("https://git.example.com/org/repo.git", self.SHA)
        self.assertEqual(links.commit(), f"https://git.example.com/org/repo/-/commit/{self.SHA}")

    def test_reports_link_existing_files_only(self):
        repo = make_repo()
        self.addCleanup(shutil.rmtree, repo, ignore_errors=True)
        results = git_analysis.analyse_repository(repo)
        results["pairs"].append({**results["pairs"][0], "file_b": "app/deleted.py"})
        analysis = Analysis.objects.create(repo_url="https://github.com/org/repo.git", branch="main",
                                           status=Analysis.Status.DONE, results=results)
        base = f"https://github.com/org/repo/blob/{results['head_sha']}/"
        for tab in ["files", "hotspots", "coupling"]:
            response = self.client.get(reverse("analysis_tab", args=[analysis.pk, tab]))
            self.assertContains(response, f'href="{base}app/core.py"', msg_prefix=tab)
            self.assertNotContains(response, f'{base}app/deleted.py', msg_prefix=tab)
        response = self.client.get(reverse("file_detail", args=[analysis.pk]), {"path": "app/core.py"})
        self.assertContains(response, "View source on GitHub")
        self.assertContains(response, f'href="{base}app/utils.py"')
        response = self.client.get(analysis.get_absolute_url())
        self.assertContains(response, f'href="https://github.com/org/repo/commit/{results["head_sha"]}"')
        self.assertIn(f"{base}app/core.py", self.client.get(reverse("files_csv", args=[analysis.pk])).content.decode())
