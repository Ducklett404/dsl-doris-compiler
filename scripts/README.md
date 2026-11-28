# 从哪个脚本开始

以下路径以仓库根目录为起点。

| 目的 | 入口 |
|---|---|
| 安装 Maven、运行本机自测 | [安装 Maven](bootstrap-maven.sh)、[Unix 自测](self-test.sh)、[Windows 项目测试](test-all.ps1) |
| 运行本批项目验收并生成交付包 | [验收入口](doris/run_project_acceptance.py)、[打包与校验](doris/package_project_delivery.py)、[运行手册](../docs/runtime-guide.md) |
| 复核已发布的比赛成绩 | [验收总览中的三条离线命令](../reports/competition-review/2026-11-29/README.md#如何复核)、[各批报告及原始证据](../reports/README.md) |
| 准备外部 DSL 语料 | [语料工具和依赖](corpus/)、[输入格式和复现命令](../docs/competition/WEEK1_BASELINE.md) |
| 用黄金集和边界夹具校验正确性 | [正确性脚本](accuracy/)、[固定输入与运行步骤](../accuracy/README.md) |
| 装载 Doris 数据、核对来源与独立预期 | [数据装载说明](../data/doris/README.md)、[快照工具](doris/snapshot_tool.py)、[来源核验](doris/validate_project_sources.py)、[独立参考库](doris/build_reference_duckdb.py) |
| 检查窗口、排名和资源限制 | [窗口边界](doris/check_project_window_boundaries.py)、[排名组合](doris/check_project_rank_combinations.py)、[资源稳定性](doris/check_project_resource_stability.py) |
| 运行演示 | [演示脚本](run-final-demo.ps1)、[数据与操作步骤](../docs/final-demo.md) |
| 核查 CI 的门禁和触发条件 | [冻结范围与配置扩展检查](ci/)、[GitHub 工作流](../.github/workflows/) |

`doris/` 内的 Java 探针供同目录的验收脚本调用。复现特定批次时，使用该批报告指定的源码提交、数据快照和命令。
