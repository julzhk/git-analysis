# git-code-quality: a Claude Code plugin

Ask Claude about the code quality of a git repository and get:
- **hotspots:** complex Python files that change often;
- **the most complex files**, with their radon grades;
- **logically coupled files:** files that keep changing together;
- **an offline, interactive HTML report.**

Inspired by Adam Tornhill's [*Your Code as a Crime Scene*](https://pragprog.com/titles/atcrime2/your-code-as-a-crime-scene-second-edition/). The same analysis also powers the Django web app in [the parent repository](../../README.md).

## Install

```
/plugin install git-code-quality --marketplace julzhk/git-analysis
```

Requires `git` and [`uv`](https://docs.astral.sh/uv/). Without `uv`, run `pip install radon jinja2` and use `python3`.

## Use

Ask naturally, for example:
- "What are the code-quality hotspots in this repo?"
- "Analyse https://github.com/psf/requests.git and tell me what to refactor first."
- "Which files in this project are logically coupled? Ignore the tests directory."

Claude runs the bundled script, reads its summary and explains the results. It then points you to `report.html`.

## The script

```
uv run skills/git-code-quality/scripts/analyse.py [TARGET] [options]

TARGET                  local repo (default: .) or https://, ssh://, git@host:org/repo URL
--branch NAME           branch to analyse (default: remote default / local checked-out branch)
--exclude-dir DIR       directory name to skip, repeatable (replaces the defaults)
--exclude-file NAME     file name to skip, repeatable (replaces the defaults)
--max-changeset N       ignore commits touching > N files for coupling (default 100)
--working-tree          local only: measure the checked-out files incl. uncommitted edits
--out DIR               output directory (default: a new temp directory)
```

Outputs:
- **stdout:** a Markdown summary.
- **`results.json`:** every file's metrics and the coupled pairs, in the same shape the web app stores.
- **`report.html`:** a self-contained page with no external requests. It has:
  - KPI cards;
  - two interactive scatters (complexity vs change rate, churn vs LOC) with a log/linear toggle;
  - top-20 bar charts;
  - the rank distribution;
  - hotspot and coupling tables.

  Hovering shows full paths and metrics. Clicking opens the file on GitHub, GitLab or Bitbucket.

The web app's MI histogram, rank donut and coupling heatmap aren't included. The report's tables carry that information.

## Safety

- Code is parsed by radon, never executed.
- Git runs with terminal prompts disabled and only the https, ssh and local-file transports allowed. `ext::`, `git://` and option-like targets are rejected.
- Remote repos and `--branch` runs are cloned into a temporary directory that is deleted afterwards. A local repo is never modified.

## Caveats

Python only, and the metrics are heuristics. See [`skills/git-code-quality/references/metrics.md`](skills/git-code-quality/references/metrics.md).

## License

GPL-3.0-or-later. See [LICENSE](../../LICENSE).
