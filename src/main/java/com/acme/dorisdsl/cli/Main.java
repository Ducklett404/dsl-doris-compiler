package com.acme.dorisdsl.cli;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.rewrite.RuleCatalogLoader;
import com.acme.dorisdsl.server.CompileHttpServer;
import com.acme.dorisdsl.stockslot.StockSlotCorpusAuditor;
import com.acme.dorisdsl.stockslot.CompilerPerformanceBenchmark;
import com.acme.dorisdsl.stockslot.CompilerPerformanceDefinition;
import com.acme.dorisdsl.stockslot.CompilerPerformanceMarkdown;
import com.acme.dorisdsl.stockslot.DorisBenchmarkReport;
import com.acme.dorisdsl.stockslot.DorisBenchmarkMatrixDefinition;
import com.acme.dorisdsl.stockslot.DorisBenchmarkMatrixMarkdown;
import com.acme.dorisdsl.stockslot.DorisBenchmarkMatrixRunner;
import com.acme.dorisdsl.stockslot.DorisExecutionMarkdownRenderer;
import com.acme.dorisdsl.stockslot.DorisExecutionPolicy;
import com.acme.dorisdsl.stockslot.DorisQueryExecutor;
import com.acme.dorisdsl.stockslot.StockSlotRegistryLoader;
import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import com.acme.dorisdsl.util.JsonSupport;
import com.acme.dorisdsl.util.MarkdownRenderer;
import picocli.CommandLine;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.List;
import java.util.concurrent.Callable;

@CommandLine.Command(name = "dsl-doris-compiler", mixinStandardHelpOptions = true, version = DslCompiler.VERSION,
        description = "Compile stock-screening DSL to parameterized Apache Doris SQL",
        subcommands = {Main.CompileCommand.class, Main.ServeCommand.class, Main.BenchmarkCommand.class,
                Main.AuditCorpusCommand.class, Main.CompileStockSlotSqlCommand.class,
                Main.ExecuteStockSlotSqlCommand.class, Main.BenchmarkDorisCommand.class,
                Main.ServeDorisCommand.class, Main.BenchmarkMatrixCommand.class,
                Main.BenchmarkStockSlotCompilerCommand.class})
public final class Main implements Runnable {
    public static void main(String[] args) { System.exit(new CommandLine(new Main()).execute(args)); }
    @Override public void run() { CommandLine.usage(this, System.out); }

    static DslCompiler compiler(Path registry, List<Path> plugins) {
        return compiler(registry, plugins, null, null);
    }

    static DslCompiler compiler(Path registry, List<Path> plugins, Path rules, String ruleVersion) {
        var loader = new RegistryLoader();
        var ruleCatalog = rules == null ? new RuleCatalogLoader().loadDefault(DslCompiler.VERSION)
                : new RuleCatalogLoader().load(rules, DslCompiler.VERSION);
        if (ruleVersion != null && !ruleVersion.isBlank()) ruleCatalog.activate(ruleVersion);
        return new DslCompiler(registry == null ? loader.loadDefault(plugins) : loader.load(registry, plugins), ruleCatalog);
    }

    static abstract class RegistryOptions {
        @CommandLine.Option(names = "--registry", description = "Base registry JSON (defaults to bundled registry)") Path registry;
        @CommandLine.Option(names = "--plugin", description = "Plugin JSON; repeatable") List<Path> plugins = new ArrayList<>();
        @CommandLine.Option(names = "--rules", description = "Declarative rule catalog JSON (defaults to bundled catalog)") Path rules;
        @CommandLine.Option(names = "--rule-version", description = "Activate or roll back to a compatible rule version") String ruleVersion;
    }

    @CommandLine.Command(name = "compile", mixinStandardHelpOptions = true, description = "Compile one DSL file")
    static final class CompileCommand extends RegistryOptions implements Callable<Integer> {
        @CommandLine.Parameters(index = "0", description = "DSL file") Path input;
        @CommandLine.Option(names = {"-f", "--format"}, defaultValue = "markdown", description = "markdown|json|sql") String format;
        @CommandLine.Option(names = {"-o", "--output"}, description = "Output file; defaults to stdout") Path output;
        @CommandLine.Option(names = "--dsl-version", defaultValue = DslCompiler.SCREEN_DSL_VERSION,
                description = "screen-v1|stock-slot-v1") String dslVersion;

