"""Runs analyses in background threads, recording progress on the Analysis row."""
import logging
import tempfile
import threading
from pathlib import Path

from django.conf import settings
from django.db import connection
from django.utils import timezone

from . import analysis as git_analysis
from .models import Analysis

logger = logging.getLogger(__name__)

_slots = threading.BoundedSemaphore(getattr(settings, "GIT_ANALYSIS_MAX_CONCURRENT", 2))


def start(analysis: Analysis):
    if getattr(settings, "GIT_ANALYSIS_RUN_SYNC", False):
        run(analysis.pk)
    else:
        threading.Thread(target=_run_in_thread, args=(analysis.pk,), daemon=True).start()


def _run_in_thread(pk):
    try:
        with _slots:
            run(pk)
    finally:
        connection.close()


def _update(pk, **fields):
    Analysis.objects.filter(pk=pk).update(**fields)


def run(pk):
    analysis = Analysis.objects.get(pk=pk)
    _update(pk, status=Analysis.Status.RUNNING, started_at=timezone.now(),
            stage="clone", message=f"Cloning {analysis.display_url} ({analysis.branch})")
    try:
        with tempfile.TemporaryDirectory(prefix="git-analysis-") as tmp:
            repo_dir = git_analysis.clone(
                analysis.repo_url, analysis.branch, Path(tmp) / "repo",
                timeout=getattr(settings, "GIT_ANALYSIS_CLONE_TIMEOUT", 900),
            )
            results = git_analysis.analyse_repository(
                repo_dir,
                exclude_dirs=analysis.exclude_dirs,
                exclude_files=analysis.exclude_files,
                max_changeset=analysis.max_changeset,
                progress=lambda stage, message: _update(pk, stage=stage, message=message),
            )
    except Exception as exc:
        logger.exception("Analysis %s failed", pk)
        _update(pk, status=Analysis.Status.FAILED, error=str(exc) or exc.__class__.__name__,
                finished_at=timezone.now())
        return
    _update(pk, status=Analysis.Status.DONE, stage="done", results=results,
            message=f"Analysed {len(results['files'])} files", finished_at=timezone.now())
