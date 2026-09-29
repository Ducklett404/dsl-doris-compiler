# stock-slot-v1 注册表与类型系统自测报告

- 日期：2026-09-26
- 注册表版本：`stock-slot-registry-v1.0.0`
- 结论：通过代码、配置加载、安全边界、SQL lowering 和全量语料回归；Doris 在线执行未运行（Docker 引擎未启动）。

## 自动化测试

- Maven：`119` 项通过，`0` 失败，`0` 错误，`0` 跳过。
- 配置扩展证明：测试运行时仅修改 JSON，新增普通字段指标 `配置新增价` 和已有
  `INDUSTRY_AGGREGATE` lowering 的函数 `config_industry_sum`，两者均成功生成 SQL。
- 安全反向测试：未知占位符、动态表名、子查询/SQL 关键字、不受控函数模板、未知 JSON
  属性、未知字段、非法倍率均在加载期被拒绝并返回稳定错误码。
- CLI 外部注册表：使用 `--registry src/main/resources/stock-slot-registry-v1.json` 编译
  `振幅`，正确生成 `(b.amplitude * 1 / 10000)`。

## 5,799 条语料回归

- 总数：`5799`
- 成功解析：`5770`
- 明确不支持：`29`
- 无解释崩溃：`0`

明细见 `summary-registry-v1.json` 和 `classification-registry-v1.jsonl`。

## 未计入通过项

当前 `docker ps` 无法连接 Docker Engine，因此本轮没有重复执行 Doris 在线 SQL。
这不影响注册表加载、类型检查和 SQL 生成自测结论；数据库结果正确性仍应在固定快照环境启动后另行复验。
