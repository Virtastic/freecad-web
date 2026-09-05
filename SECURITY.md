# Security policy

## Supported

Only the latest release (the one served at <https://freecad.virtastic.app>) is supported.
Older tagged builds receive no fixes.

## Reporting a vulnerability

Do not open a public issue. Report privately via
[GitHub private vulnerability reporting](https://github.com/Virtastic/freecad-web/security/advisories/new)
or by email to <michael@stavridis.xyz>.

Include what you found, how to reproduce it, and what you think the impact is. You will get
an acknowledgement within 7 days and a fix or a decision within 90.

## Scope

In scope: this repository's own code (`play-gui/`, `tools/`, `infra/`, the CI workflows) and
the deployed site. Out of scope: vulnerabilities in upstream FreeCAD, OCCT, Qt or Emscripten,
which should go to those projects. The application runs entirely in the browser sandbox and
stores nothing server-side, so issues are most likely in the front-end shell or the deploy
infrastructure.
