"""Native RSI regression: strict fixtures and finite-scale limits stay separate.

RSI's declared DECIMAL(38,12) output is finite, not an infinite rational. The
normal fixture keys are still computed with exact Fraction comparisons and no
tolerance. Extreme rounding counterexamples are reported explicitly, never
relabeled as successful exact comparisons or removed from the SQL input.
"""
import argparse
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
import json
from pathlib import Path
import re
import secrets

from check_project_combinations import compiled_paths
from check_project_ma_precision import close_projection, rational_evidence, source_state
from run_correctness import bind_sql, sql_literal
from validate_project_sources import ROOT, WslDoris, digest

EVALUATION_DATE = '2026-04-14'
OPERATORS = ('=', '!=', '>', '>=', '<', '<=')
SCALE = 12
DATABASE_PATTERN = re.compile(r'dsl_rsi_precision_[0-9a-f]{12}\Z')
CLOSE_EXPRESSION = 'CAST(CAST(b.closePx AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4))'


def owned_database(value):
    if not isinstance(value, str) or DATABASE_PATTERN.fullmatch(value) is None:
        raise ValueError('Not an exactly owned RSI precision fixture database')
    return value


def specimen(name, code, prices, *, diagnostic=False):
    end = date.fromisoformat(EVALUATION_DATE)
    size = len(prices)
    return dict(name=name, market=0, code=code,
                evidenceDomain='FINITE_PRECISION_LIMIT' if diagnostic else 'STRICT_EXACT_FIXTURE',
                observations=[dict(date=str(end - timedelta(days=size - i - 1)), closePx=p)
                              for i, p in enumerate(prices)])


def strict_vectors():
    first = specimen('actual-000903-exact50', '000903', [25600, 26000, 25300, 25300, 25500, 25600])
    second = specimen('actual-300135-exact50', '300135', [38200, 38700, 37700, 38100, 38700, 38200])
    # Actual six trading observation dates, not synthetic consecutive dates.
    actual_dates = ['2026-04-07', '2026-04-08', '2026-04-09', '2026-04-10', '2026-04-13', EVALUATION_DATE]
    for vector in (first, second):
        for observation, day in zip(vector['observations'], actual_dates):
            observation['date'] = day
    vectors = [first, second,
        specimen('above50-one-raw-unit', 'RS0001', [10000, 30000, 20000, 40000, 10000, 10001]),
        specimen('below50-one-raw-unit', 'RS0002', [10000, 30000, 20000, 40000, 10000, 9999]),
        specimen('null-current', 'RS0003', [10000, 30000, 20000, 40000, 10000, None]),
        specimen('null-interior', 'RS0004', [10000, 30000, None, 40000, 10000, 10001]),
        specimen('insufficient-predecessor', 'RS0005', [30000, 20000, 40000, 10000, 10001]),
        specimen('all-rises-zero-loss-null', 'RS0006', list(range(10000, 10006))),
        specimen('all-flat-zero-loss-null', 'RS0007', [10000] * 6),
        specimen('all-falls-exact-zero', 'RS0008', list(range(10005, 9999, -1))),
        specimen('negative-original-prices-exact50', 'RS0009', [-25600, -26000, -25300, -25300, -25500, -25600]),
    ]
    minimum, maximum = -(2 ** 63), 2 ** 63 - 1
    # Full signed source domain, 5000 deltas. G=L, so RSI=50 exactly while
    # sum(abs(delta)) reaches the conservative 5000-window overflow boundary.
    prices = [minimum if i % 2 == 0 else maximum for i in range(5001)]
    vectors.append(specimen('max5000-signed-bigint-exact50', 'RS0010', prices))
    return vectors


def limit_vectors():
    minimum, maximum = -(2 ** 63), 2 ** 63 - 1
    prices = [minimum if i % 2 == 0 else maximum for i in range(5001)]
    prices[-1] = minimum + 1
    return [specimen('max5000-rsi-above50-below-output-quantum', 'RL0001', prices, diagnostic=True)]


