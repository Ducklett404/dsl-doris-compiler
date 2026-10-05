package com.acme.dorisdsl;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.stockslot.StockSlotRegistry;
import com.acme.dorisdsl.stockslot.StockSlotRegistryLoader;
import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.node.ArrayNode;
import com.fasterxml.jackson.databind.node.ObjectNode;
import org.junit.jupiter.api.Test;

import java.io.ByteArrayInputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;

import static org.junit.jupiter.api.Assertions.*;

final class StockSlotRegistryTest {
    private final ObjectMapper mapper = new ObjectMapper();

    @Test void defaultRegistryIsExecutableAndCarriesCompleteMetadata() {
        StockSlotRegistry registry = new StockSlotRegistryLoader().loadDefault();
        assertEquals("stock-slot-registry-v1.0.2", registry.version());
        assertEquals("newzl.v_hsj_stock_hq_basic", registry.table("basic").qualifiedName());
        assertEquals("b.closePrice", registry.expression(registry.indicator("收盘价")));
        assertEquals("b.risePct", registry.expression(registry.indicator("涨幅")));
        assertEquals("NULLIF(e.ZJLXMainNetTur,-999999)", registry.expression(registry.indicator("主力净流入")));
        assertEquals("10000", registry.indicator("振幅").exact().scale().divide().toPlainString());
        assertEquals("QFQ", registry.indicator("前复权收盘价").exact().adjustment());
        assertFalse(registry.testVectors().positive().isEmpty());
        assertFalse(registry.testVectors().negative().isEmpty());
    }

    @Test void fieldAndExistingLoweringCanBeAddedUsingOnlyConfigAndVectors() throws Exception {
        ObjectNode root = defaultJson();
        ArrayNode indicators = (ArrayNode) root.get("indicators");
        ObjectNode field = ((ObjectNode) indicators.get(0)).deepCopy();
        field.put("name", "配置新增价");
        field.set("aliases", mapper.createArrayNode());
        ((ObjectNode) field.get("source")).put("field", "openPrice");
        indicators.add(field);

        ArrayNode functions = (ArrayNode) root.get("functions");
        ObjectNode function = ((ObjectNode) functions.get(functions.size() - 1)).deepCopy();
        function.put("name", "config_industry_sum");
        ((ObjectNode) function.get("lowering").get("parameters")).put("defaultAggregation", "SUM");
        functions.add(function);

        ArrayNode positives = (ArrayNode) root.get("testVectors").get("positive");
        positives.addObject().put("id", "config-added-field").put("kind", "INDICATOR_EXPRESSION")
                .put("name", "配置新增价").put("expected", "b.openPrice");
        positives.addObject().put("id", "config-added-function").put("kind", "FUNCTION_LOWERING")
                .put("name", "config_industry_sum").put("expected", "INDUSTRY_AGGREGATE");

        StockSlotRegistry registry = load(root);
        var fieldSql = new StockSlotSqlCompiler(registry).compile(
                "indicator('', '', '配置新增价', '2026-04-14', '', '', '') > 1").sql();
        assertTrue(fieldSql.contains("b.openPrice AS `m1`"), fieldSql);

        var functionSql = new StockSlotSqlCompiler(registry).compile(
                "indicator('', '', '收盘价', '2026-04-14', '', '', '') > "
                        + "config_industry_sum('', '', '收盘价', '2026-04-14', '')").sql();
        assertTrue(functionSql.contains("SUM(`v1`) OVER (PARTITION BY hyBlkRefName,bizdate)"), functionSql);
    }

    @Test void positionMetadataAcceptsOnlyARegisteredFieldAndBoundedNumericScale() throws Exception {
        assertMutation("REGISTRY_REFERENCE", root ->
                ((ObjectNode) root.get("indicators").get(0).get("lowering").get("parameters"))
                        .put("positionField", "lastPrice); DROP TABLE basic; --"));
        for (String scale : new String[]{"-1", "19", "1+1", "12)"}) {
            assertMutation("REGISTRY_RANGE", root ->
                    ((ObjectNode) root.get("indicators").get(0).get("lowering").get("parameters"))
                            .put("positionScale", scale));
        }
        assertMutation("REGISTRY_UNKNOWN_PARAMETER", root ->
                ((ObjectNode) root.get("indicators").get(0).get("lowering").get("parameters"))
                        .put("positionSql", "SELECT evil"));
    }

    @Test void loaderRejectsUnknownPlaceholdersDynamicTablesSubqueriesAndRawSql() throws Exception {
        assertMutation("REGISTRY_UNKNOWN_PLACEHOLDER", root ->
                ((ObjectNode) root.get("indicators").get(0).get("lowering"))
                        .put("expressionTemplate", "{alias}.{unknown}"));
        assertMutation("REGISTRY_UNSAFE_TABLE", root ->
                ((ObjectNode) root.get("tables").get("basic")).put("qualifiedName", "newzl.${tenant}"));
        assertMutation("REGISTRY_UNSAFE_TEMPLATE", root ->
                ((ObjectNode) root.get("indicators").get(0).get("lowering"))
                        .put("expressionTemplate", "(SELECT x FROM evil)"));
        assertMutation("REGISTRY_UNSAFE_TEMPLATE", root ->
                ((ObjectNode) root.get("indicators").get(0).get("lowering"))
                        .put("expressionTemplate", "ABS({alias}.{field})"));
    }

    @Test void loaderRejectsUnknownSchemaFieldsReferencesAndInvalidScale() throws Exception {
        assertMutation("REGISTRY_SCHEMA", root -> root.put("unexpected", true));
        assertMutation("REGISTRY_REFERENCE", root ->
                ((ObjectNode) root.get("indicators").get(0).get("source")).put("field", "doesNotExist"));
        assertMutation("REGISTRY_SCALE", root ->
                ((ObjectNode) root.get("indicators").get(0).get("scale")).put("divide", 0));
    }

    private void assertMutation(String expectedCode, Mutation mutation) throws Exception {
        ObjectNode root = defaultJson();
        mutation.apply(root);
        CompileException error = assertThrows(CompileException.class, () -> load(root));
        assertEquals(expectedCode, error.code(), error.getMessage());
    }

    private StockSlotRegistry load(JsonNode root) throws Exception {
        return new StockSlotRegistryLoader().load(new ByteArrayInputStream(mapper.writeValueAsBytes(root)));
    }

    private ObjectNode defaultJson() throws Exception {
        try (InputStream input = getClass().getResourceAsStream(StockSlotRegistryLoader.DEFAULT_RESOURCE)) {
            assertNotNull(input);
            return (ObjectNode) mapper.readTree(input);
        }
    }

    @FunctionalInterface private interface Mutation { void apply(ObjectNode root) throws Exception; }
}