        @Override public Integer call() {
            try {
                String source = Files.readString(input, StandardCharsets.UTF_8);
                var artifact = compiler(registry, plugins, rules, ruleVersion).compile(source, dslVersion);
                String rendered = switch (format.toLowerCase()) {
                    case "json" -> JsonSupport.MAPPER.writeValueAsString(artifact);
                    case "sql" -> {
                        if (artifact instanceof com.acme.dorisdsl.compiler.CompilationArtifact legacy) yield legacy.sql();
                        throw new CompileException("FORMAT_UNSUPPORTED",
                                "stock-slot-v1 parsing artifacts do not contain SQL", 1, 1);
                    }
                    case "markdown", "md" -> artifact instanceof com.acme.dorisdsl.compiler.CompilationArtifact legacy
                            ? MarkdownRenderer.render(legacy) : JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(artifact);
                    default -> throw new IllegalArgumentException("Unknown format: " + format);
                };
                if (output == null) System.out.println(rendered);
                else Files.writeString(output, rendered + System.lineSeparator(), StandardCharsets.UTF_8);
                return 0;
            } catch (CompileException e) {
                System.err.printf("%s at %d:%d: %s%n", e.code(), e.line(), e.column(), e.getMessage());
                return 2;
            } catch (Exception e) {
                System.err.println("compile_failed: " + e.getMessage());
                return 1;
            }
        }
    }

    @CommandLine.Command(name = "audit-corpus", description = "Classify extracted stock-slot-v1 JSONL corpus")
    static final class AuditCorpusCommand implements Callable<Integer> {
        @CommandLine.Parameters(index = "0", description = "JSONL containing row and dsl fields") Path input;
        @CommandLine.Option(names = {"-o", "--output"}, required = true, description = "Per-row JSONL result") Path output;
        @CommandLine.Option(names = "--summary", required = true, description = "Summary JSON") Path summary;

        @Override public Integer call() throws Exception {
            var result = new StockSlotCorpusAuditor().audit(input, output);
            if (summary.toAbsolutePath().getParent() != null) Files.createDirectories(summary.toAbsolutePath().getParent());
            Files.writeString(summary, JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(result)
                    + System.lineSeparator(), StandardCharsets.UTF_8);
            System.out.println(JsonSupport.MAPPER.writeValueAsString(result));
            return result.unexplained() == 0 ? 0 : 3;
        }
    }

    @CommandLine.Command(name = "compile-stock-slot-sql",
            description = "Lower the accepted stock-slot-v1 executable subset to parameterized Doris SQL")
    static final class CompileStockSlotSqlCommand implements Callable<Integer> {
        @CommandLine.Parameters(index = "0", description = "stock-slot-v1 DSL file") Path input;
        @CommandLine.Option(names = {"-f", "--format"}, defaultValue = "json", description = "json|sql") String format;
        @CommandLine.Option(names = {"-o", "--output"}, description = "Output file; defaults to stdout") Path output;
        @CommandLine.Option(names = "--registry", description = "stock-slot-v1 registry JSON; defaults to bundled registry") Path registry;

        @Override public Integer call() {
            try {
                var loader = new StockSlotRegistryLoader();
                var stockRegistry = registry == null ? loader.loadDefault() : loader.load(registry);
                var artifact = new StockSlotSqlCompiler(stockRegistry).compile(Files.readString(input, StandardCharsets.UTF_8));
                String rendered = switch (format.toLowerCase()) {
                    case "json" -> JsonSupport.MAPPER.writeValueAsString(artifact);
                    case "sql" -> artifact.sql();
                    default -> throw new IllegalArgumentException("Unknown format: " + format);
                };
                if (output == null) System.out.println(rendered);
                else Files.writeString(output, rendered + System.lineSeparator(), StandardCharsets.UTF_8);
                return 0;
            } catch (CompileException e) {
                System.err.printf("%s at %d:%d: %s%n", e.code(), e.line(), e.column(), e.getMessage());
                return 2;
            } catch (Exception e) {
                System.err.println("compile_failed: " + e.getMessage());
                return 1;
            }
        }
    }

