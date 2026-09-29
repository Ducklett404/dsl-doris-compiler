package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.StockSlotAst;
import com.acme.dorisdsl.stockslot.StockSlotCompiler;
import com.acme.dorisdsl.stockslot.StockSlotRegistryLoader;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.junit.jupiter.api.Assertions.*;

final class StockSlotLanguageContractTest {
    private final StockSlotCompiler compiler = new StockSlotCompiler();

    @Test void grammarProducesTypedAstForNumberPercentStringAndBoolean() {
        var artifact = compiler.classify("indicator('', '', '涨跌幅', '2026-04-14', '', '', '') > 5% "
                + "and position('', '', '收盘价', '20日', '2026-04-14', '', '', '') = '高'");
        assertEquals("PARSED", artifact.status(), artifact.diagnostics().toString());
        var root = assertInstanceOf(StockSlotAst.Binary.class, artifact.semanticModel().document().expression());
        assertEquals(StockSlotAst.ValueType.BOOLEAN, root.type());
        var percentComparison = assertInstanceOf(StockSlotAst.Binary.class, root.left());
        assertEquals(StockSlotAst.ValueType.PERCENT,
                assertInstanceOf(StockSlotAst.FunctionCall.class, percentComparison.left()).type());
        assertEquals(StockSlotAst.ValueType.PERCENT,
                assertInstanceOf(StockSlotAst.Literal.class, percentComparison.right()).type());
        assertEquals(new BigDecimal("5"), ((StockSlotAst.Literal) percentComparison.right()).value());
    }

    @Test void registryFreezesUnitsScalesAndEnums() {
        var registry = new StockSlotRegistryLoader().loadDefault();
        assertAll(
                () -> assertEquals("CNY", registry.indicator("收盘价").exact().unit()),
                () -> assertEquals("SHARE", registry.indicator("成交量").exact().unit()),
                () -> assertEquals("PERCENT_POINT", registry.indicator("振幅").exact().unit()),
                () -> assertEquals(new BigDecimal("10000"), registry.indicator("振幅").exact().scale().divide()),
                () -> assertEquals("QFQ", registry.indicator("前复权收盘价").exact().adjustment()),
                () -> assertEquals("HFQ", registry.indicator("后复权收盘价").exact().adjustment()));

        assertUnsupported("UNSUPPORTED_DIRECTION",
                "rank('', '', '收盘价', 'sideways', '2026-04-14', '', '', '') <= 3");
        assertUnsupported("UNSUPPORTED_AGGREGATION",
                "indicator('', '', '收盘价', '2026-04-14', '', 'MEDIAN', '') > 1");
        assertUnsupported("UNSUPPORTED_SELECT_TYPE",
                "indicator('', '', '收盘价', '2026-04-14', '任意类型', '', '') > 1");
    }

    private void assertUnsupported(String code, String dsl) {
        var result = compiler.classify(dsl);
        assertEquals("UNSUPPORTED", result.status());
        assertTrue(result.diagnostics().stream().anyMatch(item -> item.code().equals(code)), result.diagnostics().toString());
    }
}
