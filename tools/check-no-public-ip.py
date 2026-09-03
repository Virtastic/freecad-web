#!/usr/bin/env python3
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
"""Refuse to ship a tracked file containing a routable IPv4 literal.

This replaces a grep for one hardcoded address. That grep was written after the OVH
origin leaked into the tree, and it did its job for that address -- while
`ci/jenkins/README.md` sat in HEAD carrying the *dev* origin's public IP, which the grep
had never been told about. A gate that only knows the addresses somebody remembered is
not a gate; it is a record of past incidents.

The rule this enforces (AGENTS.md, "Repository rules"): Cloudflare proxies the hostname
precisely so the origin stays private. An origin address in a public repository hands
anyone a route straight past the proxy -- past its TLS termination, its rate limiting and
its DDoS absorption -- to a box whose firewall is now the only thing left.

Private addresses are allowed: RFC1918 topology is meaningless without access to the
network, and this repository documents its LAN deliberately.

    python3 tools/check-no-public-ip.py
"""
import re
import subprocess
import sys

IPV4 = re.compile(r'(?<![\w.])((?:\d{1,3}\.){3}\d{1,3})(?![\w.])')

# Public resolvers, deliberately configured in infra/nginx.conf for the /proxy/ upstreams.
ALLOWED = {'1.1.1.1', '1.0.0.1', '8.8.8.8', '8.8.4.4', '9.9.9.9'}


def is_private(ip):
    """RFC1918 and the other non-routable ranges, plus anything that is not a real IP."""
    try:
        parts = [int(p) for p in ip.split('.')]
    except ValueError:
        return True
    if len(parts) != 4 or any(p > 255 for p in parts):
        return True                      # a version number, not an address
    a, b = parts[0], parts[1]
    return (
        a == 10                          # RFC1918
        or (a == 172 and 16 <= b <= 31)  # RFC1918
        or (a == 192 and b == 168)       # RFC1918
        or a == 127                      # loopback
        or (a == 169 and b == 254)       # link-local
        or a == 0 or a >= 224            # unspecified, multicast, reserved, broadcast
        or (a == 100 and 64 <= b <= 127)  # CGNAT
        or (a == 192 and b == 0)         # 192.0.0.0/24, 192.0.2.0/24 (TEST-NET-1)
        or (a == 198 and b in (18, 19, 51))
        or (a == 203 and b == 0)         # TEST-NET-3
    )


def main():
    files = subprocess.run(['git', 'ls-files'], capture_output=True, text=True,
                           check=True).stdout.split('\n')
    hits = []
    for path in filter(None, files):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                for lineno, line in enumerate(fh, 1):
                    for ip in IPV4.findall(line):
                        if ip in ALLOWED or is_private(ip):
                            continue
                        hits.append((path, lineno, ip, line.strip()[:100]))
        except (OSError, UnicodeError):
            continue

    if hits:
        for path, lineno, ip, text in hits:
            print('::error file=%s,line=%d::routable IP %s in a tracked file -- origin '
                  'addresses belong in the ORIGIN_IP repository variable, not the tree'
                  % (path, lineno, ip))
            print('  %s:%d  %s' % (path, lineno, text))
        print('\n%d routable IPv4 literal(s) in tracked files.' % len(hits))
        print('If one is genuinely public infrastructure that is safe to name, add it to '
              'ALLOWED in this script with a comment saying why.')
        return 1

    print('  ok    no routable IPv4 literals in tracked files')
    return 0


if __name__ == '__main__':
    sys.exit(main())
