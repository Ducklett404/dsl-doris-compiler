"""Frozen rank, scalar lookup and count oracle over raw observations.

Definitions are deliberately hand written. No compiler SQL, registry expression,
semantic view or previously passing result is used to derive an expected list.
"""
import json
from project_field_reference import KEYS, load, observation
from project_matrix_reference import METRICS, compare, evaluate, raw, render, value

MARKETS = {'': {'0', '1', '103'}, '深': {'0'}, '沪': {'1'}, '京': {'103'},
           '沪|深': {'0', '1'}, '沪|深|京': {'0', '1', '103'}, '^京': {'0', '1'}}
VERSION = 'project-rank-matrix-v1'


def security_key(key):
    """Doris mktcode is INT: Beijing 103 follows Shanghai 1, not lexical 1."""
    return int(key[0]), key[1]


def rank_mode(direction):
    side, separator, method = direction.partition(':')
    if side not in ('asc', 'desc') or (separator and method not in ('rank', 'dense_rank', 'row_number')):
        raise ValueError('Invalid frozen ranking direction: ' + direction)
    return side, method if separator else 'dense_rank'


def reference(case, source):
    calls = case['calls']
    histories = {k: h for k, h in source['histories'].items() if k[0] in MARKETS[case['market']]}
    targets = {}
    for i, call in enumerate(calls):
        if call['kind'] == 'query':
            matches = [raw(h[-1], call.get('metric', 'close')) for k, h in histories.items()
                       if k[1] == call['keyword'] or source['names'].get(k) == call['keyword']]
            targets[i] = max((v for v in matches if v is not None), default=None)
    values = {k: [value(c, h, targets.get(i)) for i, c in enumerate(calls)] for k, h in histories.items()}
    inputs = []; seen_inputs = set()
    for i, call in enumerate(calls):
        kind = call['kind']; metric = METRICS[call.get('metric', 'close')]
        def add(fn, label, missing, identity=call):
            key = (fn, label, json.dumps(identity, sort_keys=True))
            if key not in seen_inputs:
                seen_inputs.add(key)
                inputs.append(dict(function=fn, indicator=label, missing=set(missing)))
        if kind == 'count':
            base = call.get('base', dict(kind='field', metric=call.get('metric', 'close')))
            label = f"{base['n']}日均线" if base['kind'] == 'ma' else f"RSI({base['n']})" if base['kind'] == 'rsi' else metric
            add('indicator', label, [k for k, h in histories.items() if value(base, h) is None], base)
            horizon = call['n'] + (call['countOp'] == '=') if call['mode'] == 'CONS' else max(20, call['n'])
            add(call['mode'], f'完整 {horizon} 条观察记录的次数条件', [k for k, v in values.items() if v[i] is None])
            add(call['mode'] + '（窗口输入）', f'完整 {horizon} 条观察记录的条件输入',
                [k for k, h in histories.items() if len(h) < horizon or any(value(base, h[:j + 1]) is None for j in range(max(0, len(h) - horizon), len(h)))])
        else:
            function = 'querydata' if kind == 'query' else 'rank' if kind == 'rank' else 'indicator'
            add(function, metric, [k for k, v in values.items() if v[i] is None])
    candidates = [k for k in values if 'pre' not in case or evaluate(case['pre'], values[k]) is True]
    rank_ids = [i for i, c in enumerate(calls) if c['kind'] == 'rank']
    # All requested rank inputs must be non-NULL before any rank is evaluated.
    candidates = [k for k in candidates if all(values[k][i] is not None for i in rank_ids)]
    for i in rank_ids:
        side, method = rank_mode(calls[i]['direction'])
        ordered = sorted(candidates, key=lambda k: ((-values[k][i] if side == 'desc' else values[k][i]), security_key(k)))
        dense = gap_rank = 0; last = object()
        for row_number, k in enumerate(ordered, 1):
            metric_value = values[k][i]
            if metric_value != last:
                dense += 1; gap_rank = row_number; last = metric_value
            values[k][i] = row_number if method == 'row_number' else dense if method == 'dense_rank' else gap_rank
    selected = [k for k in candidates if evaluate(case['expr'], values[k]) is True]
    selected.sort(key=lambda k: ((values[k][rank_ids[0]],) + security_key(k)) if rank_ids else security_key(k))
    if case.get('limit', -1) != -1:
        selected = selected[:case['limit']]
    missing_ext = {k for k, h in histories.items() if not h[-1]['ext']} if any(c.get('metric') == 'net' for c in calls) else set()
    samples = sorted(missing_ext | set().union(*(r['missing'] for r in inputs)), key=security_key)[:20]
    return dict(rows=[list(k) for k in selected], observed=len(histories), missingExtension=missing_ext,
                inputs=inputs, sampleKeys=samples,
                coverageStatus='NO_OBSERVATIONS' if not histories else 'PARTIAL_INPUTS' if missing_ext or any(r['missing'] for r in inputs) else 'COMPLETE_QUERY_INPUTS')


