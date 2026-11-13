# Metrics reference

Read this when interpreting results or answering "what does X mean?". Every metric is per Python file.

## Metrics

| Metric | What it measures | How to read it |
|---|---|---|
| `avg_cc` | Mean cyclomatic complexity of the file's functions (radon) | Branches per function. Above 5 means a lot of branching; above 10 is hard to reason about. |
| `max_cc` / `cc_rank` | Complexity of the single worst function, and its grade A–F | One very complex function can be a testing blind spot even when the average looks fine. |
| `mi` | Maintainability Index, 0–100 (Halstead volume, complexity and LOC combined) | 65 or more: maintainable. 20–65: moderate. Below 20: hard to maintain. |
| `loc` | Non-blank, non-comment lines | Size predicts defects. Very large files usually hold several responsibilities. |
| `n_commits` | Commits that touched the file | How often people need to change it. |
| `churn` | Lines added + deleted across all commits | How much editing happens. Churn that is high relative to the file's size is a known defect predictor (Nagappan & Ball 2005). |
| `change_rate` | Commits per month over the file's active lifespan (first to last commit) | `n_commits` normalised by age. Needs at least 2 commits, otherwise 0. |
| `risk_score` | `avg_cc × ln(1 + change_rate)` | **The hotspot metric** (Tornhill, *Your Code as a Crime Scene*). Complex code that changes often is where defects get introduced. |
| `coupling_strength` | co-commits ÷ commits touching either file (Jaccard, 0–1) | Files that change together without an explicit dependency suggest hidden coupling, duplicated logic or a shared responsibility. |
| `coupling_degree` | Number of distinct co-change partners | Files that change with everything (settings, routers, god objects) are change magnets. |

## Radon complexity grades

| Grade | CC | Meaning |
|:-:|:-:|---|
| A | 1–5 | Simple, low risk |
| B | 6–10 | Well structured, some branching |
| C | 11–20 | Moderately complex |
| D | 21–30 | More complex, harder to test |
| E | 31–40 | Complex, alarming |
| F | 41+ | Very high risk, effectively untestable |

## Hotspot quadrants (complexity vs change rate)

- **High complexity, high change rate:** prioritise. Refactor, add tests, split the file.
- **High complexity, low change rate:** refactor opportunistically when you next touch it.
- **Low complexity, high change rate:** watch it. It's often configuration, routing or a change magnet; check its coupling.
- **Low complexity, low change rate:** healthy.

## Caveats (mention the relevant ones in reports)

- **Correlation, not causation.** Hotspots show where to look, not proof of a problem.
- **Python only.** Other languages are ignored, including their history and coupling.
- **Files that fail to parse** (e.g. Python 2) have no complexity or risk (`—`).
- **`avg_cc` hides single bad functions.** Always look at `max_cc` too.
- **Young files have noisy change rates.** Two commits a day apart score about 60 commits a month. Files with a single commit score 0.
- **Renames reset history** (`--no-renames`). A moved file starts fresh, and its old path can appear in coupling.
- **Merge commits** contribute no file changes.
- **Vendored, generated or bulk-edited code skews coupling.** Re-run with `--exclude-dir <dir>`, or lower `--max-changeset` to drop reformatting and mass-rename commits.
- **Tests count too.** Use `--exclude-dir tests` to focus on production code.
- Only the top 2,000 coupled pairs are stored.

## References

- McCabe, "A Complexity Measure", IEEE TSE 1976: https://doi.org/10.1109/TSE.1976.233837
- Radon: https://radon.readthedocs.io/en/latest/intro.html
- Coleman et al., "Using Metrics to Evaluate Software System Maintainability", IEEE Computer 1994: https://doi.org/10.1109/2.303623
- Nagappan & Ball, "Use of Relative Code Churn Measures to Predict System Defect Density", ICSE 2005: https://doi.org/10.1145/1062455.1062514
- Tornhill, *Your Code as a Crime Scene* (2nd ed.): https://pragprog.com/titles/atcrime2/your-code-as-a-crime-scene-second-edition/
- Gall, Hajek & Jazayeri, "Detection of Logical Coupling Based on Product Release History", ICSM 1998: https://doi.org/10.1109/ICSM.1998.738508
