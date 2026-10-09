"""Isolated native MA precision regressions, with an integer/Fraction oracle.

Only fixed DSLs and fixed raw fixtures are accepted. This is synthetic native
evidence, never formal accuracy or a substitute for the immutable CSV matrix.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, localcontext
from fractions import Fraction
import json
from pathlib import Path
import re
import secrets

from check_project_combinations import compiled_paths
from run_correctness import bind_sql, sql_literal
from validate_project_sources import ROOT, WslDoris, digest

EVALUATION_DATE = '2026-04-14'
OPERATORS = ('=', '!=', '>', '>=', '<', '<=')
DATABASE_PATTERN = re.compile(r'dsl_ma_precision_[0-9a-f]{12}\Z')
SOURCE_STATE_SQL = (
    "SELECT 'basic',COUNT(*),MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_basic "
    "UNION ALL SELECT 'ext',COUNT(*),MIN(bizdate),MAX(bizdate) FROM newzl.hsj_stock_hq_ext "
    "UNION ALL SELECT 'code',COUNT(*),NULL,NULL FROM newzl.hsj_stock_code_info")


def owned_database(value):
    if not isinstance(value, str) or DATABASE_PATTERN.fullmatch(value) is None:
        raise ValueError('Not an exactly owned MA precision fixture database')
    return value


def vectors():
    # Actual 900924 observations, oldest first. Prices remain original integers.
    dates = ['2026-03-17', '2026-03-18', '2026-03-19', '2026-03-20',
             '2026-03-23', '2026-03-24', '2026-03-25', '2026-03-26',
             '2026-03-27', '2026-03-30', '2026-03-31', '2026-04-01',
             '2026-04-02', '2026-04-03', '2026-04-07', '2026-04-08',
             '2026-04-09', '2026-04-10', '2026-04-13', EVALUATION_DATE]
    actual = [3700, 3680, 3600, 3590, 3450, 3520, 3520, 3480, 3510, 3480,
              3460, 3490, 3470, 3440, 3430, 3560, 3510, 3550, 3530, 3530]
    specimens = [
        ('actual-900924', '900924', dates, actual),
        ('reflected-positive-trend', 'MA0001', dates, [7000 - v for v in actual]),
        ('equal-positive', 'MA0002', dates, [3536] * 20),
        ('tiny-positive', 'MA0003', dates, [1] * 17 + [2, 1, 1]),
        ('tiny-negative', 'MA0004', dates, [-1] * 17 + [-2, -1, -1]),
        ('equal-negative', 'MA0005', dates, [-3536] * 20),
        ('null-current', 'MA0006', dates, actual[:-1] + [None]),
        ('null-interior', 'MA0007', dates, [None] + actual[1:]),
        ('insufficient-three', 'MA0008', dates[-2:], actual[-2:]),
        ('insufficient-twenty', 'MA0009', dates[-19:], actual[-19:]),
    ]
    maximum = 2 ** 63 - 1
    end = date.fromisoformat(EVALUATION_DATE)
    long_dates = [str(end - timedelta(days=4999 - i)) for i in range(5000)]
    specimens.append(('max-window-bigint-upper', 'MA0010', long_dates,
                       [maximum - 1] + [maximum] * 4999))
    result = []
    for name, code, days, prices in specimens:
        if len(days) != len(prices) or not days or days[-1] != EVALUATION_DATE:
            raise AssertionError('Invalid fixed specimen')
        result.append(dict(name=name, market=1, code=code,
                           observations=[dict(date=d, closePx=p) for d, p in zip(days, prices)]))
    return result


def mean(raw_observations, n):
    """Exact rational average; no SQL, float, Decimal rounding or registry."""
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 5000:
        raise ValueError('Frozen MA window must be 1..5000')
    tail = raw_observations[-n:]
    if len(tail) != n or any(r['closePx'] is None for r in tail):
        return None
    return Fraction(sum(r['closePx'] for r in tail), 10000 * n)


def compare(left, operator, right):
    if operator not in OPERATORS:
        raise ValueError('Unfrozen comparison')
    if left is None or right is None:
        return None
    return {'=': left == right, '!=': left != right, '>': left > right,
            '>=': left >= right, '<': left < right, '<=': left <= right}[operator]


def indicator(n):
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 5000:
        raise ValueError('Invalid fixed MA window')
    return "indicator('', '', '" + str(n) + "日均线', '" + EVALUATION_DATE + "', '', '', '')"


def cases():
    result = []
    for left, right in ((3, 5), (5, 20), (4999, 5000), (1, 5000)):
        for operator in OPERATORS:
            result.append(dict(name=f'ma{left}-{operator}-ma{right}', windows=[left, right],
                               comparisons=[(0, operator, 1)],
                               dsl=indicator(left) + ' ' + operator + ' ' + indicator(right)))
    result.append(dict(name='actual-three-windows-and', windows=[3, 5, 5, 20],
                       comparisons=[(0, '>', 1), (2, '>=', 3)],
                       dsl='(' + indicator(3) + ' > ' + indicator(5) + ') and (' +
                           indicator(5) + ' >= ' + indicator(20) + ')'))
    return result


def expected(case, fixtures=None):
    selected = []
    for specimen in vectors() if fixtures is None else fixtures:
        means = [mean(specimen['observations'], n) for n in case['windows']]
        if all(compare(means[a], op, means[b]) is True for a, op, b in case['comparisons']):
            selected.append([str(specimen['market']), specimen['code']])
    return sorted(selected)


def rational_evidence(value):
    if value is None:
        return None
    with localcontext() as context:
        context.prec = 80
        decimal = str(Decimal(value.numerator) / Decimal(value.denominator))
    return dict(numerator=str(value.numerator), denominator=str(value.denominator), decimal80=decimal)


def close_projection(ddl):
    matches = re.findall(r'(?m)^\s*(CAST\(CAST\(b\.closePx AS DECIMAL\(24,4\)\) / 10000 '
                         r'AS DECIMAL\(19,4\)\)) AS closePrice,?\s*$', ddl)
    if len(matches) != 1:
        raise ValueError('Expected one audited exact BIGINT close-price projection')
    return matches[0]


def checked_sql(artifact, database):
    """Internal compilation only. Reject unknown sources and extra statements."""
    owned_database(database)
    sql, bindings = artifact['sql'], artifact['bindings']
    if not isinstance(sql, str) or not isinstance(bindings, list) or not bindings:
        raise ValueError('Malformed compiler artifact')
    if any(value != EVALUATION_DATE for value in bindings):
        raise ValueError('Only the frozen evaluation-date bindings are permitted')
    body = sql.rstrip().removesuffix(';')
    if (not body.startswith('WITH history AS (') or ';' in body or
            any(marker in body for marker in ('--', '/*', '*/', '#')) or
            re.search(r'\b(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|GRANT|REVOKE|LOAD|OUTFILE|INFILE)\b',
                      body, flags=re.I)):
        raise ValueError('Unexpected SQL statement in fixed compilation')
    sources = re.findall(r'\b(?:FROM|JOIN)\s+([\w.]+)', body, flags=re.I)
    allowed = {'newzl.v_hsj_stock_hq_basic', 'history', 'history_ranked',
               'observed_tail', 'features', 'current_rows'}
    if not sources or 'newzl.v_hsj_stock_hq_basic' not in sources or set(sources) - allowed:
        raise ValueError('Unfrozen compiler data source')
    return bind_sql(sql, bindings).replace('newzl.v_hsj_stock_hq_basic',
                                           database + '.v_hsj_stock_hq_basic')


def projection_sql(bound_sql, case):
    marker = 'SELECT mktcode,tgtcode\nFROM current_rows'
    if bound_sql.count(marker) != 1:
        raise ValueError('Unknown compiler final-projection shape')
    prefix = bound_sql.split(marker, 1)[0]
    aliases = re.findall(r'AS `(f[1-9][0-9]*)`', prefix)
    if len(aliases) != len(case['windows']) or len(set(aliases)) != len(aliases):
        raise ValueError('Unexpected fixed MA feature aliases')
    return prefix + 'SELECT mktcode,tgtcode,' + ','.join('`' + a + '`' for a in aliases) + \
        '\nFROM current_rows\nORDER BY mktcode,tgtcode;', aliases


def source_state(client):
    return dict(rows=sorted(client.query(SOURCE_STATE_SQL)),
                formalRegistry=sorted(client.query('SELECT * FROM newzl.data_snapshot_registry')))


def run_native(client, database, suite, compiled, fixtures, close_expression, report):
    """Create only the exact random owned namespace and remove it in finally."""
    owned_database(database)
    if close_expression != 'CAST(CAST(b.closePx AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4))':
        raise ValueError('Unfrozen raw-price projection')
    if len(compiled) != len(suite):
        raise ValueError('Incomplete compiled fixed suite')
    # All compilation checks happen before the first database mutation.
    bound = []
    for case, paths in zip(suite, compiled):
        if set(paths) != {'project', 'reference'}:
            raise ValueError('Both frozen access paths are required')
        for mode in ('project', 'reference'):
            sql = checked_sql(paths[mode], database)
            probe, aliases = projection_sql(sql, case)
            bound.append((case, mode, paths[mode], sql, probe, aliases))
    before = source_state(client)
    report['sourceStateBefore'] = before
    created = False
    try:
        if client.query("SHOW DATABASES LIKE '" + database + "'"):
            raise ValueError('Random fixture name already exists; refusing to reuse it')
        client.query('CREATE DATABASE ' + database)
        created = True
        client.query('CREATE TABLE ' + database + '.hsj_stock_hq_basic ('
                     'mktcode INT NOT NULL,tgtcode VARCHAR(12) NOT NULL,bizdate DATE NOT NULL,closePx BIGINT NULL) '
                     'DUPLICATE KEY(mktcode,tgtcode,bizdate) '
                     'DISTRIBUTED BY HASH(mktcode,tgtcode) BUCKETS 1 PROPERTIES ("replication_num"="1")')
        client.query('CREATE VIEW ' + database + '.v_hsj_stock_hq_basic AS SELECT b.*,' +
                     close_expression + ' AS closePrice FROM ' + database + '.hsj_stock_hq_basic b')
        rows = [(v['market'], v['code'], r['date'], r['closePx'])
                for v in fixtures for r in v['observations']]
        for start in range(0, len(rows), 100):
            client.query('INSERT INTO ' + database + '.hsj_stock_hq_basic VALUES ' +
                         ','.join('(' + ','.join(sql_literal(value) for value in row) + ')'
                                  for row in rows[start:start + 100]))
        report['loadedFixtureRows'] = int(client.query('SELECT COUNT(*) FROM ' + database +
                                                       '.hsj_stock_hq_basic')[0][0])
        if report['loadedFixtureRows'] != len(rows):
            raise AssertionError('Fixture row count differs from original integer vectors')
        report['baseProjectionTypes'] = [list(r) for r in client.query('DESC ' + database +
            '.v_hsj_stock_hq_basic') if r[0] in ('closePx', 'closePrice')]
        projected = set()
        for index, (case, mode, artifact, sql, probe, aliases) in enumerate(bound):
            actual = [list(row) for row in client.query(sql)]
            hand = expected(case, fixtures)
            check = dict(case=case['name'], mode=mode, status='PASS' if actual == hand else 'FAIL',
                         actual=actual, expected=hand, sql=artifact['sql'], bindings=artifact['bindings'],
                         boundFixtureSql=sql, explain=[list(r) for r in client.query('EXPLAIN VERBOSE ' + sql)])
            report['checks'].append(check)
            shape = (tuple(case['windows']), mode)
            if shape not in projected:
                projected.add(shape)
                view = database + '.ma_probe_' + str(index)
                client.query('CREATE VIEW ' + view + ' AS ' + probe.rstrip(';'))
                types = [list(r) for r in client.query('DESC ' + view) if r[0] in aliases]
                values = [list(r) for r in client.query(probe)]
                type_ok = len(types) == len(aliases) and all(
                    re.fullmatch(r'decimal(?:v3)?\(38,\s*18\)', r[1], flags=re.I) is not None
                    for r in types)
                by_key = {(str(v['market']), v['code']): v for v in fixtures}
                projection_keys_ok = [r[:2] for r in values] == [list(k) for k in sorted(by_key)]
                nulls_ok = projection_keys_ok and all(len(r) == len(aliases) + 2 and all(
                    (text == 'NULL') == (mean(by_key[tuple(r[:2])]['observations'], n) is None)
                    for text, n in zip(r[2:], case['windows'])) for r in values)
                report.setdefault('projections', []).append(dict(windows=case['windows'], mode=mode,
                    sql=probe, aliases=aliases, types=types, decimalScale18=type_ok, rows=values,
                    keysEqual=projection_keys_ok, nullPatternEqual=nulls_ok,
                    handRationals=[dict(market=str(v['market']), code=v['code'], values=[
                        rational_evidence(mean(v['observations'], n)) for n in case['windows']]) for v in fixtures]))
                if not type_ok:
                    raise AssertionError('Native MA output is not DECIMAL(38,18)')
                if not nulls_ok:
                    raise AssertionError('Native MA projection keys/NULL pattern differ from raw integers')
            if check['status'] != 'PASS':
                raise AssertionError('Strict native MA security-set difference: ' + case['name'] + '/' + mode)
    finally:
        cleanup_errors = []
        if created:
            try:
                client.query('DROP DATABASE ' + owned_database(database))
                if client.query("SHOW DATABASES LIKE '" + database + "'"):
                    raise AssertionError('Exact fixture namespace remains after cleanup')
                report['fixtureCleanup'] = 'DONE'
            except Exception as error:
                cleanup_errors.append(str(error))
                report['fixtureCleanup'] = 'FAILED'
        else:
            report['fixtureCleanup'] = 'NOT_CREATED'
        try:
            after = source_state(client)
            report['sourceStateAfter'] = after
            report['formalRegistryUnchanged'] = after['formalRegistry'] == before['formalRegistry']
            report['sourceStateUnchanged'] = after == before
            if after != before:
                cleanup_errors.append('Original newzl data or formal registration changed')
        except Exception as error:
            cleanup_errors.append(str(error))
        report['cleanupErrors'] = cleanup_errors
        if cleanup_errors:
            raise AssertionError('MA fixture cleanup/source preservation failed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='java')
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Explicitly create and remove the isolated fixture')
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error('--execute is required; offline unittest does not start Doris')
    folder = args.output_dir.resolve()
    if folder.exists():
        raise ValueError('Use a fresh evidence directory; never overwrite an earlier run')
    folder.mkdir(parents=True)
    fixtures, suite = vectors(), cases()
    report = dict(purpose='SYNTHETIC_NATIVE_MA_PRECISION_REGRESSION',
                  officialAcceptanceEligible=False, comparisonPolicy='EXACT_SECURITY_KEYS_NO_TOLERANCE',
                  oracle='RAW_INTEGER_FRACTION_NO_SQL_VIEW_OR_REGISTRY',
                  startedAtUtc=datetime.now(timezone.utc).isoformat(), vectors=fixtures, checks=[],
                  jarSha256=digest(ROOT / 'target/dsl-doris-compiler.jar'),
                  runnerSha256=digest(Path(__file__)),
                  viewSha256=digest(ROOT / 'data/doris/ddl/002_semantic_view.sql'))
    try:
        expression = close_projection((ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8'))
        compiled = compiled_paths(suite, args.java)
        client = WslDoris(args.distribution, 'dsl-doris-official')
        database = owned_database('dsl_ma_precision_' + secrets.token_hex(6))
        report['fixtureDatabase'] = database
        run_native(client, database, suite, compiled, fixtures, expression, report)
        report['artifactsUnchanged'] = (
            digest(ROOT / 'target/dsl-doris-compiler.jar') == report['jarSha256'] and
            digest(Path(__file__)) == report['runnerSha256'] and
            digest(ROOT / 'data/doris/ddl/002_semantic_view.sql') == report['viewSha256'])
        if not report['artifactsUnchanged']:
            raise AssertionError('MA regression artifacts changed during execution')
    except Exception as error:
        report['fatalError'] = str(error)
        raise
    finally:
        report.update(completedAtUtc=datetime.now(timezone.utc).isoformat(),
                      passed=sum(c['status'] == 'PASS' for c in report['checks']), total=len(report['checks']))
        report['status'] = 'PASS' if ('fatalError' not in report and report['total'] == len(suite) * 2 and
            report['passed'] == report['total'] and report.get('fixtureCleanup') == 'DONE' and
            report.get('sourceStateUnchanged') and report.get('artifactsUnchanged')) else 'FAIL'
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'passed', 'total', 'fixtureCleanup')}))
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
