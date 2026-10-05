import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import java.nio.file.*;
import java.util.*;

/** Test adapter: compile fresh ASTs, expose bounded lookup SQL, then classify returned observations. */
class ProjectAvailabilityProbe {
    public static void main(String[] args) throws Exception {
        var registry = new StockSlotRegistryLoader().loadDefault();
        var compiler = new StockSlotSqlCompiler(registry);
        var output = new ArrayList<Object>();
        for (var request : JsonSupport.MAPPER.readTree(Files.readAllBytes(Path.of(args[0])))) {
            var artifact = compiler.compile(request.get("dsl").asText(), StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
            var coverage = artifact.coveragePlan();
            List<List<String>> samples = JsonSupport.MAPPER.convertValue(request.get("samples"), new com.fasterxml.jackson.core.type.TypeReference<>() {});
            if (samples.isEmpty()) { output.add(Map.of("coverage", coverage, "details", List.of(), "sql",artifact.sql(),"bindings",artifact.bindings())); continue; }
            var fetch = StockSlotAvailabilityDiagnostics.fetchPlan(coverage, registry, samples);
            if (request.has("rawRows")) {
                List<List<String>> rows = JsonSupport.MAPPER.convertValue(request.get("rawRows"), new com.fasterxml.jackson.core.type.TypeReference<>() {});
                output.add(Map.of("coverage", coverage, "fetch", fetch, "details", StockSlotAvailabilityDiagnostics.explain(coverage, registry, samples, fetch, rows)));
            } else output.add(Map.of("coverage", coverage, "fetch", fetch));
        }
        System.out.println(JsonSupport.MAPPER.writeValueAsString(output));
    }
}