def sums(observations, n):
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 5000:
        raise ValueError('Frozen RSI window must be 1..5000')
    tail = observations[-(n + 1):]
    if len(tail) != n + 1 or any(r['closePx'] is None for r in tail):
        return None
    changes = [b['closePx'] - a['closePx'] for a, b in zip(tail, tail[1:])]
    return dict(gain=sum(max(d, 0) for d in changes), loss=sum(max(-d, 0) for d in changes),
                absolute=sum(abs(d) for d in changes), completeDeltas=n)


def exact_rsi(observations, n):
    parts = sums(observations, n)
    if parts is None or parts['loss'] == 0:
        return None
    return Fraction(100 * parts['gain'], parts['absolute'])


def declared_output(exact):
    """Independent nonnegative integer division, matching declared 12 places."""
    if exact is None:
        return None
    if exact < 0 or exact > 100:
        raise ValueError('RSI fraction is outside its mathematical domain')
    quantum = 10 ** SCALE
    return Fraction(exact.numerator * quantum // exact.denominator, quantum)


def compare(value, operator, threshold=Fraction(50)):
    if operator not in OPERATORS:
        raise ValueError('Unfrozen RSI comparison')
    if value is None:
        return None
    return {'=': value == threshold, '!=': value != threshold, '>': value > threshold,
            '>=': value >= threshold, '<': value < threshold, '<=': value <= threshold}[operator]


def cases():
    return [dict(name=f'rsi{n}-{operator}-50', n=n, operator=operator,
        dsl="indicator('', '', 'RSI(" + str(n) + ")', '" + EVALUATION_DATE + "', '', '', '') " +
            operator + ' 50') for n in (5, 5000) for operator in OPERATORS]


def expected(case, fixtures, *, finite=False):
    selected = []
    for vector in fixtures:
        value = exact_rsi(vector['observations'], case['n'])
        if finite:
            value = declared_output(value)
        if compare(value, case['operator']) is True:
            selected.append([str(vector['market']), vector['code']])
    return sorted(selected)


def checked_sql(artifact, database):
    owned_database(database)
    sql, bindings = artifact['sql'], artifact['bindings']
    if not isinstance(sql, str) or not isinstance(bindings, list) or not bindings:
        raise ValueError('Malformed fixed RSI compiler artifact')
    if any(v != EVALUATION_DATE and (type(v) is not int or v != 50) for v in bindings):
        raise ValueError('Only the frozen date and threshold bindings are allowed')
    if bindings.count(EVALUATION_DATE) != 2 or sum(type(v) is int and v == 50 for v in bindings) != 1:
        raise ValueError('Unexpected fixed RSI parameter structure')
    body = sql.rstrip().removesuffix(';')
    if (not body.startswith('WITH history AS (') or ';' in body or
        any(s in body for s in ('--', '/*', '*/', '#')) or
        re.search(r'\b(?:CREATE|ALTER|DROP|INSERT|UPDATE|DELETE|GRANT|REVOKE|LOAD|OUTFILE|INFILE)\b', body, flags=re.I)):
        raise ValueError('Unexpected SQL statement in fixed RSI compilation')
    sources = re.findall(r'\b(?:FROM|JOIN)\s+([\w.]+)', body, flags=re.I)
    allowed = {'newzl.v_hsj_stock_hq_basic', 'history', 'history_ranked',
               'observed_tail', 'deltas', 'features', 'current_rows'}
    if 'newzl.v_hsj_stock_hq_basic' not in sources or set(sources) - allowed:
        raise ValueError('Unfrozen RSI data source')
    if ' AS DOUBLE' in body.upper() or ' AS FLOAT' in body.upper():
        raise ValueError('RSI candidate must not accumulate binary floating point')
    return bind_sql(sql, bindings).replace('newzl.v_hsj_stock_hq_basic',
                                           database + '.v_hsj_stock_hq_basic')


def projection_sql(sql):
    marker = 'SELECT mktcode,tgtcode\nFROM current_rows'
    if sql.count(marker) != 1:
        raise ValueError('Unexpected RSI final projection shape')
    prefix = sql.split(marker, 1)[0]
    if re.findall(r'AS `(f[1-9][0-9]*)`', prefix) != ['f1']:
        raise ValueError('Unexpected fixed RSI feature aliases')
    return prefix + 'SELECT mktcode,tgtcode,`f1`\nFROM current_rows\nORDER BY mktcode,tgtcode;'


def run_native(client, database, suite, compiled, report):
    owned_database(database)
    if len(compiled) != len(suite):
        raise ValueError('Incomplete fixed RSI compilation')
    bound = []
    for case, paths in zip(suite, compiled):
        if set(paths) != {'project', 'reference'}:
            raise ValueError('Both RSI access paths are required')
        for mode in ('project', 'reference'):
            sql = checked_sql(paths[mode], database)
            bound.append((case, mode, paths[mode], sql, projection_sql(sql)))
    before = source_state(client)
    report['sourceStateBefore'] = before
    strict, limits = strict_vectors(), limit_vectors()
    fixtures = strict + limits
    strict_keys = {(str(v['market']), v['code']) for v in strict}
    limit_keys = {(str(v['market']), v['code']) for v in limits}
    created = False
    try:
        if client.query("SHOW DATABASES LIKE '" + database + "'"):
            raise ValueError('Random RSI namespace already exists; refusing to reuse it')
        client.query('CREATE DATABASE ' + database)
        created = True
        client.query('CREATE TABLE ' + database + '.hsj_stock_hq_basic('
                     'mktcode INT NOT NULL,tgtcode VARCHAR(12) NOT NULL,bizdate DATE NOT NULL,closePx BIGINT NULL) '
                     'DUPLICATE KEY(mktcode,tgtcode,bizdate) DISTRIBUTED BY HASH(mktcode,tgtcode) BUCKETS 1 '
                     'PROPERTIES ("replication_num"="1")')
        client.query('CREATE VIEW ' + database + '.v_hsj_stock_hq_basic AS SELECT b.*,' +
                     CLOSE_EXPRESSION + ' AS closePrice FROM ' + database + '.hsj_stock_hq_basic b')
        rows = [(v['market'], v['code'], r['date'], r['closePx']) for v in fixtures for r in v['observations']]
        for start in range(0, len(rows), 100):
            client.query('INSERT INTO ' + database + '.hsj_stock_hq_basic VALUES ' +
                ','.join('(' + ','.join(sql_literal(x) for x in r) + ')' for r in rows[start:start + 100]))
        loaded = int(client.query('SELECT COUNT(*) FROM ' + database + '.hsj_stock_hq_basic')[0][0])
        report['loadedFixtureRows'] = loaded
        if loaded != len(rows):
            raise AssertionError('RSI original-integer fixture row count differs')
        report['baseProjectionTypes'] = [list(r) for r in client.query('DESC ' + database + '.v_hsj_stock_hq_basic')
                                         if r[0] in ('closePx', 'closePrice')]
        projected = set()
        for index, (case, mode, artifact, sql, probe) in enumerate(bound):
            actual = [list(r) for r in client.query(sql)]
            if any(tuple(r) not in strict_keys | limit_keys for r in actual) or len({tuple(r) for r in actual}) != len(actual):
                raise AssertionError('RSI query returned unknown or duplicate fixture keys')
            strict_actual = [r for r in actual if tuple(r) in strict_keys]
            limit_actual = [r for r in actual if tuple(r) in limit_keys]
            strict_hand = expected(case, strict)
            exact_limit_hand = expected(case, limits)
            finite_limit_hand = expected(case, limits, finite=True)
            check = dict(case=case['name'], mode=mode, status='PASS' if strict_actual == strict_hand else 'FAIL',
                strictExactActual=strict_actual, strictExactExpected=strict_hand, fullActual=actual,
                sql=artifact['sql'], bindings=artifact['bindings'], boundFixtureSql=sql,
                explain=[list(r) for r in client.query('EXPLAIN VERBOSE ' + sql)])
            report['checks'].append(check)
            report.setdefault('finitePrecisionLimitEvidence', []).append(dict(case=case['name'], mode=mode,
                actual=limit_actual, exactRationalExpected=exact_limit_hand, declared12PlaceExpected=finite_limit_hand,
                declaredOutputMatches=limit_actual == finite_limit_hand,
                exactKeysEqual=limit_actual == exact_limit_hand,
                status='PRECISION_LIMIT_OBSERVED' if finite_limit_hand != exact_limit_hand else 'NO_THRESHOLD_DIFFERENCE'))
            if limit_actual != finite_limit_hand:
                raise AssertionError('Native RSI differs from declared finite output; no tolerance permitted')
            shape = (case['n'], mode)
            if shape not in projected:
                projected.add(shape)
                view = database + '.rsi_probe_' + str(index)
                client.query('CREATE VIEW ' + view + ' AS ' + probe.rstrip(';'))
                types = [list(r) for r in client.query('DESC ' + view) if r[0] == 'f1']
                type_ok = len(types) == 1 and re.fullmatch(r'decimal(?:v3)?\(38,\s*12\)', types[0][1], flags=re.I) is not None
                values = [list(r) for r in client.query(probe)]
                by_key = {(str(v['market']), v['code']): v for v in fixtures}
                keys_ok = [r[:2] for r in values] == [list(k) for k in sorted(by_key)]
                finite_values_ok = keys_ok and all(len(r) == 3 and (
                    (r[2] == 'NULL' and declared_output(exact_rsi(by_key[tuple(r[:2])]['observations'], case['n'])) is None) or
                    (r[2] != 'NULL' and Fraction(Decimal(r[2])) == declared_output(
                        exact_rsi(by_key[tuple(r[:2])]['observations'], case['n'])))) for r in values)
                report.setdefault('projections', []).append(dict(n=case['n'], mode=mode, sql=probe, types=types,
                    decimalScale12=type_ok, keysEqual=keys_ok, finiteOutputValuesEqual=finite_values_ok, rows=values,
                    independentHandValues=[dict(code=v['code'], evidenceDomain=v['evidenceDomain'],
                        rawSums=sums(v['observations'], case['n']), exactRsi=rational_evidence(exact_rsi(v['observations'], case['n'])),
                        declared12PlaceRsi=rational_evidence(declared_output(exact_rsi(v['observations'], case['n'])))) for v in fixtures]))
                if not type_ok or not finite_values_ok:
                    raise AssertionError('RSI native output type or finite projected values differ from the declared contract')
            if check['status'] != 'PASS':
                raise AssertionError('Strict normal RSI security-set difference: ' + case['name'] + '/' + mode)
    finally:
        errors = []
        if created:
            try:
                client.query('DROP DATABASE ' + owned_database(database))
                if client.query("SHOW DATABASES LIKE '" + database + "'"):
                    raise AssertionError('Owned RSI fixture namespace remains after cleanup')
                report['fixtureCleanup'] = 'DONE'
            except Exception as error:
                errors.append(str(error))
                report['fixtureCleanup'] = 'FAILED'
        else:
            report['fixtureCleanup'] = 'NOT_CREATED'
        try:
            after = source_state(client)
            report['sourceStateAfter'] = after
            report['formalRegistryUnchanged'] = after['formalRegistry'] == before['formalRegistry']
            report['sourceStateUnchanged'] = after == before
            if before != after:
                errors.append('Original newzl data or formal registration changed')
        except Exception as error:
            errors.append(str(error))
        report['cleanupErrors'] = errors
        if errors:
            raise AssertionError('RSI fixture cleanup/source preservation failed')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--distribution', default='dsl-doris-official-01a104f9')
    parser.add_argument('--java', default='java')
    parser.add_argument('--report-dir', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Explicitly create/remove the owned synthetic namespace')
    args = parser.parse_args(argv)
    if not args.execute:
        parser.error('--execute is required; offline unittest never starts Doris')
    folder = args.report_dir.resolve()
    if folder.exists():
        raise ValueError('Use a fresh evidence directory; previous runs are immutable')
    folder.mkdir(parents=True)
    suite = cases()
    dependencies = [ROOT / 'scripts/doris/check_project_ma_precision.py',
                    ROOT / 'scripts/doris/check_project_combinations.py',
                    ROOT / 'scripts/doris/ProjectWindowCompile.java']
    report = dict(purpose='SYNTHETIC_NATIVE_RSI_PRECISION_REGRESSION', officialAcceptanceEligible=False,
        comparisonPolicy='STRICT_NORMAL_FIXTURE_KEYS_NO_TOLERANCE_LIMIT_FIXTURE_REPORTED_SEPARATELY',
        declaredOutputType='DECIMAL(38,12)', declaredRounding='NONNEGATIVE_INTEGER_DIVISION_TRUNCATE_TO_12_PLACES',
        notInfiniteRationalProof=True, notAllSignedBigintStrictComparisonProof=True,
        precisionLimit='Extreme raw BIGINT gain/loss ratios can be strictly above 50 but truncate to 50; exact-key differences are retained below.',
        startedAtUtc=datetime.now(timezone.utc).isoformat(), strictExactFixtures=strict_vectors(),
        finitePrecisionLimitFixtures=limit_vectors(), checks=[],
        jarSha256=digest(ROOT / 'target/dsl-doris-compiler.jar'), runnerSha256=digest(Path(__file__)),
        viewSha256=digest(ROOT / 'data/doris/ddl/002_semantic_view.sql'),
        dependencySha256={str(p.relative_to(ROOT)): digest(p) for p in dependencies})
    try:
        if close_projection((ROOT / 'data/doris/ddl/002_semantic_view.sql').read_text(encoding='utf-8')) != CLOSE_EXPRESSION:
            raise AssertionError('Raw close-price normalization is not the audited exact expression')
        compiled = compiled_paths(suite, args.java)
        client = WslDoris(args.distribution, 'dsl-doris-official')
        database = owned_database('dsl_rsi_precision_' + secrets.token_hex(6))
        report['fixtureDatabase'] = database
        run_native(client, database, suite, compiled, report)
        report['artifactsUnchanged'] = (
            digest(ROOT / 'target/dsl-doris-compiler.jar') == report['jarSha256'] and
            digest(Path(__file__)) == report['runnerSha256'] and
            digest(ROOT / 'data/doris/ddl/002_semantic_view.sql') == report['viewSha256'] and
            all(digest(ROOT / name) == sha for name, sha in report['dependencySha256'].items()))
        if not report['artifactsUnchanged']:
            raise AssertionError('RSI regression artifacts changed during execution')
    except Exception as error:
        report['fatalError'] = str(error)
        raise
    finally:
        report.update(completedAtUtc=datetime.now(timezone.utc).isoformat(),
            passed=sum(c['status'] == 'PASS' for c in report['checks']), total=len(report['checks']),
            precisionLimitComparisons=sum(c['status'] == 'PRECISION_LIMIT_OBSERVED'
                                         for c in report.get('finitePrecisionLimitEvidence', [])))
        ok = ('fatalError' not in report and report['total'] == len(suite) * 2 and
              report['passed'] == report['total'] and report.get('fixtureCleanup') == 'DONE' and
              report.get('sourceStateUnchanged') and report.get('artifactsUnchanged') and
              report['precisionLimitComparisons'] == 8)
        report['status'] = 'PASS_WITH_FINITE_PRECISION_LIMIT' if ok else 'FAIL'
        (folder / 'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({k: report[k] for k in ('status', 'passed', 'total', 'precisionLimitComparisons', 'fixtureCleanup')}))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
