#!/usr/bin/env bash
# Only the image's internal -uroot probes may fall back to the initial empty
# password, and only on authentication failure (never retry an executed SQL).
set -uo pipefail
internal=false
for argument in "$@"; do
  [ "$argument" != -uroot ] || internal=true
  case "$argument" in --defaults*|-p*|--password*|--user*|-u) exec /usr/bin/mysql "$@" ;; esac
  [[ "$argument" != -u* || "$argument" = -uroot ]] || exec /usr/bin/mysql "$@"
done
if [ "$internal" != true ] || [ -z "${MYSQL_PWD:-}" ]; then exec /usr/bin/mysql "$@"; fi
diagnostic=$(mktemp /tmp/dsl-mysql-auth.XXXXXXXX)
trap 'rm -f -- "$diagnostic"' EXIT
result=$(/usr/bin/mysql "$@" 2>"$diagnostic")
status=$?
if [ "$status" = 0 ]; then
  [ -z "$result" ] || printf '%s\n' "$result"
  exit 0
fi
if [ -z "$result" ] && grep -qE '^ERROR 1045 \(28000\): Access denied' "$diagnostic"; then
  env -u MYSQL_PWD /usr/bin/mysql --no-defaults "$@"
  exit $?
fi
[ -z "$result" ] || printf '%s\n' "$result"
while IFS= read -r line; do printf '%s\n' "$line" >&2; done <"$diagnostic"
exit "$status"
