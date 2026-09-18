<!-- SPDX-License-Identifier: LGPL-2.1-or-later -->
<!-- Copyright (c) Virtastic -->

# Shared sessions, and an AI assistant over MCP

Send someone a link and they open **your document in your environment** — your add-ons,
your units, your theme — with nothing installed. If you are both there at once they watch
you work; if they open it three days later it is still exactly as you left it. The same
session can be handed to an AI assistant over MCP, which sees what you see and edits
alongside you while everyone watches.

The Virtastic sites run this. On any other install it is optional: nothing about sharing
reaches a server unless an operator starts the container, and until you start a session
nothing of yours leaves your browser either.

---

## For the operator: turning it on

One extra container, behind a compose profile:

```bash
docker compose --profile share up -d
```

That is the whole setup. nginx proxies `/share/`, `/api/` and `/mcp/` to it on the same
origin, so cross-origin isolation (which the WebAssembly build needs) is unaffected.
Without the container the feature is *inert, not broken*: the app runs exactly as before
and the Sharing page says the service is not running.

| Setting | Default | What it does |
|---|---|---|
| `FCWEB_SHARE_MAX_MB` | 25 | Largest document a session may hold |
| `FCWEB_SHARE_MAX_GB` | 5 | Total volume before the least recently viewed session with no expiry is evicted. A session opened in the last day is never evicted, and a session that never published anything is dropped after an hour. When nothing may be evicted the write is refused instead. |
| `FCWEB_PUBLIC_URL` | — | The origin used in links. Set it on any origin behind a proxy. Unset, each request's own host is used, which is right for a plain `docker compose up` and wrong almost everywhere else. |

Sessions live in one Docker volume as plain files — `<id>.fcstd`, `<id>.env.json`,
`<id>.json`. To see them:

```bash
docker compose exec session python /srv/share.py --list
docker compose exec session python /srv/share.py --stats
```

**Documents on that volume are not encrypted.** Anyone with access to the server can read
them. Passwords and the MCP token are stored only as hashes.

---

## Sharing a document

**Edit → Share Session…** opens Preferences on **Sharing → General**. Press **Start
sharing**. Sharing begins immediately — you do not need to press OK — and the page then
shows *Sharing …* with the link and a **Copy** button beside it.

**Preferences → Sharing** has three pages: **General** (start and stop, your name, the
link, passwords, expiry), **Session** (who is here, who is editing, and the actions --
Request, Take, Release, Grant, Deny, Remove from session, Copy link, Download, Diagnostics,
Stop sharing) and **MCP** (the AI link). The Session page is the live surface: who is
editing, how many others are here, and whether contact was lost. **Refresh** reads the
state again; it also repaints itself whenever you press one of its buttons.

**What travels:** the document, your full `user.cfg` (units, decimals, theme, navigation,
toolbars), your macros, and your add-ons. A visitor gets your working environment, not a
generic FreeCAD. Untick *Include my settings, add-ons and macros* to send only the
document.

**What does not travel:** your other documents, your own home directory, and anything in
the Sharing settings — the write key, the passwords and the MCP link are stripped from the
published bundle, and that stripping is asserted, not merely intended.

### Who can open it

| | |
|---|---|
| **No password** | Anyone with the link can view |
| **Viewer password** | Needed to open the session at all |
| **Editor password** | Needed to *take* control without asking |

Anyone in a session may **ask** for control — the person holding it gets Grant / Deny.
The editor password is what lets someone take it without asking, or claim it when nobody
is holding it.

Watchers are genuinely read-only, and they can see that before they try: the editing
commands are **greyed out** while someone else holds control, and every mirrored document
is locked property by property. Anything that slips through is undone in place.

Set a password by typing it and pressing OK; the field shows `set ✓` afterwards and never
shows the password again. **Clear** removes one. Only the field you touched is sent, so
setting one password never clears the other.

### Expiry and stopping

*Link expires* is **Never** by default — an emailed link should still work next week. 7,
30 and 90 days are offered; the date is fixed when you choose it, so reopening the dialog
does not restart the countdown. **Stop sharing** ends it for everyone at once.

If the server evicts a session for space, the owner is told the next time they share that
document, never silently.

---

## Opening someone's link

Click it. The loading screen asks your name, the password if there is one, and — if the
session carries add-ons — whether to install them:

