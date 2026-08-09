package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.junit.jupiter.api.Test;

import java.util.Arrays;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertTrue;

class PerformanceSmokeTest {
    @Test void compilerP95IsBelowFiftyMillisecondsAfterWarmup() {
        var compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        for (int i = 0; i < 200; i++) compiler.compile(CompilerTest.sampleDsl());
        long[] samples = new long[1000];
        for (int i = 0; i < samples.length; i++) {
            long start = System.nanoTime();
            compiler.compile(CompilerTest.sampleDsl());
            samples[i] = System.nanoTime() - start;
        }
        Arrays.sort(samples);
        double p95Millis = samples[(int) (samples.length * 0.95)] / 1_000_000.0;
        assertTrue(p95Millis < 50.0, "P95 was " + p95Millis + "ms");
    }
}
