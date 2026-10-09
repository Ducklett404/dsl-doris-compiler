"""Selective, fail-closed process fingerprints; no live runtime required."""
import os
from pathlib import Path
import re
import shutil
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import project_fe_runtime as runtime


class FeRuntimeIdentityTest(unittest.TestCase):
    OVERRIDE_OPTIONS = ('_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'GLIBC_TUNABLES')

    def bounded_fe_branch(self):
        text = (Path(__file__).parent / 'wsl-doris-entrypoint.sh').read_text(encoding='utf-8')
        fe = text.split('# DSL_FE_BOUNDED_RUNTIME_PROFILE_V1', 1)[1]
        branch = re.search(r'^  bounded-v1\)\n(.*?)^    ;;$', fe, re.M | re.S)
        self.assertIsNotNone(branch, 'Expected one independently reviewed FE bounded branch')
        return branch[1]

    def override_probe_rule(self):
        rule = re.search(
            r'^\s*/(\^\(_JAVA_OPTIONS\|JDK_JAVA_OPTIONS\|GLIBC_TUNABLES\)=\.)/\s*'
            r'\{\s*print "INVALID_ENV"\s*\}\s*$', runtime.PROCESS_PROBE, re.M)
        self.assertIsNotNone(rule, 'Override probe must emit only the fixed rejection sentinel')
        return rule[1], '/' + rule[1] + '/ { print "INVALID_ENV" }'

    def test_environment_override_guards_precede_exports_in_bounded_branch(self):
        branch = self.bounded_fe_branch()
        first_export = branch.index('export MALLOC_ARENA_MAX=4')
        self.assertLess(first_export, branch.index("export JAVA_TOOL_OPTIONS='-XX:ActiveProcessorCount=4'"))
        chain = ' && '.join('[ -z "${' + option + ':-}" ]' for option in self.OVERRIDE_OPTIONS)
        guard = re.search(re.escape(chain) + r'\s*\|\|\s*\{[^\n]*exit 1;\s*\}', branch)
        self.assertIsNotNone(guard, 'All three options must fail closed in one guard, not standalone tests')
        self.assertLess(guard.end(), first_export)

    def test_environment_probe_rejects_nonempty_values_without_revealing_them(self):
        pattern, rule = self.override_probe_rule()
        self.assertNotIn('$0', rule)
        for option in self.OVERRIDE_OPTIONS:
            for value in ('', 'private-test-value', ' ', '-XX:ActiveProcessorCount=8'):
                with self.subTest(option=option, valueEmpty=not value):
                    line = option + '=' + value
                    emitted = 'INVALID_ENV\n' if re.search(pattern, line) else ''
                    self.assertEqual(emitted, 'INVALID_ENV\n' if value else '')
                    self.assertNotIn('private-test-value', emitted)
        for line in ('UNRELATED=private-test-value', '_JAVA_OPTIONS_SUFFIX=x', 'JDK_JAVA_OPTIONS_X=x'):
            with self.subTest(nearMatch=line):
                self.assertIsNone(re.search(pattern, line))

    def test_override_sentinel_rejects_capture_without_secret_error_text(self):
        client = SimpleNamespace(prefix=['owned-docker'])
        base = b'MALLOC_ARENA_MAX=4\njvmEnvironmentCpu=4\nheapInitialMiB=768\nheapMaxMiB=768\n'
        pattern, _ = self.override_probe_rule()
        for option in self.OVERRIDE_OPTIONS:
            with self.subTest(option=option):
                self.assertIsNotNone(re.search(pattern, option + '=private-test-value'))
                outputs = [b'bounded-v1\n', base + b'INVALID_ENV\n']
                with patch.object(runtime.subprocess, 'run', side_effect=[
                        SimpleNamespace(returncode=0, stdout=value) for value in outputs]) as call:
                    with self.assertRaises(ValueError) as raised:
                        runtime.capture_fe_runtime(client)
                self.assertEqual(len(call.call_args_list), 2, 'Invalid process must fail before fingerprint acceptance')
                self.assertNotIn('private-test-value', str(raised.exception))

    @unittest.skipUnless(os.name == 'posix' and shutil.which('bash') and shutil.which('awk'),
                         'Real Linux guard test requires POSIX bash and awk; Windows structural tests remain active')
    def test_real_linux_guard_and_awk_nonempty_rejection_empty_acceptance(self):
        # Execute only the isolated reviewed branch/rule, not the entrypoint,
        # /proc probes or any inherited private environment/database command.
        branch = self.bounded_fe_branch()
        _, rule = self.override_probe_rule()
        clean_environment = dict(PATH=os.defpath, MALLOC_ARENA_MAX='', JAVA_TOOL_OPTIONS='',
                                 **{option: '' for option in self.OVERRIDE_OPTIONS})
        # Use valid option syntax: an invalid GLIBC_TUNABLES value is echoed by
        # ld.so before bash can execute any guard, independently of our script.
        overrides = dict(_JAVA_OPTIONS='-XX:ActiveProcessorCount=8',
                         JDK_JAVA_OPTIONS='-XX:ActiveProcessorCount=8',
                         GLIBC_TUNABLES='glibc.malloc.arena_max=8')
        for option in self.OVERRIDE_OPTIONS:
            for value in ('', overrides[option]):
                with self.subTest(option=option, valueEmpty=not value):
                    process = subprocess.run(['bash', '-c', 'set -euo pipefail\n' + branch + '\nprintf "GUARD_PASS\\n"'],
                        env=dict(clean_environment, **{option: value}), capture_output=True, text=True, timeout=10)
                    self.assertEqual(process.returncode, 1 if value else 0)
                    self.assertEqual(process.stdout, '' if value else 'GUARD_PASS\n')
                    if value:
                        self.assertNotIn(value, process.stdout + process.stderr)
                    selected = subprocess.run(['awk', rule], input=option + '=' + value + '\n',
                        env=clean_environment, capture_output=True, text=True, timeout=10)
                    self.assertEqual(selected.returncode, 0)
                    self.assertEqual(selected.stdout, 'INVALID_ENV\n' if value else '')
                    if value:
                        self.assertNotIn(value, selected.stdout + selected.stderr)

    def test_configuration_not_an_actual_allocator_count_claim(self):
        values = runtime.parse_process('MALLOC_ARENA_MAX=4\njvmEnvironmentCpu=4\nheapInitialMiB=768\nheapMaxMiB=768\n')
        self.assertEqual(values, dict(mallocArenaMax=4, activeProcessorCount=4, heapInitialMiB=768, heapMaxMiB=768))
        self.assertNotIn('actualArenaCount', values)
        self.assertNotIn('pid', values)
        self.assertEqual(runtime.parse_process('heapInitialMiB=768\nheapMaxMiB=768\n')['activeProcessorCount'], None)

    def test_bad_duplicate_missing_conflicting_or_secret_process_records_rejected(self):
        base = 'heapInitialMiB=768\nheapMaxMiB=768\n'
        for text in ['', 'heapMaxMiB=768\n', base + 'heapMaxMiB=768\n', base + 'INVALID_ENV\n',
                     base + 'MALLOC_ARENA_MAX=2\n', base + 'jvmCommandCpu=8\n', base + 'password=123\n',
                     base + 'jvmEnvironmentCpu=4;evil\n', 'heapInitialMiB=1024\nheapMaxMiB=768\n']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                runtime.parse_process(text)

    def test_hashes_have_exact_names_and_duplicate_or_injection_rejected(self):
        base = 'a' * 64 + '  ' + runtime.FE_CONF + '\n' + 'b' * 64 + '  ' + runtime.ENTRYPOINT + '\n'
        self.assertEqual(runtime.parse_hashes(base)['entrypointSha256'], 'b' * 64)
        for text in ['', base.splitlines()[0], base + base, base.replace(runtime.FE_CONF, '/run/client.cnf'),
                     base.replace('a' * 64, 'A' * 64), base + 'secret']:
            with self.subTest(text=text), self.assertRaises(ValueError):
                runtime.parse_hashes(text)

    def test_probe_only_emits_reviewed_numeric_values_not_full_environment(self):
        client = SimpleNamespace(prefix=['owned-docker'])
        outputs = [b'bounded-v1\n', b'MALLOC_ARENA_MAX=4\njvmEnvironmentCpu=4\nheapInitialMiB=768\nheapMaxMiB=768\n',
                   ('a' * 64 + '  ' + runtime.FE_CONF + '\n' + 'b' * 64 + '  ' + runtime.ENTRYPOINT + '\n').encode()]
        with patch.object(runtime.subprocess, 'run', side_effect=[SimpleNamespace(returncode=0, stdout=x) for x in outputs]) as call:
            identity = runtime.capture_fe_runtime(client)
        self.assertEqual(identity['profile'], 'bounded-v1')
        self.assertEqual(len(call.call_args_list), 3)
        commands = [item.args[0] for item in call.call_args_list]
        self.assertTrue(all(command[0] == 'owned-docker' for command in commands))
        self.assertNotIn('cat /proc', runtime.PROCESS_PROBE)
        self.assertIn('INVALID_ENV', runtime.PROCESS_PROBE)

    def test_failures_cannot_disclose_command_stderr(self):
        client = SimpleNamespace(prefix=['owned-docker'])
        with patch.object(runtime.subprocess, 'run', return_value=SimpleNamespace(returncode=7, stdout=b'', stderr=b'password=unsafe')):
            with self.assertRaisesRegex(RuntimeError, 'exit 7') as error:
                runtime.capture_fe_runtime(client)
        self.assertNotIn('unsafe', str(error.exception))

    def test_changed_file_without_restart_is_rejected(self):
        client = SimpleNamespace(prefix=['owned-docker'])
        for profile, process in ((b'bounded-v1\n', b'heapInitialMiB=768\nheapMaxMiB=768\n'),
                                 (b'disabled-v1\n', b'MALLOC_ARENA_MAX=4\njvmEnvironmentCpu=4\nheapInitialMiB=768\nheapMaxMiB=768\n')):
            with self.subTest(profile=profile), patch.object(runtime.subprocess, 'run',
                    side_effect=[SimpleNamespace(returncode=0, stdout=x) for x in (profile, process)]):
                with self.assertRaisesRegex(ValueError, 'restart or rollback is incomplete'):
                    runtime.capture_fe_runtime(client)

    def test_entrypoint_rejects_dangling_symlink_and_conflicting_inherited_options(self):
        from pathlib import Path
        text = (Path(__file__).parent / 'wsl-doris-entrypoint.sh').read_text(encoding='utf-8')
        self.assertIn('[ -e /run/dsl-fe-runtime-profile ] || [ -L /run/dsl-fe-runtime-profile ]', text)
        self.assertIn('[ ! -L /run/dsl-fe-runtime-profile ]', text)
        self.assertIn('[ -z "${MALLOC_ARENA_MAX:-}" ] && [ -z "${JAVA_TOOL_OPTIONS:-}" ]', text)
        self.assertIn("export JAVA_TOOL_OPTIONS='-XX:ActiveProcessorCount=4'", text)
        for option in ('_JAVA_OPTIONS', 'JDK_JAVA_OPTIONS', 'GLIBC_TUNABLES'):
            self.assertIn('[ -z "${' + option + ':-}" ]', text)
        self.assertIn('/^(_JAVA_OPTIONS|JDK_JAVA_OPTIONS|GLIBC_TUNABLES)=./ { print "INVALID_ENV" }', runtime.PROCESS_PROBE)


if __name__ == '__main__':
    unittest.main()