    static abstract class DorisOptions {
        @CommandLine.Option(names = "--host", defaultValue = "127.0.0.1") String host;
        @CommandLine.Option(names = "--port", defaultValue = "9030") int port;
        @CommandLine.Option(names = "--database", defaultValue = "newzl") String database;
        @CommandLine.Option(names = "--user", defaultValue = "dsl_runtime_reader") String user;
        @CommandLine.Option(names = "--password-env", defaultValue = "DORIS_PASSWORD") String passwordEnv;
        @CommandLine.Option(names = "--allow-empty-password", description = "Allow an empty password (local test instances only)") boolean allowEmptyPassword;
        @CommandLine.Option(names = "--registry", description = "stock-slot-v1 registry JSON; defaults to bundled registry") Path registry;
        @CommandLine.Option(names = "--max-scan-rows", defaultValue = "1000000") long maxScanRows;
        @CommandLine.Option(names = "--max-return-rows", defaultValue = "1000") int maxReturnRows;
        @CommandLine.Option(names = "--max-exec-memory-bytes", defaultValue = "536870912") long maxExecMemoryBytes;
        @CommandLine.Option(names = "--max-queue-wait-ms", defaultValue = "2000") int maxQueueWaitMillis;

        String password() {
            String password = System.getenv(passwordEnv);
            if ((password == null || password.isEmpty()) && allowEmptyPassword) return "";
            if (password == null || password.isEmpty())
                throw new IllegalArgumentException("Set password environment variable: " + passwordEnv);
            return password;
        }

        String jdbcUrl() {
            if (!host.matches("[A-Za-z0-9._:-]+") || !database.matches("[A-Za-z_][A-Za-z0-9_]*")
                    || port < 1 || port > 65535) throw new IllegalArgumentException("Invalid Doris connection target");
            return "jdbc:mysql://" + host + ":" + port + "/" + database
                    + "?useUnicode=true&characterEncoding=UTF-8&useSSL=false&allowPublicKeyRetrieval=true"
                    + "&connectTimeout=5000&socketTimeout=125000";
        }

        com.acme.dorisdsl.stockslot.StockSlotRegistry stockRegistry() {
            var loader = new StockSlotRegistryLoader();
            return registry == null ? loader.loadDefault() : loader.load(registry);
        }

        DorisExecutionPolicy controlledPolicy(int timeoutSeconds) {
            return new DorisExecutionPolicy(timeoutSeconds, maxScanRows, maxReturnRows,
                    maxExecMemoryBytes, maxQueueWaitMillis, true);
        }
    }

    @CommandLine.Command(name = "execute-stock-slot-sql",
            description = "Compile stock-slot-v1 and execute its parameterized SELECT on Doris")
    static final class ExecuteStockSlotSqlCommand extends DorisOptions implements Callable<Integer> {
        @CommandLine.Parameters(index = "0", description = "stock-slot-v1 DSL file") Path input;
        @CommandLine.Option(names = "--timeout-seconds", defaultValue = "10") int timeoutSeconds;
        @CommandLine.Option(names = "--max-rows", defaultValue = "1000") int maxRows;
        @CommandLine.Option(names = "--snapshot-id", defaultValue = "stock-20060104-20260414-v1") String snapshotId;
        @CommandLine.Option(names = {"-f", "--format"}, defaultValue = "json", description = "json|markdown") String format;
        @CommandLine.Option(names = {"-o", "--output"}) Path output;

