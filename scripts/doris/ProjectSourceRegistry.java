import com.acme.dorisdsl.stockslot.StockSlotRegistryLoader;
import com.acme.dorisdsl.util.JsonSupport;
import java.nio.file.Path;
import java.util.*;

public class ProjectSourceRegistry {
    public static void main(String[] args) throws Exception {
        var loader = new StockSlotRegistryLoader();
        var registry = args.length == 0 ? loader.loadDefault() : loader.load(Path.of(args[0]));
        var tables = new LinkedHashMap<String, Object>();
        for (String key : List.of("basic", "extension", "code")) tables.put(key, registry.table(key));
        System.out.println(JsonSupport.MAPPER.writeValueAsString(Map.of("registryFingerprint", registry.fingerprint(), "tables", tables)));
    }
}
