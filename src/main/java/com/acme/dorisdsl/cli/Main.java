package com.acme.dorisdsl.cli;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.competition.SlotCorpusCoverage;
import com.acme.dorisdsl.competition.SlotDslParserFacade;
import com.acme.dorisdsl.registry.RegistryLoader;
import com.acme.dorisdsl.server.CompileHttpServer;
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
                Main.ParseSlotCommand.class, Main.MeasureSlotCorpusCommand.class})
public final class Main implements Runnable {
    public static void main(String[] args) { System.exit(new CommandLine(new Main()).execute(args)); }
    @Override public void run() { CommandLine.usage(this, System.out); }

    static DslCompiler compiler(Path registry, List<Path> plugins) {
        var loader = new RegistryLoader();
        return new DslCompiler(registry == null ? loader.loadDefault(plugins) : loader.load(registry, plugins));
    }

    @CommandLine.Command(name = "parse-slot", description = "Parse organizer slot DSL to a syntax AST (no SQL generation)")
    static final class ParseSlotCommand implements Callable<Integer> {
        @CommandLine.Parameters(index = "0", description = "UTF-8 slot DSL file") Path input;

        @Override public Integer call() {
            try {
                var ast = new SlotDslParserFacade().parse(Files.readString(input, StandardCharsets.UTF_8));
                System.out.println(JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(ast));
                return 0;
            } catch (CompileException e) {
                System.err.printf("%s at %d:%d: %s%n", e.code(), e.line(), e.column(), e.getMessage());
                return 2;
            } catch (Exception e) {
                System.err.println("parse_slot_failed: " + e.getMessage());
                return 1;
            }
        }
    }

    @CommandLine.Command(name = "measure-slot-corpus", description = "Measure slot DSL syntax/contract acceptance on JSONL corpus")
    static final class MeasureSlotCorpusCommand implements Callable<Integer> {
        @CommandLine.Parameters(index = "0", description = "Corpus JSONL from prepare_competition_corpus.py") Path input;
        @CommandLine.Option(names = "--max-failures", defaultValue = "30", description = "Maximum example failures in report") int maxFailures;
        @CommandLine.Option(names = {"-o", "--output"}, description = "Output JSON report; defaults to stdout") Path output;

        @Override public Integer call() {
            try {
                var report = SlotCorpusCoverage.measure(input, maxFailures);
                String json = JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(report);
                if (output == null) System.out.println(json);
                else Files.writeString(output, json + System.lineSeparator(), StandardCharsets.UTF_8);
                return 0;
            } catch (Exception e) {
                System.err.println("slot_corpus_measure_failed: " + e.getMessage());
                return 1;
            }
        }
    }

    static abstract class RegistryOptions {
        @CommandLine.Option(names = "--registry", description = "Base registry JSON (defaults to bundled registry)") Path registry;
        @CommandLine.Option(names = "--plugin", description = "Plugin JSON; repeatable") List<Path> plugins = new ArrayList<>();
    }

    @CommandLine.Command(name = "compile", description = "Compile one DSL file")
    static final class CompileCommand extends RegistryOptions implements Callable<Integer> {
        @CommandLine.Parameters(index = "0", description = "DSL file") Path input;
        @CommandLine.Option(names = {"-f", "--format"}, defaultValue = "markdown", description = "markdown|json|sql") String format;
        @CommandLine.Option(names = {"-o", "--output"}, description = "Output file; defaults to stdout") Path output;

        @Override public Integer call() {
            try {
                String source = Files.readString(input, StandardCharsets.UTF_8);
                var artifact = compiler(registry, plugins).compile(source);
                String rendered = switch (format.toLowerCase()) {
                    case "json" -> JsonSupport.MAPPER.writeValueAsString(artifact);
                    case "sql" -> artifact.sql();
                    case "markdown", "md" -> MarkdownRenderer.render(artifact);
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

    @CommandLine.Command(name = "serve", description = "Start the JSON compile API")
    static final class ServeCommand extends RegistryOptions implements Callable<Integer> {
        @CommandLine.Option(names = "--host", defaultValue = "127.0.0.1") String host;
        @CommandLine.Option(names = "--port", defaultValue = "8080") int port;

        @Override public Integer call() throws Exception {
            try (var server = new CompileHttpServer(compiler(registry, plugins), host, port)) {
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
            var compiler = compiler(registry, plugins);
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
}
