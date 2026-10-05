import com.acme.dorisdsl.stockslot.StockSlotSqlCompiler;
import com.acme.dorisdsl.util.JsonSupport;
import java.nio.file.*;
import java.util.*;

/** Portable boundary tests only; full reference and project paths remain distinct. */
class ProjectWindowCompile {
    public static void main(String[] args) throws Exception {
        var compiler = new StockSlotSqlCompiler();
        var output = new ArrayList<Object>();
        for (String dsl : JsonSupport.MAPPER.readValue(Files.readAllBytes(Path.of(args[0])), String[].class)) {
            output.add(Map.of("project", compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE),
                    "reference", compiler.compile(dsl, StockSlotSqlCompiler.AccessPathMode.FULL_SCAN_REFERENCE)));
        }
        System.out.println(JsonSupport.MAPPER.writeValueAsString(output));
    }
}
