"""Links from an analysed repo URL to the hosting service's web UI (GitHub, GitLab, Bitbucket)."""
import re
from urllib.parse import quote, urlsplit

# {base} = https://host/org/repo, {sha} = commit, {path} = url-quoted file path
URL_PATTERNS = {
    "github": {"file": "{base}/blob/{sha}/{path}", "commit": "{base}/commit/{sha}"},
    "gitlab": {"file": "{base}/-/blob/{sha}/{path}", "commit": "{base}/-/commit/{sha}"},
    "bitbucket": {"file": "{base}/src/{sha}/{path}", "commit": "{base}/commits/{sha}"},
}
HOST_NAMES = {"github": "GitHub", "gitlab": "GitLab", "bitbucket": "Bitbucket"}

SCP_LIKE = re.compile(r"^[\w.-]+@(?P<host>[\w.-]+):(?P<path>.+)$")


def _host_and_path(repo_url: str) -> tuple[str, str] | None:
    """Split https://, ssh:// and git@host:path URLs into (host, org/repo), dropping credentials."""
    if match := SCP_LIKE.match(repo_url):
        host, path = match["host"], match["path"]
    elif repo_url.startswith(("https://", "http://", "ssh://")):
        parts = urlsplit(repo_url)
        host, path = parts.hostname or "", parts.path
    else:
        return None  # local path
    path = path.strip("/").removesuffix(".git")
    return (host.lower(), path) if host and path else None


def host_kind(host: str, custom_hosts: dict | None = None) -> str | None:
    """'github'/'gitlab'/'bitbucket' for a host; `custom_hosts` maps self-hosted servers, e.g. {"git.corp": "gitlab"}."""
    if custom_hosts and host in custom_hosts:
        return custom_hosts[host]
    for kind in ("github", "gitlab", "bitbucket"):
        if kind in host:
            return kind
    return None


class RepoLinks:
    def __init__(self, repo_url: str, sha: str | None, custom_hosts: dict | None = None):
        self.base = self.kind = None
        self.sha = sha
        if sha and (parsed := _host_and_path(repo_url)):
            host, path = parsed
            self.kind = host_kind(host, custom_hosts)
            if self.kind in URL_PATTERNS:
                self.base = f"https://{host}/{path}"

    def __bool__(self):
        return self.base is not None

    @property
    def host_name(self):
        return HOST_NAMES.get(self.kind, "")

    def file(self, path: str) -> str | None:
        if not self:
            return None
        return URL_PATTERNS[self.kind]["file"].format(base=self.base, sha=self.sha, path=quote(path, safe="/"))

    def commit(self) -> str | None:
        if not self:
            return None
        return URL_PATTERNS[self.kind]["commit"].format(base=self.base, sha=self.sha)
