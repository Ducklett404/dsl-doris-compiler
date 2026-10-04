"""Independently check recorded measurements and render a diagnostic report."""
import argparse
import hashlib
import json
import math
from pathlib import Path


def verify(folder):
    report = json.loads((folder/'diagnostic-summary.json').read_text(encoding='utf-8'))
    measurements = report['measurements']
    assert report['acceptanceEligible'] is False and measurements['acceptanceEligible'] is False
    assert report['temporaryReaderRemoved'] and report['officialRegistryUnchanged']
    assert report['registeredSnapshotsBefore'] == report['registeredSnapshotsAfter'] == 0
    assert measurements['registeredSnapshotsBefore'] == measurements['registeredSnapshotsAfter'] == 0
    iterations = measurements['iterationsPerPath']
    assert measurements['total'] == len(measurements['results']) == measurements['passed']
    assert len({r['id'] for r in measurements['results']}) == measurements['total']
    for result in measurements['results']:
        assert result['status'] == 'PASS' and result['resultEqual'] is True
        samples = result['samples']; assert len(samples) == iterations
        for index, sample in enumerate(samples, 1):
            assert sample['iteration'] == index and sample['resultEqual'] is True
            assert sample['order'] == ('baseline-first' if index % 2 else 'optimized-first')
        for path in ('baseline', 'optimized'):
            values = sorted(s[path+'Millis'] for s in samples)
            assert all(math.isfinite(v) and v > 0 for v in values)
            stats = result[path]
            for name, expected in {'p50Millis': values[math.ceil(iterations*.5)-1],
                    'p95Millis': values[math.ceil(iterations*.95)-1],
                    'minMillis': values[0], 'maxMillis': values[-1]}.items():
                assert math.isclose(stats[name], expected, rel_tol=1e-12)
            assert (folder/result['id']/(path+'-explain.txt')).stat().st_size > 0
        expected_ratio = result['baseline']['p95Millis']/result['optimized']['p95Millis']
        assert math.isclose(result['p95Ratio'], expected_ratio, rel_tol=1e-12)
        rows_path = folder/result['id']/'result-rows.json'
        rows = json.loads(rows_path.read_text(encoding='utf-8'))
        assert len(rows) == result['rows']
        assert hashlib.sha256(rows_path.read_bytes().rstrip(b'\n')).hexdigest() == result['resultSha256']
        sql_same = (folder/result['id']/'baseline.sql').read_bytes() == (folder/result['id']/'optimized.sql').read_bytes()
        bindings_same = json.loads((folder/result['id']/'baseline-bindings.json').read_text()) == json.loads((folder/result['id']/'optimized-bindings.json').read_text())
        assert result['sameSql'] == (sql_same and bindings_same)
    return report


def render(report):
    measurements = report['measurements']; results = measurements['results']
    iterations = measurements['iterationsPerPath']
    lines = ['# 官方数据 Doris 热缓存性能诊断', '',
        f"测量完成：{report['completedAtUtc']}。本次为诊断，正式验收仍为 **BLOCKED**。",
        '', f"{measurements['total']} 类查询中 {measurements['passed']}/{measurements['total']} 类通过结果与排序一致性检查。每条路径重复 {measurements['iterationsPerPath']} 次，共 {sum(len(r['samples'])*2 for r in results)} 次计时查询；每类另做一次双路径预热。",
        '', f'计时包含 JDBC prepare、执行及完整结果读取，不包含编译、进程启动和 EXPLAIN。SQL/查询结果缓存关闭；操作系统和 BE 缓存已预热。基线和优化路径交替先执行，P95 使用最近秩法（{iterations} 次样本取第 {math.ceil(iterations*.95)} 个）。本次没有冷缓存、并发或集群测量。',
        '', f"来源：三表共 {sum(report['sourceRows'].values()):,} 行；{report['dorisVersion']}。原快照未登记，临时 SELECT-only 账号已移除。",
        '', '| 查询 | 行数 | 基线 P95 ms | 优化 P95 ms | P95 比值 | 判断 |',
        '|---|---:|---:|---:|---:|---|']
    for r in results:
        interpretation = 'SQL 相同，不计优化收益' if r['sameSql'] else ('有诊断收益' if r['p95Ratio'] >= 2 else '收益有限，需继续优化')
        lines.append(f"| {r['id']} | {r['rows']} | {r['baseline']['p95Millis']:.3f} | {r['optimized']['p95Millis']:.3f} | {r['p95Ratio']:.3f}x | {interpretation} |")
    if iterations < 30:
        lines += ['', '**此目录为初步试跑，样本少于 30 次，不能用于稳定分位数或优化收益结论。完整测量应查看 hot-30 目录。**']
    ma60 = next(r for r in results if r['id']=='ma60')
    history = next((r for r in results if r['id']=='nineteen-year-history'),None)
    if history and not history['sameSql']:
        lines += ['', f"长期历史高点查询 P95 从 {history['baseline']['p95Millis']:.3f} ms 降到 {history['optimized']['p95Millis']:.3f} ms，耗时比 {history['p95Ratio']:.3f}x。该结果仅适用于本矩阵和本机热缓存，不能推导冷缓存或并发性能。"]
    lines += ['', f"60 日均线 P95 从 {ma60['baseline']['p95Millis']:.3f} ms 降到 {ma60['optimized']['p95Millis']:.3f} ms，耗时比为 {ma60['p95Ratio']:.3f}x。收益仅适用于本快照、本日期、当前矩阵条件和此机器。",
        '', '## 执行计划发现与下一步', '',
        '1. MA60 特征表路径值得保留。先扩展到多日期及其他证券范围复验，再考虑增量维护；任何新特征都需绑定快照并验证结果。',
        '2. MA20、MA120、MA250 及区间高低点计划仍读取多年基础行情并排序窗口。不能用固定日历天数截断证券历史来代替观察行窗口，避免停牌、缺值和稀疏证券改变语义。优先按既有窗口规则构建独立特征，或设计保留足够历史行的访问路径。',
        '3. 基础表计划提示列统计未知。可在后续独立实验中补充统计并重新测量，不能把两条相同 SQL 的随机差异当作优化。',
        '4. 关联规则明确、新快照验证通过后，补齐正式冷缓存、热缓存及并发矩阵和外部盲测。',
        '', '## 证据与适用范围', '',
        '- [机器结果与来源哈希](diagnostic-summary.json)、[逐次 JDBC 测量](jdbc-results.json)、[运行进度](progress.log)。每个查询目录保存两套 SQL、绑定参数、EXPLAIN 和完整输出行。',
        '- 校验脚本独立重算样本数量、交替次序、P50/P95、比值及结果文件哈希，核对账号清理和登记表未变化。',
        '- 验证的是每条 DSL 条件的完整返回结果；带 LIMIT 的用例按其限制比较，其他用例比较全部行。空结果用例的一致性不能证明所有数据边界。',
        f"- 官方数据审计仍为 {report['sourceAuditStatus']}：{report['unmatchedExtensionRows']:,} 条衍生记录未关联基础行情。字段口径仍待确认，因此此报告不改变正式快照或验收状态。", '']
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('folder', type=Path)
    args = parser.parse_args(); report = verify(args.folder)
    (args.folder/'性能诊断与下一步.md').write_text(render(report), encoding='utf-8')
    print('PASS: all samples, statistics, row hashes and cleanup independently verified')


if __name__ == '__main__': main()
