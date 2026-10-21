import re
import uuid

from django.db import models
from django.urls import reverse
from django.utils.functional import cached_property

from .links import RepoLinks


class Analysis(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Queued"
        RUNNING = "running", "Running"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    # Ordered stages shown in the progress stepper
    STAGES = [
        ("queued", "Queued"),
        ("clone", "Clone repository"),
        ("history", "Read git history"),
        ("metrics", "Measure complexity"),
        ("coupling", "Logical coupling"),
        ("done", "Done"),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    repo_url = models.CharField(max_length=500)
    branch = models.CharField(max_length=255)
    exclude_dirs = models.JSONField(default=list)
    exclude_files = models.JSONField(default=list)
    max_changeset = models.PositiveIntegerField(default=100)

    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    stage = models.CharField(max_length=20, default="queued")
    message = models.CharField(max_length=500, blank=True)
    error = models.TextField(blank=True)
    results = models.JSONField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name_plural = "analyses"

    def __str__(self):
        return f"{self.repo_name}@{self.branch}"

    def get_absolute_url(self):
        return reverse("analysis_detail", args=[self.pk])

    @property
    def display_url(self):
        """The repo URL with any embedded credentials (e.g. a personal access token) masked."""
        return re.sub(r"//[^/@]+@", "//***@", self.repo_url)

    @property
    def repo_name(self):
        return self.repo_url.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1].removesuffix(".git") or self.repo_url

    @cached_property
    def links(self):
        """Permalinks to files and the analysed commit on GitHub/GitLab/Bitbucket (falsy if unknown host)."""
        return RepoLinks(self.repo_url, (self.results or {}).get("head_sha"))

    @cached_property
    def current_files(self):
        return {f["file"] for f in (self.results or {}).get("files", [])}

    def file_url(self, path):
        """Link to `path` at the analysed commit; None for unknown hosts or files no longer in the tree."""
        return self.links.file(path) if path in self.current_files else None

    @property
    def is_finished(self):
        return self.status in (self.Status.DONE, self.Status.FAILED)

    @property
    def duration(self):
        if self.started_at and self.finished_at:
            return self.finished_at - self.started_at
        return None

    def stage_states(self):
        """[(key, label, state)] where state is 'done', 'current', 'failed' or 'todo'."""
        keys = [k for k, _ in self.STAGES]
        current = keys.index(self.stage) if self.stage in keys else 0
        states = []
        for i, (key, label) in enumerate(self.STAGES):
            if self.status == self.Status.DONE or i < current:
                state = "done"
            elif i == current:
                state = "failed" if self.status == self.Status.FAILED else "current"
            else:
                state = "todo"
            states.append((key, label, state))
        return states
