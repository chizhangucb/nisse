# CHI-219 — nisse CI + confidentiality guard + tag releases + CodeRabbit + PR flow + branch protection

Status: approved 2026-08-24 (Chi). Plan-first per `governance/building.md`.
Ticket: https://linear.app/chi-personal-space/issue/CHI-219

## Goal

Give nisse a full CI/PR posture: CI (pytest + ruff + a confidentiality guard) on
push and PR to `main`, tag-based release notes (no CD), a PR-only flow enforced
by branch protection mirroring chronicle, CodeRabbit reviewing PRs, and a written
confirmation that the egress gate covers nisse's push/merge.

## Verified facts (2026-08-24)

- Python, **stdlib-only**. 4 pytest suites in `scripts/tests/`
  (`test_hygiene_check`, `test_ticket_tracker`, `test_transcript_quality_score`,
  `test_wiki_retranscribe`). Local Python 3.14; code uses only 3.9+ stdlib.
- No `.github/`, no ruff/pyproject today. Remote `chizhangucb/nisse`, public.
- **No pre-existing `/Users/`+`chizhang` denylist scanner.** `hygiene_check.py`
  provides reusable machinery only — `walk_files()`, `read_text()`, `rel()`,
  `_git_ignored()`, `git()`. The guard builds on those; it does not rewrite them.
- **Naive denylist would false-positive on legit content.** Two current tracked
  hits, both legitimate:
  - `scripts/templates/com.example.daily-maintenance.plist.template` → generic
    placeholder `/Users/<you>`.
  - `README.md` → public GitHub handle `chizhangucb` (public repo, intended).
  The guard must catch the real leak (absolute home paths `/Users/chizhang`,
  `/home/chizhang`) while allowing `/Users/<placeholder>` and `chizhangucb`.
  Today's *tracked* tree passes (every `chizhang` hit is `chizhangucb`; the only
  `/Users/` hit is the `/Users/<you>` placeholder). **But the guard's own
  artifacts break a naive design:** its source literally contains the pattern
  `chizhang` (a bare-`chizhang` rule matches itself), its test plants
  `/Users/chizhang` fixtures, and *this plan doc itself* contains `/Users/chizhang`,
  bare `chizhang`, and `~/chizhang-2` (line 37 — a `(?!ucb)` lookahead does NOT
  spare `chizhang-2`). So a bare-`chizhang` word-boundary rule is fundamentally
  too broad (the handle is public; `chizhang-2` is a legit local path token in
  docs) and the scan must exclude its own self-referential files. Fix is in
  deliverable 3.
- **Chronicle live protection** (mirror target): `strict:false`, contexts = job
  names (`check`,`e2e`), `required_pull_request_reviews` with
  `required_approving_review_count:0`, `enforce_admins:true`, force-push and
  deletion off, signatures/linear-history off.
- **nisse today**: `enforce_admins:true`, force-push off, deletion off; **no**
  required checks, **no** required PR reviews.
- **Egress (item 5), already largely confirmable**: real gate config at
  `~/.config/egress-gate` + `~/chizhang-2/scripts/gating_policy.json` pins
  **nisse → `github.com/chizhangucb/nisse.git`, branch `main`**, correctly
  *without* `confidential_ok` (public repo → confidentiality floor stays ON as a
  leak tripwire). `git push` is conditioned-auto (CHI-205) against that pin.
  `gh pr merge` is intentionally **unclassified** → post-CHI-229 it cards via the
  "card + classify" catch-all for a reachable session; branch protection is the
  real merge gate. CHI-229's *suggested dedicated* `gh pr merge` classification
  entry was never added — still on the catch-all (surface as a finding, do not
  fix here).

## Decisions (chosen defaults)

1. **CI Python = 3.12**, single version. Code is 3.9+ stdlib-only so any works;
   3.12 is stable and fast on runners. (Alt considered: matrix / match-3.14 —
   rejected as unneeded cost.)
2. **CodeRabbit**: land `.coderabbit.yaml` (review-only, no summaries). The App
   install is Chi's OAuth click; plan hands her the install link. Not dropped.

## Deliverables (in order)

### 1. `.github/workflows/ci.yml`
Triggers: `push` to `main`, `pull_request` to `main`. `concurrency` group per ref,
`cancel-in-progress`. Three jobs — **job names are the required-check contexts**:
- `test`: `actions/setup-python@v5` (3.12), `pip install pytest`,
  `pytest scripts/tests/` (run from repo root — the checkout default; tests
  self-insert `scripts/` on `sys.path`, no conftest needed, verified 37 pass in a
  clean venv). Drop `ruff` from this job's install — it belongs to `lint`.
- `lint`: same setup, `ruff check .`.
- `confidentiality`: same setup, `python3 scripts/confidentiality_guard.py`.

### 2. `pyproject.toml`
`[tool.ruff]` only (no packaging metadata). Rule set `E,F,W,I`; `line-length`
tuned so existing code passes; `target-version = "py39"`. Run ruff locally and fix
trivial hits before pushing so CI is green first try. Baseline (measured
2026-08-24, `--select E,F,W,I`): **25 hits — 12 `E501`, 6 `I001`, 4 `E401`, 3
`F401`**; the non-E501 ones auto-fix (`ruff check --fix`) and E501 clears by
tuning `line-length`, so no code churn needed. **ruff/pytest are not installed on
this machine** (`python3` is 3.14, no `ruff`, no `pytest` module) — create a venv
first: `python3 -m venv .venv && .venv/bin/pip install ruff pytest`.

