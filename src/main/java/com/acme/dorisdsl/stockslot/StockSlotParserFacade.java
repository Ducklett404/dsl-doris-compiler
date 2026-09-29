package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.parser.ThrowingErrorListener;
import org.antlr.v4.runtime.BailErrorStrategy;
import org.antlr.v4.runtime.CharStreams;
import org.antlr.v4.runtime.CommonTokenStream;
import org.antlr.v4.runtime.misc.ParseCancellationException;

public final class StockSlotParserFacade {
    public StockSlotAst.Document parse(String source) {
        try {
            var lexer = new StockSlotDslLexer(CharStreams.fromString(source));
            lexer.removeErrorListeners();
            lexer.addErrorListener(ThrowingErrorListener.INSTANCE);
            var parser = new StockSlotDslParser(new CommonTokenStream(lexer));
            parser.removeErrorListeners();
            parser.addErrorListener(ThrowingErrorListener.INSTANCE);
            parser.setErrorHandler(new BailErrorStrategy());
            return (StockSlotAst.Document) new StockSlotAstBuilder().visit(parser.document());
        } catch (CompileException e) {
            throw e;
        } catch (ParseCancellationException | IllegalArgumentException e) {
            throw new CompileException("STOCK_SLOT_SYNTAX", "Unsupported stock-slot-v1 syntax", 1, 1);
        }
    }
}
