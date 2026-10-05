# 项目正确性验收：BLOCKED

快照：`stock-20060104-20260414-v1`；黄金集：`stock-slot-executable-v1.0.1`。

物理行数、日期范围与 manifest 一致，但没有与快照、契约、manifest 哈希完全匹配的 VALIDATED 登记。验收查询未执行，正确率没有计算。诊断查询成功不能替代快照验证。

原因：Exact VALIDATED snapshot/contract/manifest registration is required before acceptance queries