> This session uses 2 add-ons (Curves, Assembly4). They will be installed into a temporary
> workspace that disappears when you close this tab.
> **[Continue with add-ons]** **[Open without them]**

Declining still opens the document: the geometry is in the file either way, and only the
parametric editability of add-on objects is lost. A shared link never runs third-party
code without a click.

Everything lands in a **temporary home that disappears when you close the tab**. Your own
documents and settings are never touched, and the session cannot see them.

A first visit downloads the ~88 MB engine; returning visits start in seconds. **Download
.FCStd** on the Session page keeps a copy.

---

## Letting an AI assistant in

**Edit → Share Session… → MCP**, press **Enable assistant**. The assistant works inside a
session, so if you have not started one this starts it for you. A link is minted a moment
later.

For a command-line client, do not retype it. **Copy Claude Code command** and **Copy Codex
command** put the whole thing on the clipboard, already carrying your link:

```bash
claude mcp remove freecad
claude mcp add --transport http freecad <your link>
```

Each button copies **two lines**, a remove followed by an add, because both clients refuse a
name that already exists and the common case is not a first install but a link that changed.
Paste both into a terminal. The Codex form is `codex mcp remove freecad` then
`codex mcp add freecad --url <your link>`.

In Claude Desktop: **Settings → Connectors → add a custom connector** and paste the link
itself. There is nothing else to configure — the link carries the session and the
capability.

**Regenerate** makes a new link and the old one stops working immediately. Press the copy
button again and paste: the remove line is what lets the new one take its place.

### What the assistant can do

Everything the application can. `fc_eval` runs any FreeCAD Python, `fc_run_command` drives
all 459 GUI commands, and there are 39 typed tools on top for ease — the object tree,
every property, selection, views, export, the report view. `fc_screenshot` returns a real
image, so it can look at its own work.

It is a visible participant: it must hold control to change anything, every change is
published as it lands, and each one carries a one-line note that everyone watching reads
("added a 3 mm fillet to the top edges").

Ask it for the `freecad-quickstart` prompt for worked examples, including a print-ready
STL export.

### What it cannot do

- **Work without a tab.** The assistant acts inside *your* open FreeCAD tab; close the
  tab and it answers `no_tab` with that explanation. There is no headless mode.
- **Edit while someone else holds control.** It gets `not_holder` and a hint to ask.
- **Install an add-on without a human click.**
- **Be interrupted mid-`fc_eval`.** A runaway loop can only be ended by reloading the page.
- **Hand you a file by itself** — exports download in *your* browser, and the assistant
  gets only the name, size and hash.

### Be clear about what you are opening

`fc_eval` is arbitrary code execution inside your live FreeCAD tab, with your documents
and your environment. That is what the tick box opts into, and the page says so. The link
is a password: anyone holding it has the same reach. It is off by default, a closed
endpoint answers `404` rather than `401`, and the token is stored hashed.

---

## When something goes wrong

Every failure names its next step, in the app and over MCP alike. **Diagnostics** on the
Session page shows the last 200 session events with timestamps and request ids, and **Copy for bug
report** redacts the token and passwords first.

| What you see | What it means |
|---|---|
| *Sharing is not available on this site* | The operator has not started the session container |
| *Lost contact (HTTP 502) — retrying* | The service went away; the page keeps trying and recovers on its own |
| *This session has ended* | The owner stopped it, or it expired. The document stays open and Download still works |
| *This session is read-only for you* | You are not holding control — the toast offers *Request control* |
| `no_tab` over MCP | The owner's FreeCAD tab is closed |

---

## What this is not

- **Not concurrent editing.** One person holds control at a time; turn-taking makes
  conflicting edits impossible rather than merging them.
- **Not screen sharing.** Watchers see the documents and every change to them, but keep
  their own viewpoint -- being pulled to someone else's camera mid-inspection is worse
  than useful. Selections, dialogs and a sketch in progress do not travel either.
- **Not one file.** Every document you have open is mirrored, so the tabs along the
  bottom of a watcher's window are your tabs, and a file you open mid-session appears
  for them too. An edit in any of them reaches the audience in a few seconds, and the tabs
  you are not touching are left alone while it does.
- **No version history.** A link shows the current state.
- **No accounts.** Names are self-declared, and the activity log says so.
- **Not a ban.** Removing someone ends that tab's session, but the link still works and a
  reload lets them back in. To actually shut someone out, set or change the viewer password,
  or stop sharing.