def cases():
    suite = []
    def add(name, calls, expr, date='2026-04-14', market='', **extra):
        dsl = render(expr, calls, date, market)
        if 'pre' in extra:
            dsl = render(extra['pre'], calls, date, market) + ' then ' + dsl
        if 'limit' in extra:
            dsl += f" limit {extra.get('limitMinimum', 0)},{extra['limit']}"
        suite.append(dict(name=name, calls=calls, expr=expr, date=date, market=market, dsl=dsl, **extra))
    # Three explicit modes and both compatible default directions for every field.
    for metric in KEYS:
        for direction in ('asc:rank', 'desc:dense_rank', 'desc:row_number', 'asc', 'desc'):
            add('rank-' + metric + '-' + direction.replace(':', '-'),
                [dict(kind='rank', metric=metric, direction=direction)], ('cmp', 0, '<=', 5), limit=9)
    for market in ('沪', '深', '京', '沪|深', '^京', '沪|深|京'):
        for day in ('2018-08-20', '2026-04-13', '2026-04-14'):
            add('market-rank-' + market + '-' + day,
                [dict(kind='rank', metric='average', direction='asc:row_number')], ('cmp', 0, '<=', 10000), day, market)
    for maximum, minimum in ((0, 0), (1, 0), (3, 2), (10000, 0), (-1, 0)):
        add('selection-limit-' + str(minimum) + '-' + str(maximum),
            [dict(kind='rank', metric='close', direction='desc:rank')], ('cmp', 0, '<=', 10000),
            limit=maximum, limitMinimum=minimum)
    add('then-negative-net-rank-qfq', [dict(kind='field', metric='net'), dict(kind='rank', metric='qfq', direction='desc:row_number')],
        ('cmp', 1, '<=', 7), pre=('cmp', 0, '<', 0), limit=4)
    add('two-ranks-NULL-intersection', [dict(kind='rank', metric='average', direction='desc:rank'), dict(kind='rank', metric='net', direction='asc:row_number')],
        ('and', ('cmp', 0, '<=', 8), ('cmp', 1, '<=', 8)), limit=6)
    repeated_rank = dict(kind='rank', metric='average', direction='desc:row_number')
    add('repeated-rank-stable-input', [repeated_rank, dict(repeated_rank)],
        ('and', ('cmp', 0, '<=', 5), ('cmp', 1, '<=', 7)))
    repeated_query = dict(kind='query', metric='close', keyword='不存在证券')
    add('repeated-lookup-stable-input', [repeated_query, dict(repeated_query)],
        ('or', ('cmp', 0, '>', 0), ('cmp', 1, '<', 0)))
    # Raw code, current names and deliberately absent date/market/target.
    for keyword, market, label in [('000001', '', 'leading-zero-union'), ('000001', '深', 'exact-shenzhen'),
            ('000001', '沪', 'exact-shanghai'), ('000001', '京', 'exact-beijing'),
            ('1', '', 'no-coercion'), ('不存在证券', '', 'missing-target'),
            ('目标深零一', '', 'exact-name'), ('目标深零一', '沪', 'name-wrong-market'),
            ('000002', '', 'target-current-NULL'), ('000003', '', 'target-date-gap')]:
        for day in ('2026-04-13', '2026-04-14'):
            add('lookup-' + label + '-' + day,
                [dict(kind='field', metric='close'), dict(kind='query', metric='close', keyword=keyword)],
                ('callcmp', 0, '>', 1), day, market)
    for metric in ('average', 'qfq', 'hfq', 'cap', 'turn', 'net'):
        add('lookup-mixed-' + metric, [dict(kind='field', metric=metric), dict(kind='query', metric=metric, keyword='000001'), dict(kind='field', metric='volume')],
            ('and', ('callcmp', 0, '>=', 1), ('cmp', 2, '>', 0)))
    for mode, op in (('CONS', '>='), ('CONS', '='), ('EXIST', '>='), ('EXIST', '=')):
        for metric, comparison, threshold in [('net', '<', 0), ('net', '>=', 0), ('average', '>', 0), ('qfq', '>', 0)]:
            call = dict(kind='count', metric=metric, mode=mode, countOp=op, n=3, op=comparison, threshold=threshold)
            add('count-' + mode + op + '-' + metric + '-' + comparison, [call], ('cmp', 0, '=', True))
        call = dict(kind='count', metric='net', mode=mode, countOp=op, n=3, op='<', threshold=0)
        add('count-rank-' + mode + op, [call, dict(kind='rank', metric='listedCap', direction='desc:row_number')],
            ('cmp', 1, '<=', 10000), pre=('cmp', 0, '=', True), limit=5)
    for day, market in [('2000-01-01', ''), ('2006-01-04', '京'), ('2026-04-12', '沪|深|京')]:
        add('absent-' + day + '-' + market, [dict(kind='rank', metric='average', direction='desc:row_number')], ('cmp', 0, '<=', 5), day, market)
    counted = dict(kind='count', metric='net', mode='CONS', countOp='>=', n=3, op='<', threshold=0)
    add('count-shares-direct-value-input', [counted, dict(kind='field', metric='net')],
        ('and', ('cmp', 0, '=', True), ('cmp', 1, '<', 0)))
    return suite


def matrix_document():
    return dict(formatVersion=VERSION, definitionAuthority='PROJECT_INTERNAL_FROZEN_FUNCTION_SEMANTICS',
        officialAcceptanceEligible=False, snapshotId='stock-20060104-20260414-v1',
        contracts=dict(rankDefault='DENSE_RANK', rankNULL='EXCLUDE_BEFORE_ALL_RANKS',
            tieKey=['mktcode(INT)', 'tgtcode(TEXT)'], selectionLimit='MINIMUM_METADATA_MAXIMUM_CLIP_NO_OFFSET',
            countUnknown='NOT_A_HIT_SEPARATE_INPUT_DISCLOSURE', countInsufficient='NULL_RESULT',
            queryMissing='NULL_SCALAR', queryExplanation='PARTIAL_DETAIL_DETAIL_NOT_SUPPORTED'), cases=cases())
