import csv
import statistics

from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django_htmx.http import HttpResponseClientRedirect, HttpResponseClientRefresh

from . import charts, runner
from .analysis import GitError, list_branches
from .forms import OptionsForm, RepoForm
from .models import Analysis

TABS = [
    ("overview", "Overview"),
    ("files", "Files"),
    ("hotspots", "Hotspots"),
    ("coupling", "Coupling"),
    ("guide", "Metric guide"),
]
FILE_COLUMNS = [
    ("file", "File"),
    ("loc", "LOC"),
    ("avg_cc", "Avg CC"),
    ("max_cc", "Max CC"),
    ("mi", "MI"),
    ("n_commits", "Commits"),
    ("churn", "Churn"),
    ("change_rate", "Rate/mo"),
    ("coupling_degree", "Coupled"),
    ("risk_score", "Risk"),
]
SUMMARY_COLUMNS = ["loc", "avg_cc", "max_cc", "mi", "n_commits", "churn", "change_rate"]
FILES_PER_PAGE = 50


# ── wizard ─────────────────────────────────────────────────────────────────────

def index(request):
    return render(request, "analyzer/index.html", {
        "form": RepoForm(initial={"repo_url": request.GET.get("repo_url", "")}),
        "recent": Analysis.objects.defer("results")[:10],
    })


@require_GET
def step_repo(request):
    form = RepoForm(initial={"repo_url": request.GET.get("repo_url", "")})
    return render(request, "analyzer/partials/step_repo.html", {"form": form})


@require_POST
def inspect_repo(request):
    """Step 1 → 2: validate the URL and list its branches with `git ls-remote`."""
    form = RepoForm(request.POST)
    if form.is_valid():
        try:
            branches, default = list_branches(form.cleaned_data["repo_url"])
        except GitError as exc:
            form.add_error("repo_url", f"Could not read repository: {exc}")
        else:
            if not branches:
                form.add_error("repo_url", "The repository has no branches.")
            else:
                options = OptionsForm(initial={
                    "repo_url": form.cleaned_data["repo_url"],
                    "branch": default or branches[0],
                })
                return render(request, "analyzer/partials/step_options.html",
                              {"form": options, "branches": branches})
    return render(request, "analyzer/partials/step_repo.html", {"form": form})


@require_POST
def create_analysis(request):
    """Step 2 → 3: create the analysis and start it in the background."""
    form = OptionsForm(request.POST)
    if not form.is_valid():
        return render(request, "analyzer/partials/step_options.html",
                      {"form": form, "branches": request.POST.getlist("branches")})
    analysis = Analysis.objects.create(**form.cleaned_data)
    runner.start(analysis)
    return _redirect(request, analysis)


@require_POST
def rerun_analysis(request, pk):
    old = get_object_or_404(Analysis.objects.defer("results"), pk=pk)
    analysis = Analysis.objects.create(
        repo_url=old.repo_url, branch=old.branch, exclude_dirs=old.exclude_dirs,
        exclude_files=old.exclude_files, max_changeset=old.max_changeset,
    )
    runner.start(analysis)
    return _redirect(request, analysis)


@require_http_methods(["DELETE"])
def delete_analysis(request, pk):
    get_object_or_404(Analysis, pk=pk).delete()
    return HttpResponse("")


def _redirect(request, analysis):
    if request.htmx:
        return HttpResponseClientRedirect(analysis.get_absolute_url())
    return redirect(analysis)


# ── progress ───────────────────────────────────────────────────────────────────

@require_GET
def analysis_progress(request, pk):
    analysis = get_object_or_404(Analysis.objects.defer("results"), pk=pk)
    if analysis.is_finished:
        return HttpResponseClientRefresh()
    return render(request, "analyzer/partials/progress.html", {"analysis": analysis})


# ── results ────────────────────────────────────────────────────────────────────

def _done_analysis(pk):
    analysis = get_object_or_404(Analysis, pk=pk)
    if analysis.status != Analysis.Status.DONE:
        raise Http404("Analysis is not finished")
    return analysis


@require_GET
def analysis_detail(request, pk, tab="overview"):
    if tab not in dict(TABS):
        raise Http404
    analysis = get_object_or_404(Analysis, pk=pk)
    if analysis.status != Analysis.Status.DONE:
        return render(request, "analyzer/progress_page.html", {"analysis": analysis})

    context = {
        "analysis": analysis,
        "results": analysis.results,
        "tab": tab,
        "tabs": TABS,
        "tab_template": f"analyzer/tabs/{tab}.html",
        **TAB_CONTEXT.get(tab, lambda request, results: {})(request, analysis.results),
    }
    if request.htmx and request.htmx.target == "results-body":
        response = render(request, "analyzer/partials/results_body.html", context)
    else:
        response = render(request, "analyzer/results.html", context)
    patch_vary_headers(response, ["HX-Request", "HX-Target"])
    return response


