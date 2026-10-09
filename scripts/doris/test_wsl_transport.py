"""Repeatable offline WSL transport and credential-helper tests.

Run with ``python scripts/doris/test_wsl_transport.py --output NEW_REPORT.json``.
WslDoris process calls are mocked. Optional shell tests execute only Bash with
every mysql binary replaced by a synthetic mock; no Docker or database is used.
Pass --shell-distribution EXISTING_WSL or --bash BASH_PATH for shell tests.
Generated shell fixtures are preserved under target, never deleted by this test.
"""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts/accuracy'))
from run_correctness import WslDoris

SHELL_PREFIX = None
SHELL_USES_WSL = False


class WslTransportTest(unittest.TestCase):
    def client(self, config='', environments='', *, owner='true official-data-diagnostic', config_exit=0, env_exit=0):
        responses = [subprocess.CompletedProcess([], 0, owner + '\n', ''),
            subprocess.CompletedProcess([], config_exit, config, 'private client file error'),
            subprocess.CompletedProcess([], env_exit, environments, 'private environment error')]
        with patch('run_correctness.run', side_effect=responses) as runner:
            client = WslDoris('fixture-distribution', 'dsl-doris-official')
            commands = [call.args[0] for call in runner.call_args_list]
        return client, commands

    def test_default_ports_remain_backward_compatible(self):
        client, _ = self.client()
        self.assertEqual((client.query_port, client.be_http_port, client.fe_http_port), (9030, 8040, 8030))
        self.assertIn('--port=9030', client.command)

    def test_isolated_ports_propagate_and_mysql_still_uses_private_configuration(self):
        client, _ = self.client('19030\n', 'DSL_DORIS_BE_HTTP_PORT=18040\nDSL_DORIS_FE_HTTP_PORT=18030\n')
        self.assertEqual((client.query_port, client.be_http_port, client.fe_http_port), (19030, 18040, 18030))
        self.assertIn('--defaults-extra-file=/run/dsl-client.cnf', client.command)
        self.assertIn('--port=19030', client.command)
        self.assertEqual(client.command[:5], ['wsl.exe', '-d', 'fixture-distribution', '--exec', 'docker'])

    def test_conf_read_selects_only_port_and_docker_format_filters_only_http_keys(self):
        _, commands = self.client('19030\n')
        selected = commands[1]
        self.assertIn('awk', selected)
        self.assertNotIn('cat', selected)
        program = selected[selected.index('awk') + 1]
        self.assertIn('[client', program.replace('\\', ''))
        self.assertIn('port[[:space:]]*=', program)
        self.assertNotIn('password', program)
        template = commands[2][commands[2].index('-f') + 1]
        self.assertIn('DSL_DORIS_BE_HTTP_PORT', template)
        self.assertIn('DSL_DORIS_FE_HTTP_PORT', template)
        self.assertNotIn('json .Config.Env', template)
        self.assertIn('{{if or', template)

    def test_valid_bounds_and_surrounding_whitespace(self):
        for port in ('1', '65535', ' 19030 '):
            with self.subTest(port=port):
                client, _ = self.client(port + '\n')
                self.assertEqual(client.query_port, int(port))

    def test_invalid_query_port_injection_and_credentials_are_rejected_without_echo(self):
        for port in ('0', '65536', '-1', '9030; SELECT 1', '19030/other', 'http:19030',
                '１９０３０', '', 'user=root:private_password'):
            with self.subTest(port=port):
                with self.assertRaises(ValueError) as raised:
                    self.client(port + '\n')
                self.assertNotIn('private_password', str(raised.exception))
                self.assertNotIn('SELECT', str(raised.exception))

    def test_duplicate_query_ports_are_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            self.client('9030\n19030\n')

    def test_invalid_http_port_injection_is_rejected(self):
        for port in ('0', '65536', '18040/api/private', '18040; rm -rf', ''):
            with self.subTest(port=port):
                with self.assertRaises(ValueError):
                    self.client('19030\n', 'DSL_DORIS_BE_HTTP_PORT=' + port + '\n')

    def test_duplicate_and_unknown_environment_keys_are_rejected_without_leak(self):
        for environments in ('DSL_DORIS_BE_HTTP_PORT=18040\nDSL_DORIS_BE_HTTP_PORT=18041\n',
                'DORIS_PASSWORD=private_password\n'):
            with self.assertRaises(ValueError) as raised:
                self.client('19030\n', environments)
            self.assertNotIn('private_password', str(raised.exception))

    def test_nonowned_container_is_rejected_before_reading_private_configuration(self):
        with patch('run_correctness.run', return_value=subprocess.CompletedProcess([], 0, 'true unrelated\n', '')) as runner:
            with self.assertRaises(RuntimeError):
                WslDoris('fixture', 'original-doris')
            self.assertEqual(runner.call_count, 1)

    def test_configuration_and_environment_read_failures_are_not_silently_defaulted(self):
        with self.assertRaisesRegex(RuntimeError, 'client port'):
            self.client(config_exit=1)
        with self.assertRaisesRegex(RuntimeError, 'HTTP ports'):
            self.client('19030\n', env_exit=1)

    def test_all_wsl_python_cli_and_probe_connections_use_validated_dynamic_port(self):
        paths = [ROOT / 'scripts/doris' / name for name in (
            'check_expanded_project_matrix.py', 'check_official_project_execution.py',
            'check_project_execution.py', 'check_project_resource_stability.py',
            'check_project_window_performance.py', 'check_wsl_execution_gate.py',
            'configure_project_be_memory.py', 'diagnose_performance.py', 'run_wsl_integration.py',
            'apply_numeric_view_revision.py', 'validate_project_sources.py')]
        connections = probes = endpoints = 0
        for path in paths:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, (ast.List, ast.Tuple)):
                    words = [n.value for n in node.elts if isinstance(n, ast.Constant) and isinstance(n.value, str)]
                    if '--host' in words:
                        self.assertIn('--port', words, path.name)
                        self.assertTrue(any(isinstance(n, ast.Attribute) and n.attr == 'query_port' for n in ast.walk(node)), path.name)
                        connections += 1
                if isinstance(node, ast.JoinedStr):
                    literals = ''.join(n.value for n in node.values if isinstance(n, ast.Constant) and isinstance(n.value, str))
                    if literals.startswith('jdbc:mysql://'):
                        self.assertTrue(any(isinstance(n, ast.Attribute) and n.attr == 'query_port' for n in ast.walk(node)), path.name)
                        probes += 1
                    if literals.startswith('http://127.0.0.1:') and '/api/show_config' in literals:
                        self.assertTrue(any(isinstance(n, ast.Attribute) and n.attr == 'be_http_port' for n in ast.walk(node)), path.name)
                        endpoints += 1
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertFalse('jdbc:mysql://' in node.value and ':9030/' in node.value, path.name)
                    self.assertNotEqual(node.value, 'http://127.0.0.1:8040/api/show_config', path.name)
        self.assertEqual((connections, probes, endpoints), (7, 7, 4))


