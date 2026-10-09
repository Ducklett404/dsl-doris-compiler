"""Frozen T1 combinations and a raw-record oracle, independent of generated SQL.

Monetary literals are CNY, ratios are percent points, and windows count observed
rows.  No SQL/view/registry value is used to obtain the expected security list.
"""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
import json
from pathlib import Path

from check_official_field_acceptance import RAW_COLUMNS
from project_field_reference import observation
from project_matrix_reference import METRICS, reference as raw_reference, render

ROOT = Path(__file__).resolve().parents[2]
MATRIX = ROOT / 'config/acceptance/project-combination-matrix-v1.json'


def cases(path=None):
    suite = json.loads((Path(path) if path else MATRIX).read_text(encoding='utf-8'))
    if not isinstance(suite, list) or not suite:
        raise ValueError('A nonempty frozen matrix list is required')
    names = set()
    for case in suite:
        if case['name'] in names:
            raise ValueError('Duplicate case name: ' + case['name'])
        names.add(case['name'])
        if case['date'] != str(date.fromisoformat(case['date'])):
            raise ValueError('Noncanonical evaluation date')
        for call in case['calls']:
            if call['kind'] not in ('field', 'ma', 'rsi'):
                raise ValueError('T1 matrix contains an unfrozen function')
            if call.get('metric', 'close') not in METRICS:
                raise ValueError('T1 matrix contains an unmapped field')
            if call['kind'] != 'field' and not 1 <= call['n'] <= 20:
                raise ValueError('T1 fixture reference retains at most 20 observations')
        def check_expression(expr):
            if not isinstance(expr, (list, tuple)) or not expr:
                raise ValueError('Malformed hand reference expression')
            op = expr[0]
            if op in ('and', 'or') and len(expr) == 3:
                check_expression(expr[1])
                check_expression(expr[2])
                return
            if op not in ('cmp', 'callcmp', 'sumcmp') or len(expr) != 4:
                raise ValueError('Unfrozen hand reference operator')
            if not isinstance(expr[1], int) or not 0 <= expr[1] < len(case['calls']):
                raise ValueError('Invalid hand reference input index')
            if op == 'sumcmp':
                if not isinstance(expr[2], int) or not 0 <= expr[2] < len(case['calls']):
                    raise ValueError('Invalid arithmetic operand index')
            elif expr[2] not in ('=', '!=', '>', '>=', '<', '<='):
                raise ValueError('Unfrozen comparison operator')
            if op == 'callcmp':
                if not isinstance(expr[3], int) or not 0 <= expr[3] < len(case['calls']):
                    raise ValueError('Invalid comparison operand index')
            elif not isinstance(expr[3], (int, float)) or isinstance(expr[3], bool):
                raise ValueError('T1 threshold must be a numeric literal')
        check_expression(case['expr'])
        # Percent literals are already percent points; monetary values have no
        # implicit 万/亿 conversion in the frozen grammar.
        canonical = render(case['expr'], case['calls'], case['date'], case['market'])
        import re
        without_percent = re.sub(r'(\d+(?:\.\d+)?)%', r'\1', case['dsl'])
        if without_percent != canonical:
            raise ValueError('DSL and hand expression differ: ' + case['name'])
    return suite


def reference(case, source):
    # JSON decimals are represented by Python floats.  Convert textual decimal
    # literal values before comparison; never treat an IEEE float as exact data.
    checked = deepcopy(case)

    def decimal_literals(expr):
        if expr[0] in ('cmp', 'sumcmp'):
            if isinstance(expr[3], float):
                expr[3] = Decimal(str(expr[3]))
        elif expr[0] not in ('callcmp',):
            decimal_literals(expr[1])
            if len(expr) > 2:
                decimal_literals(expr[2])

    checked['expr'] = list(checked['expr'])
    # JSON matrix expressions are lists, but callers may supply immutable tuples.
    def mutable(value):
        return [mutable(v) for v in value] if isinstance(value, (list, tuple)) else value
    checked['expr'] = mutable(checked['expr'])
    decimal_literals(checked['expr'])
    return raw_reference(checked, source)