def _overview_context(request, results):
    files = results["files"]
    with_mi = [f for f in files if f["mi"] is not None]
    with_cc = [f for f in files if f["avg_cc"] is not None]
    return {
        "kpis": {
            "files": len(files),
            "commits": results["total_commits"],
            "loc": sum(f["loc"] for f in files),
            "mean_cc": statistics.fmean(f["avg_cc"] for f in with_cc) if with_cc else None,
            "maintainable_pct": (100 * sum(f["mi"] >= 65 for f in with_mi) / len(with_mi)) if with_mi else None,
            "complex_files": sum(f["cc_rank"] in ("D", "E", "F") for f in files),
        },
        "summary": summarise(files),
    }


def _files_context(request, results):
    files = list(results["files"])
    query = request.GET.get("q", "").strip()
    sort = request.GET.get("sort", "risk_score")
    direction = request.GET.get("dir", "desc")
    if sort not in dict(FILE_COLUMNS):
        sort = "risk_score"
    if query:
        files = [f for f in files if query.lower() in f["file"].lower()]
    present = [f for f in files if f[sort] is not None]
    missing = [f for f in files if f[sort] is None]
    present.sort(key=lambda f: f[sort], reverse=direction == "desc")
    page = Paginator(present + missing, FILES_PER_PAGE).get_page(request.GET.get("page"))
    return {"page": page, "q": query, "sort": sort, "dir": direction, "columns": FILE_COLUMNS}


def _hotspots_context(request, results):
    return {"hotspots": [f for f in results["files"] if f["risk_score"]][:30]}


def _coupling_context(request, results):
    pairs = results["pairs"][:30]
    degree = results["degree"][:30]
    return {
        "pairs": pairs,
        "max_co_commits": max((p["co_commits"] for p in pairs), default=1),
        "degree": degree,
        "max_degree": max((d["coupling_degree"] for d in degree), default=1),
    }


TAB_CONTEXT = {
    "overview": _overview_context,
    "files": _files_context,
    "hotspots": _hotspots_context,
    "coupling": _coupling_context,
}


def summarise(files):
    """Equivalent of polars' DataFrame.describe() for the numeric columns."""
    rows = []
    for column in SUMMARY_COLUMNS:
        values = sorted(f[column] for f in files if f[column] is not None)
        if not values:
            continue
        quartiles = statistics.quantiles(values, n=4, method="inclusive") if len(values) > 1 else values * 3
        rows.append({
            "column": column,
            "count": len(values),
            "mean": statistics.fmean(values),
            "std": statistics.stdev(values) if len(values) > 1 else 0.0,
            "min": values[0],
            "q1": quartiles[0],
            "median": quartiles[1],
            "q3": quartiles[2],
            "max": values[-1],
        })
    return rows


@require_GET
def files_table(request, pk):
    analysis = _done_analysis(pk)
    context = {"analysis": analysis, **_files_context(request, analysis.results)}
    return render(request, "analyzer/partials/files_table.html", context)


@require_GET
def file_detail(request, pk):
    analysis = _done_analysis(pk)
    path = request.GET.get("path", "")
    file = next((f for f in analysis.results["files"] if f["file"] == path), None)
    if file is None:
        raise Http404
    current_files = {f["file"] for f in analysis.results["files"]}
    partners = []
    for pair in analysis.results["pairs"]:
        if path in (pair["file_a"], pair["file_b"]):
            other = pair["file_b"] if pair["file_a"] == path else pair["file_a"]
            partners.append({**pair, "other": other, "exists": other in current_files})
    return render(request, "analyzer/partials/file_detail.html",
                  {"analysis": analysis, "file": file, "partners": partners[:15]})


@require_GET
def files_csv(request, pk):
    analysis = _done_analysis(pk)
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{analysis.repo_name}-files.csv"'
    fields = list(analysis.results["files"][0]) if analysis.results["files"] else []
    writer = csv.DictWriter(response, fieldnames=fields)
    writer.writeheader()
    writer.writerows(analysis.results["files"])
    return response


@require_GET
def chart(request, pk, name):
    if name not in charts.CHARTS:
        raise Http404
    analysis = _done_analysis(pk)
    response = HttpResponse(charts.render_png(name, analysis.results), content_type="image/png")
    response["Cache-Control"] = "private, max-age=86400"  # results never change once done
    return response
