"""Exact decimal projection emulation for in-memory portable DuckDB fixtures.

DuckDB decimal division returns floating point, unlike the Doris projections
being tested. This adapter changes the seven frozen view projections and a
reviewed RSI division in the in-memory execution copy of compiler SQL. Original
compiler artifacts, comparison operators and independent references are untouched.
It is not native Doris correctness or performance evidence.

See https://duckdb.org/docs/current/sql/data_types/numeric#fixed-point-decimals.
"""
from decimal import Decimal, localcontext, ROUND_DOWN
import hashlib
import re


VERSION = 'project-portable-decimal-v2'
# Canonical token hash of the reviewed 002_semantic_view.sql. A changed view
# requires a deliberate review, not a best-effort expression substitution.
TRUSTED_DDL_SHA256 = '2a32552e885800bb1d4681251c207e7ef99262d27ae25c42987c232e56cc5c4d'
PRICE_COLUMNS = dict(lastPx='lastPrice', preClosePx='preClosePrice', openPx='openPrice',
                     highPx='highPrice', lowPx='lowPrice', closePx='closePrice')
AVERAGE_UDF = '_dsl_project_portable_avg_decimal'
PRICE_UDF = '_dsl_project_portable_price_decimal'
RSI_UDF = '_dsl_project_portable_rsi_decimal'
AVERAGE_EXPRESSION = '''CAST(CAST(CAST(b.turnover AS DECIMAL(24,2)) / 100 AS DECIMAL(36,19))
                         / CAST(b.volume AS DECIMAL(20,0)) AS DECIMAL(38,21))'''

# This is the reviewed stock-slot RSI CASE, not a general SQL expression parser.
# The same captured window must occur in COUNT, loss, gain and absolute movement.
# Accept no dynamic identifier, different partition/order/frame or cast precision.
_WINDOW = (r'\(\s*PARTITION\s+BY\s+mktcode\s*,\s*tgtcode\s+ORDER\s+BY\s+bizdate\s+'
           r'ROWS\s+BETWEEN\s+(?:[0-9]+\s+PRECEDING|CURRENT\s+ROW)\s+AND\s+CURRENT\s+ROW\s*\)')
_LOSS = r'SUM\s*\(\s*GREATEST\s*\(\s*-\s*price_delta\s*,\s*0\s*\)\s*\)\s+OVER\s+(?P=window)'
_GAIN = r'SUM\s*\(\s*GREATEST\s*\(\s*price_delta\s*,\s*0\s*\)\s*\)\s+OVER\s+(?P=window)'
_MOVEMENT = r'SUM\s*\(\s*ABS\s*\(\s*price_delta\s*\)\s*\)\s+OVER\s+(?P=window)'
_RSI_CASE = re.compile(
    r'(?P<prefix>\bCASE\s+WHEN\s+COUNT\s*\(\s*price_delta\s*\)\s+OVER\s+'
    rf'(?P<window>{_WINDOW})\s*=\s*(?P<n>[0-9]+)\s+AND\s*\(\s*{_LOSS}\s*\)\s*>\s*0\s+THEN\s+)'
    rf'(?P<numerator>CAST\s*\(\s*\(\s*{_GAIN}\s*\)\s*\*\s*100\s+AS\s+DECIMAL\s*\(\s*30\s*,\s*8\s*\)\s*\))'
    r'\s*/\s*'
    rf'(?P<denominator>NULLIF\s*\(\s*CAST\s*\(\s*{_MOVEMENT}\s+AS\s+DECIMAL\s*\(\s*24\s*,\s*4\s*\)\s*\)\s*,\s*0\s*\))'
    r'(?P<suffix>\s+ELSE\s+NULL\s+END\b)', re.IGNORECASE)
_RSI_CANDIDATE = re.compile(
    # Deliberately broader than the whitelist: renamed/quoted/dynamic operands
    # must not silently fall back to DuckDB's floating-point division.
    r'\bCAST\s*\(\s*\(\s*SUM\s*\(\s*GREATEST\s*\(',
    re.IGNORECASE)


