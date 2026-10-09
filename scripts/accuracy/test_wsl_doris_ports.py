"""Offline transport regressions; no Docker/WSL/database mutation is executed."""
import argparse
import ast
import json
from pathlib import Path
import subprocess
import unittest
from unittest.mock import patch

from run_correctness import WslDoris

ROOT = Path(__file__).resolve().parents[2]


class WslDorisPortsTest(unittest.TestCase):
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if args.output and args.output.exists():
        raise ValueError('Preserve prior transport self-test evidence')
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(WslDorisPortsTest))
    if args.output:
        report = dict(purpose='OFFLINE_DIAGNOSTIC_TRANSPORT_PORT_REGRESSIONS',
            status='PASS' if result.wasSuccessful() else 'FAIL', total=result.testsRun,
            passed=result.testsRun - len(result.failures) - len(result.errors),
            failures=[dict(test=str(test), error=error) for test, error in result.failures],
            errors=[dict(test=str(test), error=error) for test, error in result.errors],
            databaseMutationExecuted=False, nativeDatabaseEvidence=False)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    raise SystemExit(0 if result.wasSuccessful() else 1)
