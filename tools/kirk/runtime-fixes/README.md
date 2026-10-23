# Kirk runtime fix staging series

This branch preserves review patches for a later Kirk PR. It does not change the LTP Kirk submodule pointer or apply these patches automatically.

LTP base: f1fe6fcf68e08eda248186107d77095f550669f5.
Exact Kirk patch base: fc28d0b526047b6fd54b931a7aa6e369ed4bc1fb (the runtime version used for the local diagnosis). This differs from the Kirk submodule pinned in this LTP base; do not blindly apply against that submodule.

Apply the numbered patches in order using `git apply` in a checkout of the exact Kirk base. 0001 and 0002 extract the Linux CI patch-kirk-monotonic.py transformations; 0003 is the separate local full-suite timeout fix. Python compilation passed. These are review candidates, not an upstream-ready or independently regression-tested series.

## Required before a PR

- Rebase onto current linux-test-project/kirk and inspect all elapsed clock conversions; calendar timestamps must remain realtime.
- Add focused tests for wall-clock changes, buffered output after process exit, output exceeding pipe capacity, split panic messages and cancellation.
- Review killing descendants after shell exit and unbounded draining when descendants hold stdout open. Define bounded cleanup behavior without losing summaries.
- Test zero/unlimited suite timeout and positive timeout/cancellation behavior; document CLI semantics.
- Keep each change independently reviewable. Use the Kirk repository for the eventual implementation PR; this LTP branch is a durable handoff location.

Earlier local runtime evidence: Obsidian nommu-swmmu/Codex-Logs/2026-10-23_150508+0900-review-followup/review-notes.md. The full LTP runs include unrelated FAIL/BROK/WARN and do not prove these patches correct.
