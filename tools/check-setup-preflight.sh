#!/bin/sh
# SPDX-License-Identifier: LGPL-2.1-or-later
# Copyright (c) Virtastic
#
#     sh tools/check-setup-preflight.sh ./setup.sh
#
# Exercises every FATAL branch of setup.sh's Docker preflight without touching the real
# daemon, by putting a fake `docker` in front of it on PATH. Each case asserts BOTH that
# the script exits non-zero AND that the message is the specific one for that fault --
# a preflight that fails for the wrong reason is not a working preflight.
set -u

SETUP="${1:?usage: preflight-cases.sh /path/to/setup.sh}"
FAKE=$(mktemp -d)
trap 'rm -rf "$FAKE"' EXIT
pass=0; fail=0

# A PATH with every real docker/docker-compose removed, but sh/grep/awk/df intact --
# otherwise "docker is absent" also removes the interpreter and proves nothing.
CLEAN=""
IFS=:
for d in $PATH; do
    [ -n "$d" ] || continue
    [ -x "$d/docker" ] || [ -x "$d/docker.exe" ] && continue
    [ -x "$d/docker-compose" ] || [ -x "$d/docker-compose.exe" ] && continue
    CLEAN="${CLEAN:+$CLEAN:}$d"
done
unset IFS
command -v docker >/dev/null 2>&1 && PATH="$CLEAN" command -v docker >/dev/null 2>&1 && {
    echo "harness broken: docker still reachable on the cleaned PATH"; exit 1; }

mkfake() { # $1 = server version (or DEAD), $2 = ostype, $3 = compose (ok|missing)
    rm -f "$FAKE/docker" "$FAKE/docker-compose"
    cat > "$FAKE/docker" <<EOF
#!/bin/sh
case "\$1" in
  info)    [ "$1" = "DEAD" ] && exit 1; printf '%s|%s|/var/lib/docker\n' "$1" "$2" ;;
  compose) [ "$3" = "missing" ] && exit 1; echo "v2.29.0" ;;
  *)       exit 0 ;;
esac
EOF
    chmod +x "$FAKE/docker"
}

check() { # $1 = label, $2 = expected substring
    label="$1"; want="$2"
    out=$(PATH="$FAKE:$CLEAN" sh "$SETUP" 2>&1); rc=$?
    report "$label" "$want" "$rc" "$out"
}

report() {
    label="$1"; want="$2"; rc="$3"; out="$4"
    if [ "$rc" -eq 0 ]; then
        printf '  FAIL  %-26s exited 0; a fault must be fatal\n' "$label"; fail=$((fail+1)); return
    fi
    if printf '%s' "$out" | grep -qF "$want"; then
        printf '  ok    %-26s rc=%s  "%s"\n' "$label" "$rc" "$want"; pass=$((pass+1))
    else
        printf '  FAIL  %-26s rc=%s  wanted "%s", got:\n' "$label" "$rc" "$want"
        printf '%s\n' "$out" | sed 's/^/          /' | head -6
        fail=$((fail+1))
    fi
}

out=$(PATH="$CLEAN" sh "$SETUP" 2>&1); rc=$?
report "docker absent" "Docker is not installed" "$rc" "$out"

mkfake DEAD linux ok
check "daemon unreachable"     "daemon is not reachable"

mkfake 19.03.15 linux ok
check "engine too old"         "20.10 or newer is required"

mkfake 27.1.1 windows ok
check "windows container mode" "Windows container mode"

# Compose plugin gone and no v1 fallback present.
mkfake 27.1.1 linux missing
check "compose v2 missing"     "Compose V2 plugin is missing"

# Compose plugin gone but legacy docker-compose IS installed: different fix, so it must
# be a different message.
mkfake 27.1.1 linux missing
printf '#!/bin/sh\necho 1.29.2\n' > "$FAKE/docker-compose"; chmod +x "$FAKE/docker-compose"
check "legacy compose v1"      "a space, not a hyphen"

printf '\n  %d passed, %d failed\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