class InternalMysqlHelperTest(unittest.TestCase):
    """Execute the actual helper source with an entirely synthetic mysql."""

    def setUp(self):
        if SHELL_PREFIX is None:
            self.skipTest('Specify --shell-distribution or --bash to execute offline Bash mocks')
        base = ROOT / 'target/wsl-transport-shell-fixtures'
        base.mkdir(parents=True, exist_ok=True)
        self.folder = Path(tempfile.mkdtemp(prefix=self._testMethodName + '-', dir=base))
        self.log = self.folder / 'mysql-attempts.log'
        self.mock = self.folder / 'mock-mysql'
        self.mock.write_text('''#!/usr/bin/env bash
set -u
auth=absent
[ -z "${MYSQL_PWD+x}" ] || auth=present
printf '%s\\n' "$auth" >>"$MOCK_LOG"
case "$MOCK_MODE" in
  password)
    if [ "$auth" = present ]; then printf 'query-result\\n'; exit 0; fi
    printf 'ERROR 1045 (28000): Access denied (synthetic)\\n' >&2; exit 1 ;;
  initial-empty)
    if [ "$auth" = absent ]; then printf 'query-result\\n'; exit 0; fi
    printf 'ERROR 1045 (28000): Access denied (synthetic)\\n' >&2; exit 1 ;;
  bad-password)
    printf 'ERROR 1045 (28000): Access denied (synthetic)\\n' >&2; exit 1 ;;
  network)
    printf 'ERROR 2003 (HY000): Cannot connect (synthetic)\\n' >&2; exit 2 ;;
  sql)
    printf 'ERROR 1064 (42000): Syntax error (synthetic)\\n' >&2; exit 3 ;;
  output-before-sql-error)
    printf 'ordinary query result containing ERROR 1045 text\\n'
    printf 'ERROR 1064 (42000): Syntax error (synthetic)\\n' >&2; exit 3 ;;
  output-before-network-error)
    printf 'ordinary query result containing ERROR 1045 text\\n'
    printf 'ERROR 2013 (HY000): Lost connection (synthetic)\\n' >&2; exit 4 ;;
  *) printf 'Unknown mock scenario\\n' >&2; exit 99 ;;
esac
''', encoding='utf-8', newline='\n')

    def shell_path(self, path):
        path = str(Path(path).resolve()).replace('\\', '/')
        if SHELL_USES_WSL and len(path) > 2 and path[1] == ':':
            return '/mnt/' + path[0].lower() + path[2:]
        return path

    def prelude(self, mode, credential=True):
        lines = ['export MOCK_MODE=' + shlex.quote(mode),
                 'export MOCK_LOG=' + shlex.quote(self.shell_path(self.log)),
                 'chmod 700 ' + shlex.quote(self.shell_path(self.mock))]
        lines.append('export MYSQL_PWD=synthetic-private-password' if credential else 'unset MYSQL_PWD')
        return '\n'.join(lines) + '\n'

    def invoke(self, script, arguments):
        result = subprocess.run(SHELL_PREFIX + ['--noprofile', '--norc', '-s', '--'] + arguments,
            input=script.encode('utf-8'), capture_output=True, timeout=20)
        # WSL can prefix native localized UTF-16 warnings to otherwise UTF-8
        # Bash stderr. Keep byte input to avoid Windows CRLF translation and
        # decode captured output explicitly, never failing a reader thread.
        result.stdout = result.stdout.decode('utf-8', errors='replace')
        result.stderr = result.stderr.decode('utf-8', errors='replace')
        attempts = self.log.read_text(encoding='utf-8').splitlines() if self.log.exists() else []
        self.assertNotIn('synthetic-private-password', result.stdout)
        self.assertNotIn('synthetic-private-password', result.stderr)
        return result, attempts

    def helper(self, mode, arguments=None, credential=True):
        source = (ROOT / 'scripts/doris/wsl-doris-internal-mysql.sh').read_text(encoding='utf-8')
        source = source.replace('/usr/bin/mysql', shlex.quote(self.shell_path(self.mock)))
        self.assertNotIn('/usr/bin/mysql', source, 'All real mysql calls must be replaced')
        return self.invoke(self.prelude(mode, credential) + source,
                           arguments or ['-uroot', '-h127.0.0.1', '-P19030', '-e', 'SHOW FRONTENDS'])

    def entrypoint(self, mode, marker=None, memory_percent=None):
        config = self.folder / 'client.cnf'
        config.write_text('[client]\npassword=synthetic-private-password\n', encoding='utf-8')
        if marker is not None:
            (self.folder / 'credentials-initialized').write_text(marker, encoding='utf-8')
        if memory_percent is not None:
            (self.folder / 'be-memory-percent').write_text(memory_percent + '\n', encoding='utf-8')
        installed = self.folder / 'tools/mysql'
        helper = self.folder / 'internal-mysql.sh'
        source = (ROOT / 'scripts/doris/wsl-doris-internal-mysql.sh').read_text(encoding='utf-8')
        helper.write_text(source.replace('/usr/bin/mysql', shlex.quote(self.shell_path(self.mock))),
                          encoding='utf-8', newline='\n')
        image = self.folder / 'mock-image-entrypoint'
        image.write_text('''#!/usr/bin/env bash
set -eu
[ -n "${MYSQL_PWD:-}" ] || exit 77
printf '%s\\n' "${BE_CONFIG_EXTRA:-}" > "$MOCK_BE_LOG"
printf 'entrypoint-credential-ready\\n'
exec mysql -uroot -h127.0.0.1 -P19030 -e 'SHOW FRONTENDS'
''', encoding='utf-8', newline='\n')
        source = (ROOT / 'scripts/doris/wsl-doris-entrypoint.sh').read_text(encoding='utf-8')
        replacements = {
            '/run/dsl-client.cnf': shlex.quote(self.shell_path(config)),
            '/run/dsl-credentials-initialized': shlex.quote(self.shell_path(self.folder / 'credentials-initialized')),
            '/run/dsl-be-memory-percent': shlex.quote(self.shell_path(self.folder / 'be-memory-percent')),
            '/run/dsl-internal-mysql.sh': shlex.quote(self.shell_path(helper)),
            '/run/dsl-tools/mysql': shlex.quote(self.shell_path(installed)),
            '/opt/doris-ci/entrypoint.sh': shlex.quote(self.shell_path(image)),
        }
        source = source.replace('export PATH="/run/dsl-tools:$PATH"',
                                'export PATH=' + shlex.quote(self.shell_path(installed.parent)) + ':"$PATH"')
        for old, new in replacements.items():
            source = source.replace(old, new)
        self.assertNotIn('/usr/bin/mysql', source)
        prelude = self.prelude(mode, credential=False) + 'chmod 700 ' + shlex.quote(self.shell_path(image)) + '\n'
        prelude += 'unset DSL_DORIS_BE_MEMORY_PERCENT\nexport MOCK_BE_LOG=' + shlex.quote(self.shell_path(self.folder/'be-config.log')) + '\n'
        prelude += 'export BE_CONFIG_EXTRA=' + shlex.quote('webserver_port = 18040\nmem_limit = 40%\nheartbeat_service_port = 19050') + '\n'
        return self.invoke(prelude + source, [])

    def test_initial_empty_password_uses_only_one_authentication_fallback(self):
        result, attempts = self.helper('initial-empty')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['present', 'absent'], attempts)
        self.assertEqual('query-result\n', result.stdout)

    def test_initialized_random_password_needs_one_attempt(self):
        result, attempts = self.helper('password')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['present'], attempts)

    def test_both_authentications_fail_without_looping(self):
        result, attempts = self.helper('bad-password')
        self.assertEqual(1, result.returncode)
        self.assertEqual(['present', 'absent'], attempts)

    def test_sql_errors_do_not_retry(self):
        result, attempts = self.helper('sql')
        self.assertEqual(3, result.returncode)
        self.assertEqual(['present'], attempts)

    def test_network_errors_do_not_retry(self):
        result, attempts = self.helper('network')
        self.assertEqual(2, result.returncode)
        self.assertEqual(['present'], attempts)

    def test_query_output_containing_auth_error_text_does_not_retry_sql(self):
        result, attempts = self.helper('output-before-sql-error')
        self.assertEqual(3, result.returncode)
        self.assertEqual(['present'], attempts)

    def test_query_output_containing_auth_error_text_does_not_retry_network(self):
        result, attempts = self.helper('output-before-network-error')
        self.assertEqual(4, result.returncode)
        self.assertEqual(['present'], attempts)

    def test_explicit_authentication_arguments_never_fallback(self):
        for index, options in enumerate((['--defaults-extra-file=/synthetic/client.cnf'],
                ['--defaults-file=/synthetic/client.cnf'], ['-psynthetic-argument-password'],
                ['-p', 'synthetic-argument-password'], ['--password=synthetic-argument-password'],
                ['--password', 'synthetic-argument-password'])):
            with self.subTest(options=options):
                self.log = self.folder / ('explicit-' + str(index) + '.log')
                result, attempts = self.helper('bad-password', ['-uroot'] + options + ['-e', 'SHOW FRONTENDS'])
                self.assertEqual(1, result.returncode)
                self.assertEqual(['present'], attempts)
                self.assertNotIn('synthetic-argument-password', result.stdout + result.stderr)

    def test_non_root_probe_never_fallback(self):
        result, attempts = self.helper('bad-password', ['-uother', '-e', 'SHOW FRONTENDS'])
        self.assertEqual(1, result.returncode)
        self.assertEqual(['present'], attempts)

    def test_overridden_root_username_never_fallback(self):
        result, attempts = self.helper('bad-password', ['-uroot', '--user=other', '-e', 'SHOW FRONTENDS'])
        self.assertEqual(1, result.returncode)
        self.assertEqual(['present'], attempts)

    def test_absent_process_credential_does_not_repeat_empty_login(self):
        result, attempts = self.helper('initial-empty', credential=False)
        self.assertEqual(0, result.returncode)
        self.assertEqual(['absent'], attempts)

    def test_entrypoint_initial_empty_database_uses_safe_fallback(self):
        result, attempts = self.entrypoint('initial-empty')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['present', 'absent'], attempts)
        self.assertIn('entrypoint-credential-ready', result.stdout)

    def test_entrypoint_missing_marker_with_initialized_password_still_works(self):
        result, attempts = self.entrypoint('password')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['present'], attempts)

    def test_entrypoint_default_be_share_preserves_ports_and_replaces_only_memory(self):
        result, attempts = self.entrypoint('password')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['present'], attempts)
        lines=(self.folder/'be-config.log').read_text(encoding='utf-8').splitlines()
        self.assertIn('webserver_port = 18040',lines)
        self.assertIn('heartbeat_service_port = 19050',lines)
        self.assertEqual([line for line in lines if line.startswith('mem_limit')],['mem_limit = 60%'])

    def test_entrypoint_be_share_has_a_private_40_percent_rollback(self):
        result, _ = self.entrypoint('password',memory_percent='40')
        self.assertEqual(0, result.returncode, result.stderr)
        lines=(self.folder/'be-config.log').read_text(encoding='utf-8').splitlines()
        self.assertEqual([line for line in lines if line.startswith('mem_limit')],['mem_limit = 40%'])

    def test_entrypoint_unknown_be_share_is_rejected_without_echoing_value(self):
        result, attempts = self.entrypoint('password',memory_percent='60; synthetic-untrusted')
        self.assertNotEqual(0,result.returncode)
        self.assertEqual([],attempts)
        self.assertIn('Invalid project BE process memory percentage',result.stderr)
        self.assertNotIn('synthetic-untrusted',result.stdout+result.stderr)

    def test_entrypoint_empty_marker_with_initialized_password_still_works(self):
        result, attempts = self.entrypoint('password', marker='')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['present'], attempts)

    def test_entrypoint_initialized_marker_with_initialized_password_still_works(self):
        result, attempts = self.entrypoint('password', marker='initialized\n')
        self.assertEqual(0, result.returncode, result.stderr)
        self.assertEqual(['present'], attempts)


