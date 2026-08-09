package com.acme.dorisdsl.parser;

import com.acme.dorisdsl.ast.Ast;
import org.antlr.v4.runtime.CharStreams;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.misc.ParseCancellationException;
import com.acme.dorisdsl.compiler.CompileException;

public final class DslParserFacade {
    public Ast.Query parse(String source) {
        try {
            var lexer = new StockDslLexer(CharStreams.fromString(source));
            lexer.removeErrorListeners();
            lexer.addErrorListener(ThrowingErrorListener.INSTANCE);
            var parser = new StockDslParser(new CommonTokenStream(lexer));
            parser.removeErrorListeners();
            parser.addErrorListener(ThrowingErrorListener.INSTANCE);
            parser.setErrorHandler(new org.antlr.v4.runtime.BailErrorStrategy());
            return (Ast.Query) new AstBuilder().visit(parser.query());
        } catch (CompileException e) {
            throw e;
        } catch (ParseCancellationException e) {
            throw new CompileException("DSL_SYNTAX", "DSL syntax error", 1, 1);
        }
    }
}