        @Override public Integer call() {
            try (var executor = new DorisQueryExecutor(jdbcUrl(), user, password(), stockRegistry(), controlledPolicy(timeoutSeconds))) {
                executor.ping();
                var result = executor.execute(Files.readString(input, StandardCharsets.UTF_8), snapshotId, timeoutSeconds, maxRows);
                String rendered = switch (format.toLowerCase()) {
                    case "json" -> JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(result);
                    case "markdown", "md" -> DorisExecutionMarkdownRenderer.render(result);
                    default -> throw new IllegalArgumentException("Unknown format: " + format);
                };
                if (output == null) System.out.println(rendered);
                else {
                    if (output.toAbsolutePath().getParent() != null) Files.createDirectories(output.toAbsolutePath().getParent());
                    Files.writeString(output, rendered + System.lineSeparator(), StandardCharsets.UTF_8);
                }
                return result.queryMillis() <= 10_000.0 ? 0 : 4;
            } catch (CompileException e) {
                System.err.printf("%s at %d:%d: %s%n", e.code(), e.line(), e.column(), e.getMessage());
                return 2;
            } catch (Exception e) {
                System.err.println("doris_execution_failed: " + e.getMessage());
                return 3;
            }
        }
    }

    @CommandLine.Command(name = "serve-doris", description = "Start compile and controlled Doris execution HTTP APIs")
    static final class ServeDorisCommand extends DorisOptions implements Callable<Integer> {
        @CommandLine.Option(names = "--bind-host", defaultValue = "127.0.0.1") String bindHost;
        @CommandLine.Option(names = "--http-port", defaultValue = "8080") int httpPort;
        @CommandLine.Option(names = "--timeout-seconds", defaultValue = "10") int timeoutSeconds;

        @Override public Integer call() throws Exception {
            try (var executor = new DorisQueryExecutor(jdbcUrl(), user, password(), stockRegistry(), controlledPolicy(timeoutSeconds));
                 var server = new CompileHttpServer(compiler(null, List.of()),
                         (dsl, snapshot, rows) -> executor.execute(dsl, snapshot, timeoutSeconds, rows),
                         bindHost, httpPort)) {
                executor.ping();
                server.start();
                System.out.printf("Listening on http://%s:%d (/compile, /execute)%n", bindHost, server.port());
                Thread.currentThread().join();
            }
            return 0;
        }
    }

    @CommandLine.Command(name = "benchmark-doris",
            description = "Benchmark compilation and Doris query latency on one fixed-snapshot DSL")
    static final class BenchmarkDorisCommand extends DorisOptions implements Callable<Integer> {
        @CommandLine.Parameters(index = "0", description = "stock-slot-v1 DSL file") Path input;
        @CommandLine.Option(names = "--snapshot-id", defaultValue = "stock-20060104-20260414-v1") String snapshotId;
        @CommandLine.Option(names = "--warmup", defaultValue = "3") int warmup;
        @CommandLine.Option(names = "--iterations", defaultValue = "20") int iterations;
        @CommandLine.Option(names = "--timeout-seconds", defaultValue = "10") int timeoutSeconds;
        @CommandLine.Option(names = "--baseline-timeout-seconds", defaultValue = "120") int baselineTimeoutSeconds;
        @CommandLine.Option(names = {"-o", "--output"}) Path output;

        @Override public Integer call() {
            try {
                if (warmup < 0 || iterations < 1) throw new IllegalArgumentException("warmup >= 0 and iterations >= 1 are required");
                String dsl = Files.readString(input, StandardCharsets.UTF_8);
                double[] compile = new double[iterations];
                double[] query = new double[iterations];
                double[] baseline = new double[iterations];
                int rows = 0;
                try (var executor = new DorisQueryExecutor(jdbcUrl(), user, password(), stockRegistry())) {
                    executor.ping();
                    executor.requireValidatedSnapshot(snapshotId);
                    for (int i = 0; i < warmup; i++) {
                        executor.execute(dsl, timeoutSeconds, 0);
                        executor.measureFullScanBaseline(baselineTimeoutSeconds);
                    }
                    for (int i = 0; i < iterations; i++) {
                        var result = executor.execute(dsl, timeoutSeconds, 0);
                        compile[i] = result.compileMillis();
                        query[i] = result.queryMillis();
                        var baselineResult = executor.measureFullScanBaseline(baselineTimeoutSeconds);
                        baseline[i] = baselineResult.millis();
                        if (!result.rows().equals(baselineResult.rows()))
                            throw new IllegalStateException("Accelerated query result differs from the full-scan baseline");
                        rows = result.rows().size();
                    }
                }
                Arrays.sort(compile);
                Arrays.sort(query);
                Arrays.sort(baseline);
                var compileStats = percentiles(compile);
                var queryStats = percentiles(query);
                var baselineStats = percentiles(baseline);
                double speedup = baselineStats.p95Millis() / queryStats.p95Millis();
                boolean compilePass = compileStats.p95Millis() < 50.0;
                boolean queryPass = queryStats.p95Millis() <= 10_000.0;
                boolean speedupPass = speedup >= 10.0;
                var report = new DorisBenchmarkReport(snapshotId, warmup, iterations, rows, compileStats, queryStats,
                        baselineStats, speedup, compilePass, queryPass, speedupPass,
                        compilePass && queryPass && speedupPass);
                String json = JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(report);
                if (output == null) System.out.println(json);
                else {
                    if (output.toAbsolutePath().getParent() != null) Files.createDirectories(output.toAbsolutePath().getParent());
                    Files.writeString(output, json + System.lineSeparator(), StandardCharsets.UTF_8);
                }
                return report.passed() ? 0 : 4;
            } catch (Exception e) {
                System.err.println("doris_benchmark_failed: " + e.getMessage());
                return 3;
            }
        }

