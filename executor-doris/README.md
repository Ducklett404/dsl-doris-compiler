# executor-doris

`executor-doris` runs parameterized compiler SQL against Apache Doris, captures `EXPLAIN`, enables Query Profile,
retrieves the profile from the FE HTTP endpoint, and produces a structured performance report.

The report contains scanned bytes, scanned rows, elapsed time, peak memory, partition/tablet pruning, materialized
view hit, index evidence, and feature-table hit. Raw EXPLAIN and Profile text are retained for audit.

Runtime integration requires a MySQL-compatible Doris JDBC driver supplied by the host application. Credentials and
FE endpoints are injected through `JdbcDorisQueryExecutor.ConnectionFactory` and
`QueryProfileCollector.http(...)`; this module does not store credentials.
