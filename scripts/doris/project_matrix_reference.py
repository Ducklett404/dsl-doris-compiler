"""Independent raw-row oracle for the project contract (no generated SQL or semantic views)."""
from collections import Counter, defaultdict
from decimal import Decimal

METRICS = {'last':'最新价','previous':'昨收价','open':'开盘价','high':'最高价','low':'最低价',
    'close':'收盘价','volume':'成交量','amount':'成交额','quantity':'量比','turn':'换手率',
    'trueTurn':'真实换手率','cap':'总市值','listedCap':'流通市值','rise':'涨跌幅',
    'average':'均价','qfq':'前复权收盘价','hfq':'后复权收盘价','net':'主力净流入','amplitude':'振幅'}
MARKETS = {'深': {'0'}, '沪': {'1'}, '京': {'103'}, '沪|深': {'0', '1'}, '^京': {'0', '1'}}


def load(con, date, retained_rows=21):
    if not isinstance(retained_rows, int) or retained_rows < 1: raise ValueError('Invalid raw history budget')
    rows = con.execute("""WITH tail AS (
        SELECT mktcode,tgtcode,bizdate,closePx,openPx,volume FROM newzl.hsj_stock_hq_basic
        WHERE bizdate<=CAST(? AS DATE)
        QUALIFY ROW_NUMBER() OVER(PARTITION BY mktcode,tgtcode ORDER BY bizdate DESC)<=?)
        SELECT b.*,e.tgtcode,e.ZJLXMainNetTur FROM tail b
        LEFT JOIN newzl.hsj_stock_hq_ext e USING(mktcode,tgtcode,bizdate)
        ORDER BY b.mktcode,b.tgtcode,b.bizdate""", [date, retained_rows]).fetchall()
    histories = defaultdict(list)
    for market, code, day, close, opening, volume, ext, net in rows:
        histories[(str(market), code)].append(dict(date=str(day), close=close, open=opening,
            volume=volume, ext=ext is not None, net=None if net == -999999 else net))
    names = {(str(m), c): name for m, c, name in con.execute(
        'SELECT mktcode,tgtcode,name FROM newzl.hsj_stock_code_info').fetchall()}
    return dict(histories={k: h for k, h in histories.items() if h[-1]['date'] == date}, names=names)


def sql_bool(op, a, b=None):
    if op == 'not': return None if a is None else not a
    if op == 'and': return False if a is False or b is False else None if a is None or b is None else True
    if op == 'or': return True if a is True or b is True else None if a is None or b is None else False
    raise ValueError(op)


def compare(value, op, threshold):
    if value is None: return None
    return {'>': lambda: value > threshold, '>=': lambda: value >= threshold,
            '<': lambda: value < threshold, '<=': lambda: value <= threshold,
            '=': lambda: value == threshold, '!=': lambda: value != threshold}[op]()


def raw(row, metric):
    if 'normalized' in row: return row['normalized'][metric]
    value = row[metric]
    return None if value is None else Decimal(value) / (10000 if metric in ('close', 'open') else 1)


def value(call, history, target=None):
    kind = call['kind']; now = history[-1]
    metric = call.get('metric', 'close'); n = call.get('n', 1)
    if kind in ('field', 'rank'): return raw(now, metric)
    if kind == 'query': return target
    if kind == 'count':
        mode, op = call['mode'], call['countOp']
        horizon = n + (op == '=') if mode == 'CONS' else max(20, n)
        if len(history) < horizon: return None
        base = call.get('base', dict(kind='field', metric=metric))
        hits = [compare(value(base, history[:i+1]), call['op'], call['threshold']) is True
                for i in range(len(history)-horizon, len(history))]
        return (all(hits[-n:]) and (op != '=' or not hits[0])) if mode == 'CONS' else compare(sum(hits), op, n)
    if kind in ('cross_above', 'cross_down', 'close_together'):
        a, b = raw(now, 'close'), raw(now, 'open')
        if a is None or b is None: return None
        if kind == 'close_together':
            denominator = max(abs(a), abs(b))
            return None if denominator == 0 else 100 * abs(a-b) <= denominator
        if len(history) < 2: return None
        pa, pb = raw(history[-2], 'close'), raw(history[-2], 'open')
        if pa is None or pb is None: return None
        return (a > b and pa <= pb) if kind == 'cross_above' else (a < b and pa >= pb)
    prices = [r['positions'][metric] if kind=='position' and 'positions' in r else raw(r, metric)
              for r in history[-(n+1 if kind == 'rsi' else n):]]
    if len(prices) < (n+1 if kind == 'rsi' else n) or any(p is None for p in prices): return None
    if kind == 'ma': return sum(prices) / n
    if kind == 'rsi':
        changes = [b-a for a, b in zip(prices, prices[1:])]
        gains = sum(max(d, 0) for d in changes); losses = sum(max(-d, 0) for d in changes)
        return None if losses == 0 else 100 * gains / (gains + losses)
    if kind == 'record_high': return prices[-1] == max(prices)
    if kind == 'record_low': return prices[-1] == min(prices)
    if kind == 'position':
        lo, hi = min(prices), max(prices)
        if lo == hi: return None
        distance = 3 * (prices[-1]-lo)
        return '低' if distance <= hi-lo else '高' if distance >= 2*(hi-lo) else '中'
    raise ValueError(kind)