        private DorisBenchmarkReport.Percentiles percentiles(double[] values) {
            return new DorisBenchmarkReport.Percentiles(at(values, 0.50), at(values, 0.95), at(values, 0.99), values[values.length - 1]);
        }
        private double at(double[] values, double percentile) {
            return values[Math.min(values.length - 1, (int) Math.ceil(values.length * percentile) - 1)];
        }
    }

    @CommandLine.Command(name = "benchmark-matrix", mixinStandardHelpOptions = true,
            description = "Run 30+ hot/process-cold full-scan versus optimized Doris benchmark samples")
    static final class BenchmarkMatrixCommand extends DorisOptions implements Callable<Integer> {
        @CommandLine.Option(names = "--matrix", defaultValue = "benchmarks/doris-matrix-v1.json") Path matrix;
        @CommandLine.Option(names = "--iterations", defaultValue = "30") int iterations;
        @CommandLine.Option(names = "--cold-restart-container", defaultValue = "doris") String coldContainer;
        @CommandLine.Option(names = "--evidence-dir", defaultValue = "reports/benchmark-matrix/evidence") Path evidenceDir;
        @CommandLine.Option(names = "--json-output", defaultValue = "reports/benchmark-matrix/report.json") Path jsonOutput;
        @CommandLine.Option(names = "--markdown-output", defaultValue = "reports/benchmark-matrix/report.md") Path markdownOutput;

        @Override public Integer call() {
            try {
                var definition = JsonSupport.MAPPER.readValue(matrix.toFile(), DorisBenchmarkMatrixDefinition.class);
                var report = new DorisBenchmarkMatrixRunner(jdbcUrl(), user, password(), stockRegistry())
                        .run(definition, iterations, evidenceDir, coldContainer);
                if (jsonOutput.toAbsolutePath().getParent() != null) Files.createDirectories(jsonOutput.toAbsolutePath().getParent());
                if (markdownOutput.toAbsolutePath().getParent() != null) Files.createDirectories(markdownOutput.toAbsolutePath().getParent());
                Files.writeString(jsonOutput, JsonSupport.MAPPER.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(report) + System.lineSeparator(), StandardCharsets.UTF_8);
                Files.writeString(markdownOutput, DorisBenchmarkMatrixMarkdown.render(report), StandardCharsets.UTF_8);
                System.out.println(markdownOutput.toAbsolutePath());
                return 0;
            } catch (Exception e) {
                System.err.println("benchmark_matrix_failed: " + e.getMessage());
                return 3;
            }
        }
    }

    @CommandLine.Command(name = "serve", description = "Start the JSON compile API")
    static final class ServeCommand extends RegistryOptions implements Callable<Integer> {
        @CommandLine.Option(names = "--host", defaultValue = "127.0.0.1") String host;
        @CommandLine.Option(names = "--port", defaultValue = "8080") int port;

