# Publishing

This repository is a generated public snapshot. Development happens in a
private source repository; only the sanitised export is published here.

- **Public repo:** <https://github.com/A-viral-dev/RPT_Viewer>
- **Publish tool:** [`publish_public.ps1`](publish_public.ps1)
- **History policy:** one commit per snapshot

## Snapshot model

The public repo is a mirror: it holds exactly one commit whose tree equals the
sanitised export. The private source repository remains the only place where
development happens.

## Before publishing

1. Run the test suite.
2. Run the fixture hygiene tests and confirm every account number, name,
   branch, bank reference and credential is synthetic.
3. Review the exported tree for local paths and generated output files.

## One-time setup

```powershell
git config rpt.publicRemote https://github.com/A-viral-dev/RPT_Viewer.git
```

## Publishing

```powershell
.\publish_public.ps1 -Message "Initial public snapshot"
```

Refresh an existing snapshot:

```powershell
.\publish_public.ps1 -Message "Fix CC001 column detection"
```

Preview without pushing:

```powershell
.\publish_public.ps1 -DryRun -Message "test"
```

## Safety checks performed by the script

1. **Clean tree** - refuses to publish if this folder has uncommitted changes
   (override with `-AllowDirty`, which publishes the last commit only).
2. **Leak scan** - checks the exported tree against the private leak list and
   aborts on a hit.
3. **Committed tree only** - exports `HEAD:<folder>` via `git archive`, so
   ignored files such as `.venv/`, `build/` and private configuration never
   ship.

## History warning

Force-pushing a new snapshot does **not** delete old commits from GitHub. If a
snapshot ever contains sensitive data, delete and recreate the public
repository (or ask GitHub Support to purge unreachable commits) instead of
force-pushing over it.

## Force-push note

Each publish rewrites the public repo's single commit, so the script pushes with
`--force`. That is safe only while every published snapshot is known to be
clean and no sensitive data has ever been published.
