package com.acme.dorisdsl.benchmark;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;
import com.acme.dorisdsl.registry.RegistryLoader;
import org.openjdk.jmh.annotations.Benchmark;
import org.openjdk.jmh.annotations.BenchmarkMode;
import org.openjdk.jmh.annotations.Level;
import org.openjdk.jmh.annotations.Mode;
import org.openjdk.jmh.annotations.OutputTimeUnit;
import org.openjdk.jmh.annotations.Scope;
import org.openjdk.jmh.annotations.Setup;
import org.openjdk.jmh.annotations.State;

import java.util.List;
import java.util.concurrent.TimeUnit;

@BenchmarkMode(Mode.SampleTime)
@OutputTimeUnit(TimeUnit.MILLISECONDS)
public class DslCompilerBenchmark {
    @State(Scope.Benchmark)
    public static class CompilerState {
        DslCompiler compiler;

        @Setup(Level.Trial)
        public void setUp() {
            // Registry and plugin IO belongs to startup, never to the measured compile path.
            compiler = new DslCompiler(new RegistryLoader().loadDefault(List.of()));
        }
    }

    @Benchmark
    public Object simpleDsl(CompilerState state) {
        return state.compiler.compile(BenchmarkCorpus.SIMPLE);
    }

    @Benchmark
    public Object mediumDsl(CompilerState state) {
        return state.compiler.compile(BenchmarkCorpus.MEDIUM);
    }

    @Benchmark
    public Object complexDsl(CompilerState state) {
        return state.compiler.compile(BenchmarkCorpus.COMPLEX);
    }

    @Benchmark
    public String errorDsl(CompilerState state) {
        return compileErrorCode(state.compiler, BenchmarkCorpus.ERROR);
    }

    @Benchmark
    public String maliciousBoundaryDsl(CompilerState state) {
        return compileErrorCode(state.compiler, BenchmarkCorpus.MALICIOUS_BOUNDARY);
    }

    private String compileErrorCode(DslCompiler compiler, String dsl) {
        try {
            compiler.compile(dsl);
            return "COMPILED";
        } catch (CompileException exception) {
            return exception.code();
        }
    }
}