def _sql_code_mask(sql):
    """Keep source offsets, but never match inside literals, identifiers or comments."""
    if not isinstance(sql, str):
        raise ValueError('Expected compiler SQL text')
    result = list(sql)
    i = 0
    while i < len(sql):
        start = i
        if sql[i] in ("'", '"', '`'):
            quote = sql[i]
            i += 1
            while i < len(sql):
                if sql[i] == '\\':
                    i += 2
                elif sql[i] == quote:
                    i += 1
                    if i < len(sql) and sql[i] == quote:
                        i += 1
                    else:
                        break
                else:
                    i += 1
            else:
                raise ValueError('Unterminated quoted compiler SQL fragment')
        elif sql.startswith('--', i) or sql[i] == '#':
            end = sql.find('\n', i)
            i = len(sql) if end < 0 else end
        elif sql.startswith('/*', i):
            end = sql.find('*/', i + 2)
            if end < 0:
                raise ValueError('Unterminated compiler SQL comment')
            i = end + 2
        else:
            i += 1
            continue
        result[start:i] = ' ' * (i - start)
    return ''.join(result)


def _in_memory_only(con):
    if any(row[2] not in (None, '') for row in con.execute('PRAGMA database_list').fetchall()):
        raise ValueError('Portable decimal emulation requires an in-memory fixture only')


def _rsi_ratio(numerator, denominator):
    """Doris DECIMAL(30,8)/DECIMAL(24,4), truncated to DECIMAL(38,12)."""
    if numerator is None or denominator is None:
        return None
    with localcontext() as context:
        context.prec = 80
        for value, scale, integer_places in ((numerator, 8, 22), (denominator, 4, 20)):
            if (not isinstance(value, Decimal) or not value.is_finite() or
                    abs(value) >= Decimal(10) ** integer_places or
                    value != value.quantize(Decimal(1).scaleb(-scale), rounding=ROUND_DOWN)):
                raise ValueError('RSI emulation requires the reviewed finite decimal operand types')
        if denominator == 0:
            return None
        return (numerator / denominator).quantize(Decimal('1e-12'), rounding=ROUND_DOWN)


def adapt_compiler_sql(con, sql, evidence=None):
    """Adapt only the reviewed RSI division in a portable execution copy.

    Unrecognized RSI-shaped candidates fail closed. Non-RSI SQL is unchanged. The
    connection must be the in-memory fixture where install_semantic_views has
    installed the typed UDF; neither native Doris nor raw references use this.
    """
    _in_memory_only(con)
    masked = _sql_code_mask(sql)
    matches = list(_RSI_CASE.finditer(masked))
    candidates = [m.start() for m in _RSI_CANDIDATE.finditer(masked)]
    if candidates != [m.start('numerator') for m in matches]:
        raise ValueError('Unrecognized RSI decimal division shape; portable emulation refused')
    adapted = sql
    for match in reversed(matches):
        n = int(match['n'])
        frame = re.search(r'BETWEEN\s+([0-9]+)\s+PRECEDING', match['window'], re.IGNORECASE)
        preceding = int(frame[1]) if frame else 0
        if not 1 <= n <= 5000 or preceding != n - 1:
            raise ValueError('RSI observation count differs from the reviewed window frame')
        begin, end = match.start('numerator'), match.end('denominator')
        numerator = sql[match.start('numerator'):match.end('numerator')]
        denominator = sql[match.start('denominator'):match.end('denominator')]
        adapted = adapted[:begin] + f'{RSI_UDF}({numerator}, {denominator})' + adapted[end:]
    if evidence is not None:
        evidence['rsiDivisionTransforms'] = evidence.get('rsiDivisionTransforms', 0) + len(matches)
    return adapted


def _tokens(sql):
    if not isinstance(sql, str):
        raise ValueError('Expected trusted semantic-view DDL text')
    uncommented = re.sub(r'--[^\n]*', '', sql)
    return [token.lower() for token in re.findall(r'[A-Za-z_][A-Za-z_0-9]*|[0-9]+(?:\.[0-9]+)?|[^\s]', uncommented)]


