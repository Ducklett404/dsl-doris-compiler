package com.acme.dorisdsl.parser;

import com.acme.dorisdsl.compiler.CompileException;
import org.antlr.v4.runtime.BaseErrorListener;
import org.antlr.v4.runtime.RecognitionException;
import org.antlr.v4.runtime.Recognizer;

public final class ThrowingErrorListener extends BaseErrorListener {
    public static final ThrowingErrorListener INSTANCE = new ThrowingErrorListener();
    private ThrowingErrorListener() {}

    @Override
    public void syntaxError(Recognizer<?, ?> recognizer, Object offendingSymbol, int line,
                            int charPositionInLine, String msg, RecognitionException e) {
        throw new CompileException("DSL_SYNTAX", "DSL syntax error: " + msg, line, charPositionInLine + 1);
    }
}
