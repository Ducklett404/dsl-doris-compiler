# 指标注册与插件开发说明

## 正式指标注册

正式表、字段、指标和函数配置位于 `src/main/resources/stock-slot-registry-v1.json`。每个指标必须
声明名称/别名、类型、单位、倍率、允许聚合、来源表字段、时间粒度、最大回看、复权、空值、
哨兵值和 lowering。每个函数必须声明参数/返回类型、时间和空值合同以及 lowering 参数。

支持的安全模板仅有白名单形式，例如 `{alias}.{field}` 与
`NULLIF({alias}.{field},{sentinel})`。加载器拒绝未知占位符、动态表名、子查询、注释、分号和
任意 SQL。新增已有 lowering 类型时必须补正向和反向测试向量。

## 三种零核心改动扩展

| 类型 | 示例目录 | 允许改动 |
|---|---|---|
| 直接字段指标 | `config/extensions/direct-field` | 注册配置与向量 |
| 模板计算指标 | `config/extensions/template-calculation` | 已登记模板参数与向量 |
| 已有窗口 lowering | `config/extensions/window-lowering` | 窗口参数与向量 |

统一验收：

```powershell
mvn.cmd -Dtest=ConfigOnlyExtensionAcceptanceTest test
./scripts/ci/verify-config-only-extension.ps1 -BaseRef origin/main -HeadRef HEAD
```

CI 会拒绝这些扩展同时修改 `src/main/java`、ANTLR 文法或编译流水线。

## 新语义插件

全新计算语义不能伪装成模板。应新建 `plugins/<plugin-id>/` SPI 模块，在模块内部实现并测试
lowering；允许增加插件代码，但不得修改既有编译流水线或核心类。插件仍须使用参数化值、受控
标识符，并声明类型、单位、窗口及空值语义。

完整注册表字段及加载安全规则见 `docs/stock-slot-registry-v1.md`；零核心改动门禁细节见
`docs/config-only-extension-acceptance.md`。
