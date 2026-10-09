import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import java.nio.file.*;
import java.sql.*;
import java.util.*;

/** Read-only plans for local experiments; compatible with archived baseline JARs. */
class ProjectPlanExplain {
    public static void main(String[] args) throws Exception {
        var artifact = new StockSlotSqlCompiler().compile(Files.readString(Path.of(args[2])), StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        var json = JsonSupport.MAPPER.valueToTree(artifact);
        var output = new LinkedHashMap<String,Object>();
        try(var connection=DriverManager.getConnection(args[0],args[1],System.getenv("DSL_PROJECT_PASSWORD"))) {
            try(var session=connection.createStatement()) { session.execute("SET parallel_pipeline_task_num=2");session.execute("SET query_timeout=10");session.execute("SET exec_mem_limit=2147483648"); }
            for(String name:List.of("main","sql","samplesSql","combinedSql")) {
                var node=name.equals("main")?json:json.get("coveragePlan");
                var sql=node.get(name.equals("main")?"sql":name);
                if(sql==null||sql.isNull())continue;
                var bindings=node.get("bindings");var lines=new ArrayList<String>();
                try(var statement=connection.prepareStatement("EXPLAIN "+sql.asText())) {
                    statement.setQueryTimeout(10);
                    for(int i=0;i<bindings.size();i++) statement.setObject(i+1,bindings.get(i).isTextual()?bindings.get(i).asText():bindings.get(i).numberValue());
                    try(var rows=statement.executeQuery()) {while(rows.next())lines.add(rows.getString(1));}
                }
                output.put(name,Map.of("sql",sql.asText(),"bindings",bindings,"explain",lines));
            }
        }
        System.out.println(JsonSupport.MAPPER.writeValueAsString(output));
    }
}
