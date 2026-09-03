# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Answer "did anyone use it, and did it work for them" from the event log.

    python tools/fcweb-events.py <events.log>
    python tools/fcweb-events.py --ssh                 # pull from production first
    python tools/fcweb-events.py <events.log> --days 3

The collection side of this has worked since 2026-08-16 and nobody could read it. nginx
appends one line per beacon to /var/log/fcweb/events.log inside the freecad container, and
answering "how many people hit a crash yesterday" meant an SSH session, a grep, and some
counting. So it never got asked.

WHAT THE NUMBERS MEAN

The app sends enumerated events and nothing else -- no identifier, no cookie, no document
name, no free text, no session id. That is a deliberate limit and it shapes what can be
said here:

  * a "session" is one boot_start. Two visits from one person are two sessions, and there
    is no way to tell that from two people.
  * boot_start minus boot_ready is the number of boots that never finished. That is the
    single most important number in the file, because a user who never reaches Ready sees
    a loading screen and leaves, and nothing else in this project would notice.
  * crash and abort are counted by their enumerated kind. There is no stack, by design;
    the kind is enough to tell "the wasm aborted" from "a script threw".

WHAT IT CANNOT TELL YOU

Who. Nothing here identifies a person, and the server does not log IPs. It also cannot
tell a real user from a CI run against production -- the gate boots the live site, and
those boots are in this file too. --exclude-headless drops the obvious ones by user agent,
which is a heuristic and is labelled as one.
"""
import argparse
import collections
import io
import os
import re
import subprocess
import sys
import urllib.parse

LINE = re.compile(
    r'^(?P<ts>\S+)\s+e=(?P<e>\S*)\s+k=(?P<k>\S*)\s+ms=(?P<ms>\S*)\s+b=(?P<b>\S*)\s+ua=(?P<ua>.*)$')

# The box, and the key that reaches it. Both overridable, because hardcoding one person's
# key path is how a tool becomes "works on my machine".
#
# The origin address is deliberately NOT in the tree. Cloudflare proxies the hostname
# precisely so the origin stays private, and this repository is public -- a literal here
# would hand anyone a way around the proxy. See AGENTS.md, "Repository rules"; CI enforces
# it in the `hygiene` job. Set FCWEB_SSH_HOST (the ORIGIN_IP repository variable holds the
# same value for CI and Terraform), or pass --host.
SSH_HOST = os.environ.get('FCWEB_SSH_HOST', '')
SSH_KEY = '~/Documents/SSH/ovh_nostalgia'
REMOTE_LOG = 'docker exec freecad cat /var/log/fcweb/events.log'


def ssh_cmd(key, host):
    cmd = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20']
    if key:
        cmd += ['-i', os.path.expanduser(key)]
    return cmd + [host, REMOTE_LOG]


def parse(path):
    rows = []
    for raw in io.open(path, encoding='utf-8', errors='replace'):
        m = LINE.match(raw.strip())
        if not m:
            continue
        d = m.groupdict()
        d['day'] = d['ts'][:10]
        d['build'] = urllib.parse.unquote(d['b'])
        d['ms'] = int(d['ms']) if d['ms'].isdigit() else None
        rows.append(d)
    return rows


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p / 100.0))]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('logfile', nargs='?', default=None)
    ap.add_argument('--ssh', action='store_true',
                    help='pull the log from production first')
    ap.add_argument('--host', default=SSH_HOST,
                    help='ssh destination for --ssh, e.g. user@host. '
                         'Defaults to $FCWEB_SSH_HOST.')
    ap.add_argument('--key', default=SSH_KEY,
                    help='ssh identity for the box (default: %(default)s)')
    ap.add_argument('--days', type=int, default=0, help='only the last N days')
    ap.add_argument('--exclude-headless', action='store_true',
                    help='drop user agents that look like CI. A heuristic, not a fact.')
    args = ap.parse_args()

    path = args.logfile
    if args.ssh:
        # Fail with the fix rather than with an ssh error about an empty destination.
        if not args.host:
            raise SystemExit(
                '--ssh needs the origin address, which is deliberately not in the tree.\n'
                'Set it for this shell:  export FCWEB_SSH_HOST=ubuntu@<origin-ipv4>\n'
                'or pass it directly:    --host ubuntu@<origin-ipv4>\n'
                'The value is the ORIGIN_IP repository variable '
                '(gh variable get ORIGIN_IP --repo Virtastic/freecad-web).')
        path = path or 'events.log'
        try:
            data = subprocess.check_output(ssh_cmd(args.key, args.host),
                                           stderr=subprocess.PIPE)
        except subprocess.CalledProcessError as e:
            raise SystemExit('could not read the log from %s: %s'
                             % (args.host, e.stderr.decode('utf-8', 'replace').strip()))
        except FileNotFoundError:
            raise SystemExit('no ssh on PATH')
        with io.open(path, 'wb') as fh:
            fh.write(data)
        print('pulled %d bytes from %s to %s' % (len(data), args.host, path))
    if not path:
        raise SystemExit('give a log file, or --ssh to fetch one')

    rows = parse(path)
    if args.exclude_headless:
        before = len(rows)
        rows = [r for r in rows
                if not any(x in r['ua'] for x in ('HeadlessChrome', 'Puppeteer', 'bot'))]
        print('dropped %d event(s) whose user agent looks automated' % (before - len(rows)))
    if args.days:
        days = sorted({r['day'] for r in rows})[-args.days:]
        rows = [r for r in rows if r['day'] in days]
    if not rows:
        print('no events'); return 0

    days = sorted({r['day'] for r in rows})
    print('%d events, %s to %s' % (len(rows), days[0], days[-1]))
    print()

    # The headline: did it work for the people who showed up?
    starts = [r for r in rows if r['e'] == 'boot_start']
    readys = [r for r in rows if r['e'] == 'boot_ready']
    crashes = [r for r in rows if r['e'] in ('crash', 'abort')]
    never = len(starts) - len(readys)
    print('sessions (boot_start)        %d' % len(starts))
    print('reached Ready               %d' % len(readys))
    if starts:
        print('NEVER reached Ready         %d  (%.0f%% of sessions)'
              % (never, 100.0 * never / len(starts)))
    print('crash + abort events         %d' % len(crashes))
    if crashes:
        for k, n in collections.Counter(
                '%s/%s' % (r['e'], r['k']) for r in crashes).most_common():
            print('    %-28s %d' % (k, n))
    print()

    times = [r['ms'] for r in readys if r['ms']]
    if times:
        print('time to Ready   p50 %.1fs   p90 %.1fs   worst %.1fs'
              % (pct(times, 50) / 1000.0, pct(times, 90) / 1000.0, max(times) / 1000.0))
        print()

    print('by day:')
    print('    %-12s %8s %8s %8s' % ('day', 'starts', 'ready', 'crash'))
    for d in days:
        ds = [r for r in rows if r['day'] == d]
        print('    %-12s %8d %8d %8d'
              % (d,
                 sum(1 for r in ds if r['e'] == 'boot_start'),
                 sum(1 for r in ds if r['e'] == 'boot_ready'),
                 sum(1 for r in ds if r['e'] in ('crash', 'abort'))))
    print()

    # Per build, because the aggregate lies. The first run of this reported "23% of
    # sessions never reached Ready", which reads like a live problem -- and almost all of
    # it was one pre-port build that has not been deployed for days. A rate is only
    # meaningful next to the thing it is a rate OF.
    print('by build (worst first):')
    per = []
    for b, n in collections.Counter(r['build'] for r in starts).items():
        b_ready = sum(1 for r in readys if r['build'] == b)
        per.append((1.0 - (float(b_ready) / n), b, n, b_ready))
    for rate, b, n, b_ready in sorted(per, reverse=True):
        flag = '   <-- ' if rate >= 0.2 and n >= 3 else '       '
        print('    %-42s %3d starts, %3d ready  %3.0f%% lost%s'
              % (b[:42], n, b_ready, rate * 100, flag))

    # Say the thing out loud rather than leaving it in a table.
    if starts and never > 0:
        print()
        print('NOTE: %d boot(s) started and never reported Ready. Each of those is someone '
              'watching a loading screen. Nothing else in this project can see them.' % never)
    return 0


if __name__ == '__main__':
    sys.exit(main())
