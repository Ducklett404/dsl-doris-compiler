import com.acme.dorisdsl.stockslot.*;
import com.acme.dorisdsl.util.JsonSupport;
import java.nio.file.*;
import java.sql.*;

/** Local test diagnostics only; credential values are read from environment and never printed. */
class ProjectExecutionProbe {
    public static void main(String[] args) throws Exception {
        var registry = new StockSlotRegistryLoader().load(Path.of(args[2]));
        var validation = ProjectDataValidation.load(Path.of(args[3]), registry);
        var artifact = new StockSlotSqlCompiler(registry).compile(Files.readString(Path.of(args[4])), StockSlotSqlCompiler.AccessPathMode.PROJECT_REFERENCE);
        try(var executor = new DorisQueryExecutor(args[0],args[1],System.getenv("DSL_PROJECT_PASSWORD"),registry,
                new DorisExecutionPolicy(10,100000000,10000,2147483648L,2000,true),validation)) {
            executor.execute(Files.readString(Path.of(args[4])),validation.certificate().snapshotId(),10,10000);
            System.out.println("CONTROLLED_EXECUTION_OK");
        } catch(DorisExecutionException error) {
            System.out.println("CONTROLLED_EXECUTION_DIAGNOSTIC: "+error.getMessage());
            if(error.getCause()!=null) System.out.println("CAUSE: "+error.getCause().getMessage());
        }
        try (var connection = DriverManager.getConnection(args[0], args[1], System.getenv("DSL_PROJECT_PASSWORD"))) {
            try(var session=connection.createStatement()) {
                session.execute("SET enable_sql_cache=false");session.execute("SET exec_mem_limit=2147483648");session.execute("SET query_timeout=10");
            }
            validation.verify(connection, validation.certificate().snapshotId(), validation.requiredSources(artifact), 10);
            System.out.println("SOURCE_IDENTITY_OK");
            for (var plan : new String[]{artifact.coveragePlan().sql(), artifact.coveragePlan().samplesSql(), artifact.sql()}) {
                System.out.println(plan.equals(artifact.sql()) ? "MAIN_QUERY" : plan.equals(artifact.coveragePlan().sql()) ? "COVERAGE_AGGREGATE" : "COVERAGE_SAMPLES");
                var values = plan.equals(artifact.sql()) ? artifact.bindings() : artifact.coveragePlan().bindings();
                try (var explain = connection.prepareStatement("EXPLAIN "+plan)) {
                    for(int i=0;i<values.size();i++) explain.setObject(i+1,values.get(i));
                    try(var rows=explain.executeQuery()) {
                        while(rows.next()) System.out.println("EXPLAIN: "+rows.getString(1));
                    }
                }
                try (var statement = connection.prepareStatement(plan)) {
                    statement.setQueryTimeout(10);
                    for (int i=0;i<values.size();i++) statement.setObject(i+1,values.get(i));
                    try (var rows=statement.executeQuery()) { while(rows.next()) {} }
                }
                System.out.println("QUERY_OK");
            }
        } catch(SQLException error) {
            System.out.println("SQL_DIAGNOSTIC: " + error.getMessage());
            System.exit(1);
        }
    }
}
