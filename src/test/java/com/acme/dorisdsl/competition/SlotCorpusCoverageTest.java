package com.acme.dorisdsl.competition;

import com.acme.dorisdsl.util.JsonSupport;
import com.fasterxml.jackson.databind.SerializationFeature;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;

class SlotCorpusCoverageTest {
    @TempDir Path tempDir;

    @Test void reportsAcceptedAndRejectedRowsWithoutTreatingThemAsSqlResults() throws Exception {
        Path corpus = tempDir.resolve("sample.jsonl");
        var jsonlWriter = JsonSupport.MAPPER.writer().without(SerializationFeature.INDENT_OUTPUT);
        String valid = jsonlWriter.writeValueAsString(Map.of(
                "source_row", 10, "split", "train",
                "dsl", "indicator('', '', '最新价', '', '', '', '') > 10 limit 3,-1"));
        String invalid = jsonlWriter.writeValueAsString(Map.of(
                "source_row", 11, "split", "dev",
                "dsl", "indicator('沪') > 10"));
        Files.writeString(corpus, valid + "\n" + invalid + "\n", StandardCharsets.UTF_8);

        var report = SlotCorpusCoverage.measure(corpus, 10);
        assertEquals(2, report.total());
        assertEquals(1, report.accepted());
        assertEquals(0.5, report.acceptanceRate());
        assertEquals(1, report.errors().get("DSL_FUNCTION_ARITY"));
        assertEquals(11, report.failures().getFirst().sourceRow());
        assertEquals(1, report.splitAccepted().get("train"));
    }
}