def _adapt_ddl(ddl):
    tokens = _tokens(ddl)
    if tokens[:3] == ['use', 'newzl', ';']:
        tokens = tokens[3:]
    canonical = ' '.join(tokens)
    actual_hash = hashlib.sha256(canonical.encode('utf-8')).hexdigest()
    if actual_hash != TRUSTED_DDL_SHA256:
        raise ValueError('Unrecognized semantic-view DDL shape; portable decimal emulation refused')
    average = ' '.join(_tokens(AVERAGE_EXPRESSION))
    if canonical.count(average) != 1:
        raise ValueError('Expected exactly one reviewed raw-BIGINT avgPx projection')
    adapted = canonical.replace(average, f'{AVERAGE_UDF}(b.turnover, b.volume)', 1)
    for raw, alias in PRICE_COLUMNS.items():
        expression = f'CAST(CAST(b.{raw} AS DECIMAL(24,4)) / 10000 AS DECIMAL(19,4)) AS {alias}'
        expression = ' '.join(_tokens(expression))
        if adapted.count(expression) != 1:
            raise ValueError('Expected exactly one reviewed price projection: ' + alias)
        adapted = adapted.replace(expression, f'{PRICE_UDF}(b.{raw}) AS {alias}', 1)
    return adapted, actual_hash


def _raw_bigint(value):
    if not isinstance(value, int) or isinstance(value, bool) or not -(1 << 63) <= value < (1 << 63):
        raise ValueError('Portable decimal projections require signed raw BIGINT inputs')
    return value


def _average_price(turnover, volume):
    if turnover is None or volume is None:
        return None
    turnover, volume = _raw_bigint(turnover), _raw_bigint(volume)
    if volume == 0:
        return None
    with localcontext() as context:
        context.prec = 80
        return (Decimal(turnover) / Decimal(100) / Decimal(volume)).quantize(
            Decimal('1e-21'), rounding=ROUND_DOWN)


def _plain_price(raw):
    if raw is None:
        return None
    with localcontext() as context:
        context.prec = 80
        return (Decimal(_raw_bigint(raw)) / Decimal(10000)).quantize(
            Decimal('1e-4'), rounding=ROUND_DOWN)


def install_semantic_views(con, ddl):
    """Install only reviewed portable views and return their explicit evidence scope.

    The caller must supply an in-memory DuckDB fixture with both raw tables in
    newzl. Refuse persistent/attached source databases before registering UDFs or
    executing DDL, so an independent raw reference cannot be changed accidentally.
    """
    adapted, canonical_hash = _adapt_ddl(ddl)
    _in_memory_only(con)
    raw_types = {row[0].lower(): row[1].upper() for row in
                 con.execute('DESCRIBE newzl.hsj_stock_hq_basic').fetchall()}
    for column in (*PRICE_COLUMNS, 'turnover', 'volume'):
        if raw_types.get(column.lower()) != 'BIGINT':
            raise ValueError('Expected raw BIGINT fixture column: ' + column)
    con.create_function(AVERAGE_UDF, _average_price, ['BIGINT', 'BIGINT'], 'DECIMAL(38,21)',
                        null_handling='special')
    con.create_function(PRICE_UDF, _plain_price, ['BIGINT'], 'DECIMAL(19,4)', null_handling='special')
    con.create_function(RSI_UDF, _rsi_ratio, ['DECIMAL(30,8)', 'DECIMAL(24,4)'], 'DECIMAL(38,12)',
                        null_handling='special')
    con.execute("SET schema='newzl'")
    con.execute(adapted)
    return dict(version=VERSION, purpose='PORTABLE_DORIS_DECIMAL_EMULATION',
                notNativeDorisProof=True, officialAcceptanceEligible=False,
                trustedDdlSha256=canonical_hash,
                projections=dict(avgPx='DECIMAL(38,21)', **{alias: 'DECIMAL(19,4)' for alias in PRICE_COLUMNS.values()}),
                averageRounding='ROUND_DOWN', averagePrecision=80,
                rsiDivision=dict(inputTypes=['DECIMAL(30,8)', 'DECIMAL(24,4)'], outputType='DECIMAL(38,12)',
                    precision=80, rounding='ROUND_DOWN', lossGuard='UNCHANGED_LOSS_SUM_GREATER_THAN_ZERO',
                    sqlScope='Reviewed RSI CASE division in portable execution copies only; original compiler artifacts unchanged'),
                rsiDivisionTransforms=0,
                positionCompanions='UNCHANGED',
                scope='In-memory DuckDB projections and reviewed RSI division emulation only; original compiler artifacts and independent oracles unchanged.')