### 3. `scripts/confidentiality_guard.py` (+ `scripts/tests/test_confidentiality_guard.py`)
Imports helpers from `hygiene_check`. Read-only; exits non-zero with a clear
report on any finding. Three checks, over a self-excluded scan scope:
- **Home-path denylist**: the leak signal is the **absolute home path** —
  `/Users/chizhang`, `/home/chizhang` (and `\Users\chizhang`). The bare-`chizhang`
  handle is NOT confidential (it is the public GitHub/email identity) and appears
  in legit tokens (`chizhangucb`, `~/chizhang-2`), so do **not** auto-fail on bare
  `chizhang`; match only the path-prefixed leak forms above. Allowlist:
  `/Users/<placeholder>` forms, `chizhangucb`.
- **Scan scope + self-exclusion (required, or the guard fails on its own commit)**:
  scan **git-tracked files only** (`git ls-files`; skips gitignored and `.git/`),
  and exclude self-referential files that legitimately carry leak-shaped strings:
  the guard source `scripts/confidentiality_guard.py`, its test, and the doc trees
  `plans/`, `plans/workstate/`, `archives/plans/` (which discuss the patterns).
  The test must plant leak fixtures in a **tempdir at runtime** (like the existing
  `scripts/tests/`), never as tracked literal strings, so the test file carries no
  leak the scan would trip on.
- **Synthetic-fixture markers**: designated example/fixture files (e.g. the
  shipped `wiki/raw/transcripts/2026-01-05_example_weekly_sync.md`) must carry a
  synthetic marker keyword (`example|synthetic|fixture|fake|sample`).
- **`.gitignore` coverage**: required ignore patterns present (`.env`,
  `wiki/raw/transcripts/*`, `.claude/settings.local.json`, `.claude/state/`,
  `records/.sessions_index.lock`, `.tmp/`).
Tests cover: clean tree passes; a planted `/Users/chizhang` (in a tempdir) fails;
`chizhangucb`, `~/chizhang-2`, and `/Users/<you>` do **not** trip; the guard's own
source/test and `plans/` docs are excluded from the scan; a missing gitignore
entry fails.

### 4. `.github/workflows/release.yml`
Trigger: `push: tags: ['v*']`. Generate release notes via
`softprops/action-gh-release` with `generate_release_notes: true`. **No CD, no
artifact build.** Needs `contents: write` permission.

### 5. `.coderabbit.yaml`
Review-only. These toggles live under a top-level `reviews:` block
(`reviews.high_level_summary`, `reviews.poem`, `reviews.review_status`,
`reviews.auto_review.enabled: true`); `walkthrough` may not be a standalone key —
**validate exact schema keys against CodeRabbit docs before writing** (building.md
validation rule). Hand Chi the App install link.

### 6. PR flow + branch protection (sequencing)
1. Feature branch `chizhangucb/chi-219-nisse-ci-...` → add all files.
2. **Push via `egress git push`** (respect the gate; never raw push).
3. Open PR to `main`; let CI run; fix to green; capture exact check-run names.
4. Merge PR #1 via **`egress gh pr merge`** (gated) so `ci.yml` lands on `main`.
5. Apply branch protection mirroring chronicle. The `PUT
   .../branches/main/protection` body **requires all four top-level fields present
   (nullable), or it 422s** — `required_status_checks`, `enforce_admins`,
   `required_pull_request_reviews`, **`restrictions`** (the plan previously omitted
   `restrictions`; for a user-owned repo it must be `null`). Send it as a JSON body
   via `--input` (not `-f`/`-F` flags — the nested `contexts` array and typed
   booleans don't survive `-f`), e.g. `gh api -X PUT
   repos/chizhangucb/nisse/branches/main/protection --input body.json` with:
   - `enforce_admins: true`
   - `required_status_checks: {"strict": false, "contexts": ["test","lint","confidentiality"]}`
   - `required_pull_request_reviews: {"required_approving_review_count": 0}`
     (forces PR flow; 0 approvals + `enforce_admins:true` lets the admin merge her
     own PR once checks are green — chronicle runs this exact config, no deadlock)
   - `restrictions: null`
   - `allow_force_pushes: false`, `allow_deletions: false`
   This closes direct-push to `main`.
6. Tag `v0.1.0` to prove release notes generate.

### 7. Close-out
- Confirm item 5 in writing (egress push pin verified; `gh pr merge` cards via
  catch-all; branch protection owns merge). Surface the CHI-229 leftover finding.
- Session ID + completion comment on CHI-219; move to **In Review**.
- Archive this plan to `archives/plans/` on ship (building.md).
- Workstate file at `plans/workstate/2026-08-24-chi-219.md`, updated per milestone.

## Cost / posture

- CI cost trivial (pure Python, no build/browser).
- Branch-protection + merge are outward GitHub state changes → confirm-first;
  plan approval + the gated `egress` path cover them; each shown before firing.

## Risks / watch-items

- Required-check contexts are the bare job ids (`test`,`lint`,`confidentiality`) —
  chronicle proves the un-prefixed form works (its `check`,`e2e` == its job ids,
  no `<workflow> /` prefix). GitHub does **not** 422 on a context it has never
  seen; the real failure mode is a name typo → every future PR hangs forever on a
  perpetually-pending required check. So capture the exact check-run names from
  PR #1's run (step 3) and apply protection (step 5) only after they've reported
  at least once.
- CodeRabbit App install is out-of-band (Chi's OAuth); config is inert until then.
- If ruff surfaces many pre-existing hits, prefer tuning config over a large
  code churn in this ticket; note any deferred cleanups.
