import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import com.acme.dorisdsl.util.JsonSupport;
import com.fasterxml.jackson.databind.SerializationFeature;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import java.time.Instant;
import java.util.HexFormat;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;

/** Replays extracted DSLs against the actual SQL compiler; performs no DB I/O. */
class ExecutableCorpusProbe {
    static String hash(Path path) throws Exception {
        return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(Files.readAllBytes(path)));
    }
    public static void main(String[] args) throws Exception {
        Path input = Path.of(args[0]), output = Path.of(args[1]), jar = Path.of(args[2]);
        Files.createDirectories(output);
        var compiler = new StockSlotSqlCompiler();
        var writer = JsonSupport.MAPPER.writer().without(SerializationFeature.INDENT_OUTPUT);
        int total = 0, parsed = 0, compiled = 0, internalErrors = 0;
        Map<String, Integer> reasons = new TreeMap<>();
        try (var reader = Files.newBufferedReader(input, StandardCharsets.UTF_8);
             var out = Files.newBufferedWriter(output.resolve("executable-corpus.jsonl"), StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) continue;
                var source = JsonSupport.MAPPER.readTree(line);
                total++;
                if (source.path("status").asText().equals("PARSED")) parsed++;
                Map<String, Object> row = new LinkedHashMap<>();
                row.put("row", source.path("row").asInt());
                row.put("dsl", source.path("dsl").asText());
                row.put("previousParseStatus", source.path("status").asText());
                try {
                    var artifact = compiler.compileForSnapshot(source.path("dsl").asText(), "stock-20060104-20260414-v1");
                    compiled++;
                    row.put("status", "COMPILED_NOT_EXECUTED");
                    row.put("bindings", artifact.bindings());
                    row.put("ordered", artifact.ordered());
                } catch (CompileException e) {
                    row.put("status", "REJECTED");
                    row.put("code", e.code());
                    row.put("message", e.getMessage());
                    reasons.merge(e.code(), 1, Integer::sum);
                } catch (Exception e) {
                    internalErrors++;
                    row.put("status", "INTERNAL_ERROR");
                    row.put("message", e.getClass().getSimpleName() + ": " + e.getMessage());
                    reasons.merge("INTERNAL_ERROR", 1, Integer::sum);
                }
                out.write(writer.writeValueAsString(row)); out.newLine();
            }
        }
        Map<String, Object> summary = new LinkedHashMap<>();
        summary.put("purpose", "EXTRACTED_CORPUS_SQL_COMPILATION_COVERAGE_NOT_RESULT_ACCURACY");
        summary.put("executedAtUtc", Instant.now().toString());
        summary.put("input", input.toString());
        summary.put("inputSha256", hash(input));
        summary.put("jarSha256", hash(jar));
        summary.put("total", total); summary.put("previousParsed", parsed);
        summary.put("sqlCompiled", compiled); summary.put("rejected", total-compiled-internalErrors);
        summary.put("internalErrors", internalErrors); summary.put("reasons", reasons);
        Files.writeString(output.resolve("executable-corpus-summary.json"), JsonSupport.MAPPER.writerWithDefaultPrettyPrinter().writeValueAsString(summary) + "\n", StandardCharsets.UTF_8);
        System.out.println(writer.writeValueAsString(summary));
        if (internalErrors > 0) System.exit(1);
    }
}
