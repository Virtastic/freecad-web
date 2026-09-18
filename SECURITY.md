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

In scope: this repository's own code (`play-gui/`, `tools/`, `infra/` including
`infra/session/`, the CI workflows) and the deployed sites. Out of scope: vulnerabilities in
upstream FreeCAD, OCCT, Qt or Emscripten, which should go to those projects.

Your documents are still opened, edited and rendered inside the browser sandbox. The one
exception is a session you deliberately share: the optional session service then holds a copy
of those documents on the server, **unencrypted**, so that a link keeps working after you
close your laptop. Anyone holding the link can read them, as can whoever runs the server.
Passwords and the assistant token are stored only as hashes, never in the clear.

## By design, and not a vulnerability

These are choices, documented in `SHARING.md`, and a report that only restates them will be
closed as such:

- **The assistant runs code.** With the AI assistant switched on, `fc_eval` and
  `fc_run_command` execute arbitrary Python and any FreeCAD command inside the owner's own
  tab, with that tab's rights. That is the feature. It is off until someone presses Enable,
  it needs a capability URL that answers `404` when closed, and the token is stored hashed.
- **A share link is a bearer capability.** Whoever holds it gets what it grants. Passwords
  narrow that; the link itself is the secret.
- **Session storage is unencrypted** and, by default, has no expiry date.
- **Removing someone from a session is not a ban.** They can rejoin with the link. Rotating
  the viewer password or stopping the session is what actually removes them.

What we do want to hear about: reaching a tab that never enabled the assistant, a closed
endpoint answering anything other than `404`, a viewer escalating to editor without the
editor password, one session reading another's documents, a token or password appearing in a
log, or any way to make the server hand out data to someone who never had the link.