def render_call(call, date, market):
    kind = call['kind']; metric = METRICS[call.get('metric', 'close')]; n = call.get('n', 1)
    prefix = f"'{market}', '', "
    if kind in ('field', 'ma', 'rsi', 'count'):
        if kind == 'ma': metric = f'{n}日均线'
        if kind == 'rsi': metric = f'RSI({n})'
        count = f"{call['mode']}{call['countOp']}{n}日" if kind == 'count' else ''
        if kind == 'count' and 'base' in call:
            return render_call(call['base'], date, market).replace("'', '')", f"'', '{count}')")
        return f"indicator({prefix}'{metric}', '{date}', '', '', '{count}')"
    if kind in ('position', 'record_high', 'record_low'):
        return f"{kind}({prefix}'{metric}', '{n}日', '{date}', '', '', '')"
    if kind in ('cross_above', 'cross_down', 'close_together'):
        return f"{kind}({prefix}'收盘价', '开盘价', '{date}', '', '')"
    if kind == 'rank': return f"rank({prefix}'{metric}', '{call['direction']}', '{date}', '', '', '')"
    if kind == 'query': return f"queryData('{market}', '{call['keyword']}', '{metric}', '{date}', '')"
    raise ValueError(kind)


def literal(value):
    if isinstance(value, bool): return str(value)
    if isinstance(value, str): return "'" + value + "'"
    return str(value)


def render(expr, calls, date, market):
    op = expr[0]
    if op == 'cmp':
        call = calls[expr[1]]
        comparison, threshold = (call['op'], call['threshold']) if call['kind'] == 'count' else (expr[2], expr[3])
        return render_call(call, date, market) + ' ' + comparison + ' ' + literal(threshold)
    if op == 'callcmp': return render_call(calls[expr[1]], date, market) + ' ' + expr[2] + ' ' + render_call(calls[expr[3]], date, market)
    if op == 'sumcmp': return '(' + render_call(calls[expr[1]], date, market) + '+' + render_call(calls[expr[2]], date, market) + ') > ' + str(expr[3])
    if op == 'not': return 'not (' + render(expr[1], calls, date, market) + ')'
    return '(' + render(expr[1], calls, date, market) + ') ' + op + ' (' + render(expr[2], calls, date, market) + ')'


def evaluate(expr, values):
    op = expr[0]
    if op == 'cmp': return compare(values[expr[1]], expr[2], expr[3])
    if op == 'callcmp': return None if values[expr[3]] is None else compare(values[expr[1]], expr[2], values[expr[3]])
    if op == 'sumcmp':
        a, b = values[expr[1]], values[expr[2]]
        return None if a is None or b is None else a+b > expr[3]
    return sql_bool(op, evaluate(expr[1], values), None if op == 'not' else evaluate(expr[2], values))