        @Override public Integer call() throws Exception {
            try (var server = new CompileHttpServer(compiler(registry, plugins, rules, ruleVersion), host, port)) {
                server.start();
                System.out.printf("Listening on http://%s:%d%n", host, server.port());
                Thread.currentThread().join();
            }
            return 0;
        }
    }

    @CommandLine.Command(name = "benchmark", description = "Measure in-process compiler latency")
    static final class BenchmarkCommand extends RegistryOptions implements Callable<Integer> {
        @CommandLine.Parameters(index = "0", description = "DSL file") Path input;
        @CommandLine.Option(names = "--warmup", defaultValue = "500") int warmup;
        @CommandLine.Option(names = "--iterations", defaultValue = "5000") int iterations;

        @Override public Integer call() throws Exception {
            if (warmup < 0 || iterations < 100) throw new IllegalArgumentException("iterations must be >= 100 and warmup >= 0");
            String source = Files.readString(input, StandardCharsets.UTF_8);
            var compiler = compiler(registry, plugins, rules, ruleVersion);
            for (int i = 0; i < warmup; i++) compiler.compile(source);
            long[] samples = new long[iterations];
            for (int i = 0; i < iterations; i++) {
                long start = System.nanoTime();
                compiler.compile(source);
                samples[i] = System.nanoTime() - start;
            }
            Arrays.sort(samples);
            System.out.printf("iterations=%d p50=%.3fms p95=%.3fms p99=%.3fms%n", iterations,
                    millis(samples[(int) (iterations * 0.50)]), millis(samples[(int) (iterations * 0.95)]),
                    millis(samples[Math.min(iterations - 1, (int) (iterations * 0.99))]));
            return 0;
        }

        private static double millis(long nanos) { return nanos / 1_000_000.0; }
    }

    @CommandLine.Command(name = "benchmark-stock-slot-compiler", mixinStandardHelpOptions = true,
            description = "Benchmark all formal stock-slot-v1 compiler phases on a complex corpus")
    static final class BenchmarkStockSlotCompilerCommand implements Callable<Integer> {
        @CommandLine.Option(names = "--corpus", defaultValue = "benchmarks/compiler/stock-slot-complex-v1.json") Path corpus;
        @CommandLine.Option(names = "--stock-registry", description = "stock-slot-v1 registry JSON; defaults to bundled registry") Path stockRegistry;
        @CommandLine.Option(names = "--warmup", defaultValue = "1000") int warmup;
        @CommandLine.Option(names = "--iterations", defaultValue = "5000") int iterations;
        @CommandLine.Option(names = "--p95-threshold-ms", defaultValue = "50") double p95ThresholdMillis;
        @CommandLine.Option(names = "--json-output", defaultValue = "reports/compiler-performance/latest.json") Path jsonOutput;
        @CommandLine.Option(names = "--markdown-output", defaultValue = "reports/compiler-performance/latest.md") Path markdownOutput;

        @Override public Integer call() {
            try {
                CompilerPerformanceDefinition definition = JsonSupport.MAPPER.readValue(
                        corpus.toFile(), CompilerPerformanceDefinition.class);
                var loader = new StockSlotRegistryLoader();
                var registry = stockRegistry == null ? loader.loadDefault() : loader.load(stockRegistry);
                var report = new CompilerPerformanceBenchmark().run(definition, warmup, iterations,
                        p95ThresholdMillis, registry);
                if (jsonOutput.toAbsolutePath().getParent() != null) Files.createDirectories(jsonOutput.toAbsolutePath().getParent());
                if (markdownOutput.toAbsolutePath().getParent() != null) Files.createDirectories(markdownOutput.toAbsolutePath().getParent());
                Files.writeString(jsonOutput, JsonSupport.MAPPER.writerWithDefaultPrettyPrinter()
                        .writeValueAsString(report) + System.lineSeparator(), StandardCharsets.UTF_8);
                Files.writeString(markdownOutput, CompilerPerformanceMarkdown.render(report), StandardCharsets.UTF_8);
                System.out.println(markdownOutput.toAbsolutePath());
                return report.passed() ? 0 : 4;
            } catch (Exception e) {
                System.err.println("compiler_benchmark_failed: " + e.getMessage());
                return 3;
            }
        }
    }
}
