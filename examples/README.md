# 可运行示例

从仓库根目录运行命令。构建步骤见[项目首页](../README.md)。

## 正式选股 DSL

[基础筛选](project-basic.dsl)按收盘价选股。[复杂演示](final-demo-complex.dsl)先筛选沪市股票，再按涨跌幅排名。第一条命令展示参数化 SQL，第二条还会输出语义模型、逻辑计划与绑定参数。

```sh
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql examples/project-basic.dsl --format sql
java -jar target/dsl-doris-compiler.jar compile-stock-slot-sql examples/final-demo-complex.dsl --format json
```

[stock-slot](stock-slot/) 收录另外三个正式方言示例。

- [振幅冒烟查询](stock-slot/registry-smoke.dsl)和[60 日均线](stock-slot/performance-long-cycle.dsl)使用同一条 `compile-stock-slot-sql` 命令。
- [复杂槽位表达式](stock-slot/stock-slot-v1.dsl)用于检查行业范围、相对日期、次数与排名的语义解析，可执行 `java -jar target/dsl-doris-compiler.jar compile examples/stock-slot/stock-slot-v1.dsl --dsl-version stock-slot-v1 --format json` 查看结果。

## SCREEN 兼容方言与插件

[基础 SCREEN 示例](screen-v1/basic.dsl)组合财务指标、均线上穿与排序。[插件示例](screen-v1/plugins/plugin.dsl)通过同目录的配置注册 `ABS_CHANGE`。[配置扩展示例](screen-v1/plugins/final-demo-config-only.dsl)使用项目自带的直接字段插件注册 `CLOSE_MIRROR`。

```sh
java -jar target/dsl-doris-compiler.jar compile examples/screen-v1/basic.dsl --format markdown
java -jar target/dsl-doris-compiler.jar compile examples/screen-v1/plugins/plugin.dsl --plugin examples/screen-v1/plugins/custom-plugin.json --format json
java -jar target/dsl-doris-compiler.jar compile examples/screen-v1/plugins/final-demo-config-only.dsl --plugin config/extensions/direct-field/registry-plugin.json --format json
```

[screen-v1/output](screen-v1/output/) 保留基础 SCREEN 示例早期生成的 JSON 工件和 Markdown 展示稿。上面的编译命令可生成当前版本的输出。

## 早期槽位解析原型

[slot-prototype](slot-prototype/) 包含原型语法输入和状态为 `DRAFT` 的指标映射模板。可执行 `java -jar target/dsl-doris-compiler.jar parse-slot examples/slot-prototype/competition_slot.dsl` 查看语法树。`compile-slot-safe` 要求使用经过核对的 `VERIFIED` 映射。