def reference(case, source):
    calls = case['calls']; histories = source['histories']; market = case['market']
    histories = {k: h for k, h in histories.items() if not market or k[0] in MARKETS[market]}
    targets = {}
    for i, call in enumerate(calls):
        if call['kind'] == 'query':
            values = [raw(h[-1], call.get('metric', 'close')) for k, h in histories.items()
                      if k[1] == call['keyword'] or source['names'].get(k) == call['keyword']]
            targets[i] = max((v for v in values if v is not None), default=None)
    values = {k: [value(call, h, targets.get(i)) for i, call in enumerate(calls)] for k, h in histories.items()}
    inputs = []
    def add(function, label, missing): inputs.append(dict(function=function, indicator=label, missing=set(missing)))
    for i, call in enumerate(calls):
        kind = call['kind']; metric = METRICS[call.get('metric', 'close')]; n = call.get('n', 1)
        if kind == 'count':
            base = call.get('base', dict(kind='field', metric=call.get('metric', 'close')))
            label = f"{base['n']}日均线" if base['kind'] == 'ma' else f"RSI({base['n']})" if base['kind'] == 'rsi' else metric
            function = 'indicator' if base['kind'] in ('field', 'ma', 'rsi') else base['kind']
            add(function, label, [k for k, h in histories.items() if value(base, h) is None])
            horizon = n + (call['countOp'] == '=') if call['mode'] == 'CONS' else max(20, n)
            add(call['mode'], f'完整 {horizon} 条观察记录的次数条件', [k for k, v in values.items() if v[i] is None])
            add(call['mode']+'（窗口输入）', f'完整 {horizon} 条观察记录的条件输入',
                [k for k, h in histories.items() if len(h) < horizon or any(value(base, h[:i+1]) is None for i in range(len(h)-horizon, len(h)))])
        else:
            function = 'indicator' if kind in ('field', 'ma', 'rsi') else 'querydata' if kind == 'query' else kind
            label = f'{n}日均线' if kind == 'ma' else f'RSI({n})' if kind == 'rsi' else '收盘价 / 开盘价' if kind.startswith('cross_') or kind == 'close_together' else metric
            add(function, label, [k for k, v in values.items() if v[i] is None])
    candidate = [k for k in values if 'pre' not in case or evaluate(case['pre'], values[k]) is True]
    for i, call in enumerate(calls):
        if call['kind'] != 'rank': continue
        direction, method = call['direction'].split(':')
        candidate = [k for k in candidate if values[k][i] is not None]
        ordered = sorted(candidate, key=lambda k: (-values[k][i] if direction == 'desc' else values[k][i], k))
        last = object(); dense = 0; rank = 0
        for row_number, key in enumerate(ordered, 1):
            metric = values[key][i]
            if metric != last: dense += 1; rank = row_number; last = metric
            values[key][i] = row_number if method == 'row_number' else dense if method == 'dense_rank' else rank
    selected = [k for k in candidate if evaluate(case['expr'], values[k]) is True]
    rank_ids = [i for i, c in enumerate(calls) if c['kind'] == 'rank']
    selected.sort(key=(lambda k: (values[k][rank_ids[0]], k)) if rank_ids else None)
    selected = selected[:case.get('limit', len(selected))]
    missing_ext = {k for k, h in histories.items() if not h[-1]['ext']} if any(c.get('metric') == 'net' for c in calls) else set()
    sample_keys = sorted(missing_ext | set().union(*(r['missing'] for r in inputs)))[:20]
    return dict(rows=[list(k) for k in selected], observed=len(histories), missingExtension=missing_ext,
                inputs=inputs, sampleKeys=sample_keys,
                coverageStatus='NO_OBSERVATIONS' if not histories else 'PARTIAL_INPUTS' if missing_ext or any(r['missing'] for r in inputs) else 'COMPLETE_QUERY_INPUTS')


def assess(data, expected):
    quality = data['dataQuality']; samples = quality['unavailableSamples']
    keys = [tuple(row[:2]) for row in samples]
    expected_inputs = Counter((r['function'], r['indicator'], len(r['missing']), tuple(int(k in r['missing']) for k in keys)) for r in expected['inputs'])
    actual_inputs = Counter((r['function'], r['indicator'], r['unavailableSecurities'], tuple(int(row[3+i]) for row in samples)) for i, r in enumerate(quality['inputs']))
    return dict(keysEqual=data['rows'] == expected['rows'], inputsEqual=actual_inputs == expected_inputs,
        samplesEqual=keys == expected['sampleKeys'] and all(int(r[2]) == int(k in expected['missingExtension']) for r, k in zip(samples, keys)),
        observedEqual=quality['observedSecurities'] == expected['observed'],
        missingExtensionEqual=quality['currentMissingExtensionRows'] == len(expected['missingExtension']),
        coverageStatusEqual=quality['coverageStatus'] == expected['coverageStatus'],
        completeResult=not data['truncated'], internalAuthority=quality['officialAcceptanceEligible'] is False and quality['validationLevel'] == 'PROJECT_SCOPED')
