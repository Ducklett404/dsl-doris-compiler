import com.acme.dorisdsl.stockslot.StockSlotRegistryLoader;
import com.acme.dorisdsl.util.JsonSupport;
import java.util.*;

/** Exposes compiler-owned expressions/fingerprint for the diagnostic feature builder. */
public class HistoryFeatureRegistry {
    public static void main(String[] args) throws Exception {
        var registry = new StockSlotRegistryLoader().loadDefault();
        var metrics = new LinkedHashMap<String, Object>();
        for (var entry : Map.of("close", "收盘价", "high", "最高价", "low", "最低价").entrySet())
            metrics.put(entry.getKey(), Map.of("sourceExpression", registry.expression(registry.indicator(entry.getValue())),
                "currentField", entry.getKey()+"_current", "minField", entry.getKey()+"_min", "maxField", entry.getKey()+"_max"));
        System.out.println(JsonSupport.MAPPER.writeValueAsString(Map.of("registryFingerprint", registry.fingerprint(),
            "metrics", metrics, "sourceTable", registry.table("basic").qualifiedName())));
    }
}
