import re
from pathlib import Path

from django import forms
from django.conf import settings

from .analysis import DEFAULT_EXCLUDE_DIRS, DEFAULT_EXCLUDE_FILES, DEFAULT_MAX_CHANGESET

SSH_URL = re.compile(r"^(ssh://[^\s]+|[\w.-]+@[\w.-]+:[^\s]+)$")
HTTPS_URL = re.compile(r"^https://[^\s]+$")
BRANCH_NAME = re.compile(r"^(?!-)(?!.*\.\.)(?!.*//)[\w./-]+(?<![./])$")


def _split_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


class RepoForm(forms.Form):
    repo_url = forms.CharField(max_length=500, strip=True)

    def clean_repo_url(self):
        url = self.cleaned_data["repo_url"]
        if url.startswith("-"):
            raise forms.ValidationError("That doesn't look like a repository URL.")
        if HTTPS_URL.match(url):
            return url
        if SSH_URL.match(url):
            if not getattr(settings, "GIT_ANALYSIS_ALLOW_SSH", False):
                raise forms.ValidationError("SSH URLs are disabled on this server — use an https:// URL.")
            return url
        if url.startswith(("/", "~", "file://")):
            if not getattr(settings, "GIT_ANALYSIS_ALLOW_LOCAL", False):
                raise forms.ValidationError("Local paths are disabled on this server — use an https:// URL.")
            path = Path(url.removeprefix("file://")).expanduser()
            if not path.is_dir():
                raise forms.ValidationError(f"No such directory: {path}")
            return str(path)
        raise forms.ValidationError("Enter an https:// URL (e.g. https://github.com/org/repo.git).")


class OptionsForm(RepoForm):
    branch = forms.CharField(max_length=255)
    exclude_dirs = forms.CharField(required=False, initial=", ".join(DEFAULT_EXCLUDE_DIRS))
    exclude_files = forms.CharField(required=False, initial=", ".join(DEFAULT_EXCLUDE_FILES))
    max_changeset = forms.IntegerField(min_value=2, max_value=10_000, initial=DEFAULT_MAX_CHANGESET)

    def clean_branch(self):
        branch = self.cleaned_data["branch"]
        if not BRANCH_NAME.match(branch):
            raise forms.ValidationError("Invalid branch name.")
        return branch

    def clean_exclude_dirs(self):
        return _split_list(self.cleaned_data["exclude_dirs"])

    def clean_exclude_files(self):
        return _split_list(self.cleaned_data["exclude_files"])
