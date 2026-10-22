# NOMMU UML validation kit

This kit contains the NOMMU UML runtime workflow, host and guest Kirk runners,
the Alpine/musl build helper, and the setup and usage notes for validating the
`hajime/nommu-runtime-upstream` branch.

These runtime validation files are kept outside the upstream LTP branch. The
upstream branch uses the project's normal build CI only. To run the runtime
validation separately, copy the `.github` and `ci` contents into a full clone
of the branch and follow `ci/nommu-uml-testing.md`.