def fixture():
    """Deterministic raw fixtures: exact thresholds, both sides, unknowns, suspension.

    Three cohorts anchor at close=1 CNY, average=1 CNY, qfq=5 CNY,
    hfq=1 CNY, turn=1 percent point and net=0 CNY with raw +/-1 sides.
    Every raw operand also has its own current-row NULL specimen.
    """
    source_rows, extension_rows, histories = [], [], {}
    for index in range(63):
        market = (0, 1, 103)[index % 3]
        code = f'{index + 1:06}'
        size = (1, 2, 3, 4, 5, 6, 20, 25, 30)[index % 9]
        side = (-1, 0, 1)[(index // 3) % 3]
        history = []
        days = ['2006-01-04', '2018-08-20'] + [
            str(date(2026, 4, 14) - timedelta(days=41 * (size - i - 1)))
            for i in range(size)]
        for i, day in enumerate(days):
            price = 10000 + side if i == len(days) - 1 else (10000, 30000, 20000, 40000)[i % 4]
            raw = dict.fromkeys(RAW_COLUMNS, 10000)
            raw.update(lastPx=price, closePx=price, openPx=price, highPx=price + 10000,
                lowPx=price - 1000, preClosePx=10000, volume=100,
                turnover=10000 + side, turnRatio=10000 + side,
                amplitude=10000 + side, totalShare=1000000, listedShare=500000,
                qfqMulti=2, qfqAdd=3, hfqMulti=3, hfqAdd=-2)
            if i == len(days) - 1 and 27 <= index < 27 + len(RAW_COLUMNS):
                raw[RAW_COLUMNS[index - 27]] = None
            if index == 55:
                raw['volume'] = 0
            if index == 56:
                raw.update(preClosePx=0, turnover=None)
            if index == 57:
                raw.update(closePx=None, qfqMulti=None, qfqAdd=None)
            extension = not (day < '2018-08-20' or index % 8 == 0 and i == len(days) - 1)
            net = -999999 if index % 9 == 0 else None if index % 11 == 0 else side
            raw['net'] = net if extension else None
            actual_day = '2026-04-13' if index == 62 and i == len(days) - 1 else day
            history.append(observation(actual_day, raw, extension))
            source_rows.append((market, code, actual_day, *(raw[k] for k in RAW_COLUMNS)))
            if extension:
                extension_rows.append((market, code, actual_day, net))
        histories[(str(market), code)] = history
        # The future high price must not influence any current-day window.
        source_rows.append((market, code, '2026-04-15', *([999999] * len(RAW_COLUMNS))))

    # Independent raw-DuckDB observation: snapshot stock-20060104-20260414-v1,
    # market=1, code=900924, dates 2026-03-17..2026-04-14.  Only these dates and
    # closePx values were inspected; all other operands remain explicitly NULL,
    # with no invented extension row.  MA3=1061/3000 > MA5=0.3536, but a
    # four-fractional-place AVG would collapse the strict comparison to equality.
    boundary_closes = (
        ('2026-03-17', 3700), ('2026-03-18', 3680), ('2026-03-19', 3600),
        ('2026-03-20', 3590), ('2026-03-23', 3450), ('2026-03-24', 3520),
        ('2026-03-25', 3520), ('2026-03-26', 3480), ('2026-03-27', 3510),
        ('2026-03-30', 3480), ('2026-03-31', 3460), ('2026-04-01', 3490),
        ('2026-04-02', 3470), ('2026-04-03', 3440), ('2026-04-07', 3430),
        ('2026-04-08', 3560), ('2026-04-09', 3510), ('2026-04-10', 3550),
        ('2026-04-13', 3530), ('2026-04-14', 3530),
    )
    boundary_history = []
    for day, price in boundary_closes:
        raw = dict.fromkeys(RAW_COLUMNS)
        raw.update(closePx=price, net=None)
        boundary_history.append(observation(day, raw, extension=False))
        source_rows.append((1, '900924', day, *(raw[k] for k in RAW_COLUMNS)))
    histories[('1', '900924')] = boundary_history
    # A synthetic future close is intentionally not part of the oracle history.
    future = dict.fromkeys(RAW_COLUMNS)
    future['closePx'] = 999999
    source_rows.append((1, '900924', '2026-04-15', *(future[k] for k in RAW_COLUMNS)))

    # Two additional independently inspected raw securities use the same 20
    # trading dates above.  Both have exact RSI(5)=50: raw gain/loss totals are
    # respectively 700/700 and 1500/1500.  Casting individual decimal changes to
    # DOUBLE before AVG can produce 49.99999999999999 and wrongly reject >=50.
    # Only verified closePx/date data is copied; no other source is invented.
    for code, prices in (
            ('000903', (26900, 27000, 26200, 25600, 24300, 24800, 25100,
                24800, 26000, 25800, 26100, 26300, 25900, 25600, 25600,
                26000, 25300, 25300, 25500, 25600)),
            ('300135', (45000, 43600, 43400, 40700, 38800, 39400, 39800,
                40400, 40700, 39900, 38700, 38900, 39200, 36900, 38200,
                38700, 37700, 38100, 38700, 38200))):
        history = []
        for (day, _), price in zip(boundary_closes, prices):
            raw = dict.fromkeys(RAW_COLUMNS)
            raw.update(closePx=price, net=None)
            history.append(observation(day, raw, extension=False))
            source_rows.append((0, code, day, *(raw[k] for k in RAW_COLUMNS)))
        histories[('0', code)] = history
        source_rows.append((0, code, '2026-04-15', *(future[k] for k in RAW_COLUMNS)))
    return dict(sourceRows=source_rows, extensionRows=extension_rows, histories=histories,
        names={},fixturePolicy='RAW_PLUS_MINUS_ONE_NULL_OPERANDS_AND_EXACT_MA_RSI_BOUNDARIES_V3')


def source_on(fixtures, day):
    return dict(names=fixtures.get('names', {}), histories={
        key: [row for row in history if row['date'] <= day]
        for key, history in fixtures['histories'].items()
        if any(row['date'] == day for row in history)})