def test_names(suite):
    for test in suite:
        if isinstance(test, unittest.TestSuite):
            yield from test_names(test)
        else:
            yield test.id()


def main():
    global SHELL_PREFIX, SHELL_USES_WSL
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path)
    shell = parser.add_mutually_exclusive_group()
    shell.add_argument('--shell-distribution', help='Existing WSL with Bash; all mysql calls remain mocked')
    shell.add_argument('--bash', type=Path, help='Native Bash executable for offline helper tests')
    args = parser.parse_args()
    if args.output and args.output.exists():
        raise ValueError('Preserve prior transport self-test evidence')
    if args.shell_distribution:
        SHELL_PREFIX = ['wsl.exe', '-d', args.shell_distribution, '--exec', 'bash']
        SHELL_USES_WSL = True
    elif args.bash:
        SHELL_PREFIX = [str(args.bash.resolve())]
    elif sys.platform != 'win32' and shutil.which('bash'):
        SHELL_PREFIX = [shutil.which('bash')]
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    names = list(test_names(suite))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if args.output:
        failed = {getattr(test, 'test_case', test).id() for test, _ in result.failures + result.errors}
        skipped = {test.id() for test, _ in result.skipped}
        report = dict(purpose='OFFLINE_DIAGNOSTIC_TRANSPORT_PORT_REGRESSIONS',
            status='PASS' if result.wasSuccessful() else 'FAIL', total=result.testsRun,
            passed=result.testsRun - len(failed) - len(result.skipped),
            skipped=len(result.skipped),
            checks=[dict(test=name, status='FAIL' if name in failed else 'SKIP' if name in skipped else 'PASS') for name in names],
            failures=[dict(test=str(test), error=error) for test, error in result.failures],
            errors=[dict(test=str(test), error=error) for test, error in result.errors],
            sourceSha256={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in (Path(__file__).resolve(), ROOT / 'scripts/accuracy/run_correctness.py',
                             ROOT / 'scripts/doris/wsl-doris-internal-mysql.sh', ROOT / 'scripts/doris/wsl-doris-entrypoint.sh')},
            shellMockExecuted=SHELL_PREFIX is not None, realMysqlExecuted=False,
            databaseMutationExecuted=False, nativeDatabaseEvidence=False,
            userFilesDeleted=False, generatedFixturesPreserved='target/wsl-transport-shell-fixtures')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open('x', encoding='utf-8') as stream:
            json.dump(report, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
