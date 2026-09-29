package com.acme.dorisdsl.benchmark;

import org.junit.jupiter.api.Test;
import org.openjdk.jmh.results.RunResult;
import org.openjdk.jmh.runner.Runner;
import org.openjdk.jmh.runner.options.OptionsBuilder;
import org.openjdk.jmh.runner.options.TimeValue;

import java.util.Collection;
import java.util.concurrent.TimeUnit;
import java.util.function.Predicate;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

class JmhPerformanceTest {
    @Test void allBucketsRunAndComplexDslP95IsBelowFiftyMillisecondsAfterWarmup() throws Exception {
        var options = new OptionsBuilder()
                .include(DslCompilerBenchmark.class.getName() + ".*")
                .mode(org.openjdk.jmh.annotations.Mode.SampleTime)
                .timeUnit(TimeUnit.MILLISECONDS)
                .warmupIterations(3)
                .warmupTime(TimeValue.milliseconds(200))
                .measurementIterations(5)
                .measurementTime(TimeValue.milliseconds(300))
                .forks(1)
                .shouldFailOnError(true)
                .build();

        Collection<RunResult> results = new Runner(options).run();
        assertEquals(5, results.size(), "Expected simple, medium, complex, error, and malicious benchmarks");
        RunResult complex = results.stream()
                .filter(benchmarkNamed("complexDsl"))
                .findFirst()
                .orElseThrow(() -> new AssertionError("Missing complex DSL benchmark result"));
        double p95Millis = complex.getPrimaryResult()
                .getStatistics().getPercentile(95.0);
        assertTrue(p95Millis < 50.0, "Complex DSL JMH P95 was " + p95Millis + "ms");
    }

    private Predicate<RunResult> benchmarkNamed(String method) {
        return result -> result.getParams().getBenchmark().endsWith("." + method);
    }
}
