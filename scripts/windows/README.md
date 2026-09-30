# windows source builds

Read the [shared operational guide](../nightly/README.md),
[workflow](../nightly/workflow.md) and [windows profile](../nightly/profiles/windows.md).

Automation definitions remain in their existing registry. Package verification and
run records use `scripts/nightly.py`; see its `--help` and the shared guide.

After successful verification, Windows builds remove older package directories.
The latest verified package and packages with running executables are kept;
locked packages are retried after the next successful build. Run logs and the
shared compilation cache remain available.
