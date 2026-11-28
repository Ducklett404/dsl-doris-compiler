# 项目交付清单

11 月 29 日的原生 Doris 测试覆盖随包版和跨证券窗口优化版。验收总览列出每个赛题指标对应的版本、原始样本和复核命令。[验收总览](../../reports/competition-review/2026-11-29/README.md) · [赛题对照](competition-readiness.md)

| 交付内容 | 入口 | 当前状态 |
|---|---|---|
| 比赛要求与统一状态 | [赛题对照](competition-readiness.md)、[项目状态](../project-status.md) | 实现、历史证据、当前缺口分别披露 |
| 技术报告、数据说明、算法说明、测试结果与案例 | 本机源码同级目录 `提交文档/` | Word 提交材料单独保存；GitHub 上的实测结果见[验收目录](../../reports/competition-review/2026-11-29/) |
| 项目概览与目录 | [README](../../README.md)、[目录说明](../project-layout.md) | 已整理 |
| 源码与测试 | `src/`、`executor-doris/` | 已合入 main |
| Windows／Unix 构建 | `mvnw.cmd`／`mvnw`，`scripts/build-test-start.ps1` | Java 21、Maven 3.9+ |
| 构建测试与 JAR 身份 | [专项构建与数据身份](../../reports/competition-review/2026-11-29/lookup-window/environment.json)、[10 月构建自测](self-test.md) | 11 月专项主模块有 336 项在常规构建中通过，另 8 项在真实 Doris 集成环境通过 |
| CLI／HTTP／Docker | [运行手册](../runtime-guide.md) | 可构建、可演示；数据库需准备环境 |
| 架构与扩展 | [编译器架构](../compiler-architecture.md)、[插件指南](../registry-plugin-guide.md) | 已实现 |
| 项目能力与语义边界 | [能力说明](../project-capabilities-v1.md)、[冻结范围](../phase1-data-indicator-scope-v1.md) | 以冻结范围为准 |
| 示例 | `examples/project-basic.dsl`、`examples/final-demo-complex.dsl`、`examples/basic.dsl` | 本轮 JAR 编译通过 |
| 项目便携验收与打包 | `scripts/doris/run_project_acceptance.py`、`scripts/doris/package_project_delivery.py` | 按源码与 JAR 哈希绑定证据 |
| GitHub 可下载 JAR／ZIP | `.github/workflows/project-delivery.yml` | 推送后自动构建，成功运行生成 Artifacts |
| 真实数据与正式验收 | [项目验收说明](../project-scoped-validation.md)、[正式问题路线图](../正式验收问题解决路线图.md) | 项目复杂查询已在真实 Doris 复测；赛事正式门禁执行 0 例 |
| 历史测试与诊断 | `reports/`、`docs/history/` | 保留原日期和原工件身份，不作为本轮结果 |

## 取得可运行成果

本机构建输出为 `target/dsl-doris-compiler.jar`。GitHub 的 `project-delivery` 工作流成功后，在该次运行的 Artifacts 下载 `project-delivery-<提交 SHA>`，包含 JAR、`project-delivery.zip`、`delivery-manifest.json` 和外层 `SHA256SUMS`。

ZIP 内含实际源码、配置、脚本、文档、与本批证据匹配的 JAR，以及本批便携验收结果。它不携带原始 CSV、审计数据库、工具缓存或私有凭据。便携验收不声称真实数据和正式验收已通过。下载和恢复步骤见 [目录与交付说明](../project-layout.md)、[项目能力说明](../project-capabilities-v1.md)。

## 复测顺序

1. 运行 `mvnw.cmd -B package`（Unix 使用 `./mvnw -B package`）。
2. 安装 `scripts/doris/requirements-selftest.txt`，运行项目便携验收。
3. 准备原始数据、独立参考和专用 Doris 环境后，再显式运行真实项目验收；具体参数见能力说明。
4. 选定完成的本批证据，执行交付脚本并核对逐文件校验和。

历史正式演示说明仍见 [final-demo.md](../final-demo.md)；历史的“最终交付报告”已注明其原批次口径，不替代当前自测与正式验收。
