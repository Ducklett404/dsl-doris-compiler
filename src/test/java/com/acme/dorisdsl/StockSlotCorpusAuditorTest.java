package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.StockSlotCorpusAuditor;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;

final class StockSlotCorpusAuditorTest {
    @Test
    void emitsExactlyOneExplainedResultPerInput(@TempDir Path directory) throws Exception {
        Path input = directory.resolve("input.jsonl");
        Path output = directory.resolve("output.jsonl");
        Files.writeString(input,
                "{\"row\":2,\"dsl\":\"indicator('', '', '收盘价', '', '', '', '') > 5\"}\n"
                        + "{\"row\":3,\"dsl\":\"and indicator('', '', '收盘价', '', '', '', '') > 5\"}\n",
                StandardCharsets.UTF_8);
        var summary = new StockSlotCorpusAuditor().audit(input, output);
        assertEquals(2, summary.total());
        assertEquals(1, summary.parsed());
        assertEquals(1, summary.unsupported());
        assertEquals(0, summary.unexplained());
        assertEquals(2, Files.readAllLines(output, StandardCharsets.UTF_8).size());
    }
}
