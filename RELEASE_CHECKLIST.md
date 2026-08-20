# Release Checklist (operator-only — manual steps)

Everything up to this point (assembly, sanitization, git init + one clean
commit on `main`, no remote) was done automatically. Everything below is
irreversible or requires your own credentials, and was deliberately left
for you to perform by hand.

- [ ] **1. Final human review of the tree**, especially
  `SANITIZATION_REPORT.md`. Read it fully — it lists every finding and the
  fix applied. Confirm you agree with the fixes and that nothing was
  missed. Pay particular attention to `results/*.csv` (raw kubectl error
  text) and `terraform/*.tf` if you've since made local changes — the
  scan was run at the time this artifact was assembled, not continuously.

- [ ] **2. Create the GitHub repository — PRIVATE first, not public yet.**
  ```bash
  cd c3-pac-artifact
  gh repo create <your-org-or-username>/c3-pac-artifact --private --source=. --remote=origin
  git push -u origin main
  ```
  (Or create it in the GitHub web UI, then `git remote add origin
  <url>` and `git push -u origin main`.)

- [ ] **3. Review the rendered README on GitHub.** Open the repo in a
  browser. Confirm the README renders correctly, and — since this is a
  private repo at this stage — do one more visual scan for anything that
  looks like a secret, real IP, or personal path that the automated scan
  might have missed. A human eyeballing the actual GitHub file browser is
  a different check than a local grep pass.

- [ ] **4. Flip the repository to public**, once step 3 is clean.
  (Settings → General → Danger Zone → Change visibility.)

- [ ] **5. Enable the GitHub–Zenodo integration** for this repo:
  https://zenodo.org/account/settings/github/ → toggle the repository on.
  Requires a Zenodo account linked to your GitHub account.

- [ ] **6. Cut a GitHub Release** (e.g. tag `v1.0.0`) from the `main`
  branch. This is the action that triggers Zenodo to archive the release
  and mint a DOI — it happens automatically within a few minutes of
  publishing the release, if step 5 was done correctly.

- [ ] **7. Copy the freshly-minted Zenodo DOI back into:**
  - `CITATION.cff` — both the top-level `identifiers` DOI and the
    `preferred-citation` DOI once the *paper's own* DOI is also assigned
    (these are two different DOIs — the software/Zenodo one and the
    Computers & Security article one — don't conflate them)
  - `.zenodo.json` — the `related_identifiers` TODO
  - the paper's **Data Availability Statement**
  - `README.md` — `repository-code` reference in `CITATION.cff` and any
    "how to cite" pointer you want in the README itself

  After editing, commit and push:
  ```bash
  git add CITATION.cff .zenodo.json
  git commit -m "Add DOI after Zenodo release"
  git push
  ```
  (This does **not** need a new GitHub Release — Zenodo only re-archives
  on new releases/tags, so a plain push here is fine for metadata fixes.)

- [ ] **8. Rotate any credential SANITIZATION_REPORT.md flagged.** As of
  this artifact's assembly, **no findings required rotation** — everything
  found was an identifier (IP, local path, stale public certificate), not
  a live credential. Re-check this box only applies if a future
  sanitization pass finds something different; don't skip reading the
  report just because this run was clean.

## Two things worth doing before step 2, not strictly required but cheap

- Run `git log -1 --stat` yourself and skim the file list one more time —
  69 files, no `.tfstate`, no `.terraform/`, no `CLAUDE.md`. Takes 30
  seconds, catches anything an automated pass structurally can't judge
  (e.g. "is this comment revealing something it shouldn't," which is a
  judgment call, not a pattern match).
- Consider whether you want `version: 1.0.0` in `CITATION.cff` to match
  the git tag you'll cut in step 6 (`v1.0.0`) — keeping those in sync
  avoids a confusing mismatch later.
