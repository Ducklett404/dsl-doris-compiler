package com.acme.dorisdsl.competition;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.util.JsonSupport;
import com.fasterxml.jackson.databind.JsonNode;

import java.io.BufferedReader;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Measures syntax/contract acceptance only; it does not claim SQL or result correctness. */
public final class SlotCorpusCoverage {
    private SlotCorpusCoverage() {}

    public record Failure(int sourceRow, String split, String code, int line, int column, String message) {}
    public record Report(int total, int accepted, double acceptanceRate, Map<String, Integer> errors,
                         Map<String, Integer> splitTotals, Map<String, Integer> splitAccepted,
                         List<Failure> failures) {}

    public static Report measure(Path corpus, int maxFailures) throws IOException {
        if (maxFailures < 0) throw new IllegalArgumentException("maxFailures must be >= 0");
        var parser = new SlotDslParserFacade();
        Map<String, Integer> errors = new LinkedHashMap<>();
        Map<String, Integer> splitTotals = new LinkedHashMap<>();
        Map<String, Integer> splitAccepted = new LinkedHashMap<>();
        List<Failure> failures = new ArrayList<>();
        int total = 0, accepted = 0;
        try (BufferedReader reader = Files.newBufferedReader(corpus, StandardCharsets.UTF_8)) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.isBlank()) continue;
                JsonNode row = JsonSupport.MAPPER.readTree(line);
                int sourceRow = row.path("source_row").asInt(-1);
                String split = row.path("split").asText("unknown");
                String dsl = row.path("dsl").asText("");
                total++;
                splitTotals.merge(split, 1, Integer::sum);
                try {
                    parser.parse(dsl);
                    accepted++;
                    splitAccepted.merge(split, 1, Integer::sum);
                } catch (CompileException e) {
                    errors.merge(e.code(), 1, Integer::sum);
                    if (failures.size() < maxFailures)
                        failures.add(new Failure(sourceRow, split, e.code(), e.line(), e.column(), e.getMessage()));
                }
            }
        }
        return new Report(total, accepted, total == 0 ? 0 : (double) accepted / total,
                Map.copyOf(errors), Map.copyOf(splitTotals), Map.copyOf(splitAccepted), List.copyOf(failures));
    }
}
