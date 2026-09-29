package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.compiler.DslCompiler;

import java.util.List;

public final class StockSlotCompiler {
    public static final String DSL_VERSION = "stock-slot-v1";
    private final StockSlotParserFacade parser = new StockSlotParserFacade();
    private final StockSlotSemanticAnalyzer semanticAnalyzer;

    public StockSlotCompiler() { this(new StockSlotRegistryLoader().loadDefault()); }
    public StockSlotCompiler(StockSlotRegistry registry) { this.semanticAnalyzer = new StockSlotSemanticAnalyzer(registry); }

    public StockSlotCompilationArtifact classify(String dsl) {
        try {
            validate(dsl);
            var analyzed = analyze(parse(dsl));
            String status = analyzed.diagnostics().isEmpty() ? "PARSED" : "UNSUPPORTED";
            return new StockSlotCompilationArtifact(DslCompiler.VERSION, DSL_VERSION, status,
                    analyzed.semanticModel(), analyzed.diagnostics());
        } catch (CompileException e) {
            return unsupported(e.code(), e.getMessage(), e.line(), e.column());
        } catch (RuntimeException e) {
            return unsupported("INTERNAL_CLASSIFICATION_ERROR",
                    "Classifier could not explain this input: " + e.getClass().getSimpleName(), 1, 1);
        }
    }

    void validate(String dsl) {
        if (dsl == null) throw new CompileException("EMPTY_DSL", "DSL cannot be empty", 1, 1);
        if (dsl.length() > 100_000) throw new CompileException("DSL_TOO_LARGE", "DSL exceeds 100000 characters", 1, 1);
        if (dsl.isBlank()) throw new CompileException("EMPTY_DSL", "DSL cannot be empty", 1, 1);
    }

    StockSlotAst.Document parse(String dsl) { return parser.parse(dsl); }
    StockSlotSemanticAnalyzer.Result analyze(StockSlotAst.Document document) { return semanticAnalyzer.analyze(document); }

    private StockSlotCompilationArtifact unsupported(String code, String message, int line, int column) {
        return new StockSlotCompilationArtifact(DslCompiler.VERSION, DSL_VERSION, "UNSUPPORTED", null,
                List.of(new StockSlotDiagnostic("ERROR", code, message, line, column)));
    }
}
