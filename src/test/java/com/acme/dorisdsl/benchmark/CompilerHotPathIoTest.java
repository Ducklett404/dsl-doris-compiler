package com.acme.dorisdsl.benchmark;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import jdk.jfr.Recording;
import jdk.jfr.consumer.RecordedEvent;
import jdk.jfr.consumer.RecordingFile;
import org.junit.jupiter.api.Test;

import java.nio.file.Files;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertTrue;

class CompilerHotPathIoTest {
    private static final List<String> IO_EVENTS = List.of(
            "jdk.FileRead", "jdk.FileWrite", "jdk.SocketRead", "jdk.SocketWrite");

    @Test void warmedCompilePathPerformsNoFileOrNetworkIo() throws Exception {
        DslCompiler compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        for (int i = 0; i < 100; i++) compiler.compile(BenchmarkCorpus.COMPLEX);

        long threadId = Thread.currentThread().threadId();
        var recordingPath = Files.createTempFile("dsl-compiler-hot-path-", ".jfr");
        try (Recording recording = new Recording()) {
            IO_EVENTS.forEach(event -> recording.enable(event).withThreshold(Duration.ZERO));
            recording.start();
            for (int i = 0; i < 100; i++) compiler.compile(BenchmarkCorpus.COMPLEX);
            recording.stop();
            recording.dump(recordingPath);
        }

        List<String> violations = new ArrayList<>();
        for (RecordedEvent event : RecordingFile.readAllEvents(recordingPath)) {
            if (event.getThread() != null && event.getThread().getJavaThreadId() == threadId) {
                violations.add(event.getEventType().getName());
            }
        }
        Files.deleteIfExists(recordingPath);
        assertTrue(violations.isEmpty(), "Compiler hot path emitted IO events: " + violations);
    }
}
