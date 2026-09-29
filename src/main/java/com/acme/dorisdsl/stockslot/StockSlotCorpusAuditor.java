package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.util.JsonSupport;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.SerializationFeature;

import java.io.BufferedReader;
import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.TreeMap;

public final class StockSlotCorpusAuditor {
    private final StockSlotCompiler compiler = new StockSlotCompiler();

    public Summary audit(Path input, Path output) throws IOException {
        long total = 0;
        long parsed = 0;
        long unsupported = 0;
        long unexplained = 0;
        Map<String, Long> reasons = new TreeMap<>();
        var compactJson = JsonSupport.MAPPER.writer().without(SerializationFeature.INDENT_OUTPUT);
        Files.createDirectories(output.toAbsolutePath().getParent());
        try (BufferedReader reader = Files.newBufferedReader(input, StandardCharsets.UTF_8);
             BufferedWriter writer = Files.newBufferedWriter(output, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) continue;
                total++;
                JsonNode source = JsonSupport.MAPPER.readTree(line);
                var artifact = compiler.classify(source.path("dsl").asText());
                if (artifact.status().equals("PARSED")) parsed++; else unsupported++;
                for (var diagnostic : artifact.diagnostics()) {
                    reasons.merge(diagnostic.code(), 1L, Long::sum);
                    if (diagnostic.code().equals("INTERNAL_CLASSIFICATION_ERROR")) unexplained++;
                }
                Map<String, Object> result = new LinkedHashMap<>();
                result.put("row", source.path("row").asInt());
                result.put("dsl", source.path("dsl").asText());
                result.put("status", artifact.status());
                result.put("diagnostics", artifact.diagnostics());
                writer.write(compactJson.writeValueAsString(result));
                writer.newLine();
            }
        }
        return new Summary(total, parsed, unsupported, unexplained, reasons);
    }

    public record Summary(long total, long parsed, long unsupported, long unexplained,
                          Map<String, Long> reasons) {
        public Summary { reasons = Map.copyOf(reasons); }
    }
}
