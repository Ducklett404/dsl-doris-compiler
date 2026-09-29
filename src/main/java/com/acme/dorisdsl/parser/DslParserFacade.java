package com.acme.dorisdsl.parser;

import com.acme.dorisdsl.ast.Ast;
import org.antlr.v4.runtime.CharStreams;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.misc.ParseCancellationException;
import com.acme.dorisdsl.compiler.CompileException;

public final class DslParserFacade {
    private static final int MAX_PARENTHESES_DEPTH = com.acme.dorisdsl.semantic.SemanticAnalyzer.MAX_EXPRESSION_DEPTH;

    public Ast.Query parse(String source) {
        try {
            validateParenthesesDepth(source);
            var lexer = new StockDslLexer(CharStreams.fromString(source));
            lexer.removeErrorListeners();
            lexer.addErrorListener(ThrowingErrorListener.INSTANCE);
            var parser = new StockDslParser(new CommonTokenStream(lexer));
            parser.removeErrorListeners();
            parser.addErrorListener(ThrowingErrorListener.INSTANCE);
            return (Ast.Query) new AstBuilder().visit(parser.query());
        } catch (CompileException e) {
            throw e;
        } catch (ParseCancellationException e) {
            if (e.getCause() instanceof CompileException compileException) throw compileException;
            throw new CompileException("DSL_SYNTAX", "DSL syntax error", 1, 1);
        }
    }

    private void validateParenthesesDepth(String source) {
        int depth = 0;
        int line = 1;
        int column = 1;
        for (int i = 0; i < source.length(); i++) {
            char ch = source.charAt(i);
            if (ch == '(') {
                depth++;
                if (depth > MAX_PARENTHESES_DEPTH)
                    throw new CompileException("EXPRESSION_DEPTH", "Expression depth exceeds " + MAX_PARENTHESES_DEPTH, line, column);
            } else if (ch == ')' && depth > 0) {
                depth--;
            }
            if (ch == '\n') {
                line++;
                column = 1;
            } else {
                column++;
            }
        }
    }
}
