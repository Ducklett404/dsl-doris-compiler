"""Selective FE identity. Never return a full command line or process environment.

The CPU option is verified from the JVM process's inherited options and command
line, not via JMX/NMT. This is configuration evidence, not an arena-count claim.
"""
import re
import subprocess

PROFILE_PATH = '/run/dsl-fe-runtime-profile'
FE_CONF = '/opt/apache-doris/fe/conf/fe.conf'
ENTRYPOINT = '/run/dsl-entrypoint.sh'
PROCESS_PROBE = r'''
set -eu
set -- $(pidof java)
[ "$#" -eq 1 ] || exit 45
case "$1" in *[!0-9]*|'') exit 46;; esac
pid=$1
tr '\000' '\n' < "/proc/$pid/environ" | awk '
  /^MALLOC_ARENA_MAX=/ { if ($0 == "MALLOC_ARENA_MAX=4") print $0; else print "INVALID_ENV" }
  /^JAVA_TOOL_OPTIONS=/ { if ($0 == "JAVA_TOOL_OPTIONS=-XX:ActiveProcessorCount=4") print "jvmEnvironmentCpu=4"; else print "INVALID_ENV" }
  /^(_JAVA_OPTIONS|JDK_JAVA_OPTIONS|GLIBC_TUNABLES)=./ { print "INVALID_ENV" }
'
tr '\000' '\n' < "/proc/$pid/cmdline" | awk '
  /^-Xms/ { if ($0 ~ /^-Xms[0-9]+m$/) { sub(/^-Xms/, ""); sub(/m$/, ""); print "heapInitialMiB=" $0 } else print "INVALID_HEAP" }
  /^-Xmx/ { if ($0 ~ /^-Xmx[0-9]+m$/) { sub(/^-Xmx/, ""); sub(/m$/, ""); print "heapMaxMiB=" $0 } else print "INVALID_HEAP" }
  /^-XX:ActiveProcessorCount=/ { if ($0 ~ /^-XX:ActiveProcessorCount=[0-9]+$/) { sub(/^-XX:ActiveProcessorCount=/, ""); print "jvmCommandCpu=" $0 } else print "INVALID_CPU" }
'
'''


def parse_process(text):
    fields = {}
    allowed = {'MALLOC_ARENA_MAX', 'jvmEnvironmentCpu', 'jvmCommandCpu', 'heapInitialMiB', 'heapMaxMiB'}
    for line in text.splitlines():
        key, separator, value = line.partition('=')
        if not separator or key not in allowed or key in fields or re.fullmatch(r'[1-9][0-9]*', value) is None:
            raise ValueError('Malformed or unreviewed FE process runtime identity')
        fields[key] = int(value)
    if set(fields) & {'heapInitialMiB', 'heapMaxMiB'} != {'heapInitialMiB', 'heapMaxMiB'}:
        raise ValueError('FE heap configuration is incomplete')
    if fields['heapInitialMiB'] > fields['heapMaxMiB']:
        raise ValueError('FE heap bounds are reversed')
    environment_cpu = fields.get('jvmEnvironmentCpu')
    command_cpu = fields.get('jvmCommandCpu')
    if environment_cpu not in (None, 4) or command_cpu not in (None, 4):
        raise ValueError('Unreviewed or conflicting FE JVM CPU option')
    if fields.get('MALLOC_ARENA_MAX') not in (None, 4):
        raise ValueError('Unreviewed FE allocator arena limit')
    return dict(mallocArenaMax=fields.get('MALLOC_ARENA_MAX'),
                activeProcessorCount=command_cpu or environment_cpu,
                heapInitialMiB=fields['heapInitialMiB'], heapMaxMiB=fields['heapMaxMiB'])


def parse_hashes(text):
    hashes = {}
    for line in text.splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  (/[^\r\n]+)', line)
        if match is None or match[2] not in (FE_CONF, ENTRYPOINT) or match[2] in hashes:
            raise ValueError('Malformed or incomplete FE runtime configuration fingerprints')
        hashes[match[2]] = match[1]
    if set(hashes) != {FE_CONF, ENTRYPOINT}:
        raise ValueError('Missing FE runtime configuration fingerprint')
    return dict(feConfigurationSha256=hashes[FE_CONF], entrypointSha256=hashes[ENTRYPOINT])


def capture_fe_runtime(client):
    def run(arguments):
        result = subprocess.run(client.prefix + arguments, capture_output=True, timeout=20)
        if result.returncode:
            raise RuntimeError('Selective FE identity command failed (exit ' + str(result.returncode) + ')')
        return result.stdout.decode('utf-8', errors='strict')
    profile = run(['exec', 'dsl-doris-official', 'sh', '-c',
        'if test -L "$1"; then exit 45; elif test -e "$1"; then '
        'test -f "$1" || exit 46; cat -- "$1"; else printf "disabled-v1\\n"; fi',
        'dsl-fe-profile-identity', PROFILE_PATH])
    if re.fullmatch(r'(bounded-v1|disabled-v1)(?:\r?\n)?', profile) is None:
        raise ValueError('Unreviewed FE runtime profile')
    process = parse_process(run(['exec', 'dsl-doris-official', 'sh', '-c', PROCESS_PROBE,
                                 'dsl-fe-runtime-identity']))
    enabled = profile.rstrip('\r\n') == 'bounded-v1'
    if (process['mallocArenaMax'], process['activeProcessorCount']) != ((4, 4) if enabled else (None, None)):
        raise ValueError('FE private profile and running process options differ; restart or rollback is incomplete')
    fingerprints = parse_hashes(run(['exec', 'dsl-doris-official', 'sha256sum', FE_CONF, ENTRYPOINT]))
    return dict(profile=profile.rstrip('\r\n'), **process, **fingerprints)
