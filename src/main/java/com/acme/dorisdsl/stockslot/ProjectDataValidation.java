package com.acme.dorisdsl.stockslot;

import com.acme.dorisdsl.util.JsonSupport;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.*;
import java.util.*;

/** Trusted local publication of project checks; never a VALIDATED official snapshot. */
public record ProjectDataValidation(Certificate certificate, String certificateSha256) {
    public record Source(String qualifiedName, String kind, String status, long rows, String definitionSha256) {}
    public record Certificate(String formatVersion, String status, String snapshotId, String contractVersion,
                               String manifestSha256, String registryFingerprint, String definitionAuthority,
                               Map<String, Source> sources, long extensionWithoutBasic, long closeOutsideRange,
                               List<String> limitations) {
        public Certificate {
            sources = sources == null ? Map.of() : Map.copyOf(sources);
            limitations = limitations == null ? List.of() : List.copyOf(limitations);
        }
    }

    public static ProjectDataValidation load(Path path, StockSlotRegistry registry) throws java.io.IOException {
        byte[] bytes = Files.readAllBytes(path);
        var data = JsonSupport.MAPPER.readValue(bytes, Certificate.class);
        validate(data, registry);
        return new ProjectDataValidation(data, sha(bytes));
    }

    public void validateRegistry(StockSlotRegistry registry) { validate(certificate, registry); }

    private static void validate(Certificate data, StockSlotRegistry registry) {
        require("project-data-validation-v1".equals(data.formatVersion()), "Unknown project validation format");
        require("PROJECT_READY_WITH_LIMITATIONS".equals(data.status()) && "PROJECT_INTERNAL".equals(data.definitionAuthority()),
                "Expected explicit project-only validation authority");
        require(data.snapshotId() != null && !data.snapshotId().isBlank() && data.contractVersion() != null, "Missing source identity");
        require(hash(data.manifestSha256()) && registry.fingerprint().equals(data.registryFingerprint()), "Stale project registry or manifest identity");
        require(data.sources() != null && !data.sources().isEmpty()
                && Set.of("basic", "extension", "code").containsAll(data.sources().keySet()), "Unknown source capability");
        require(data.limitations() != null && !data.limitations().isEmpty()
                && data.extensionWithoutBasic() >= 0 && data.closeOutsideRange() >= 0, "Missing project limitations");
        for (var entry : data.sources().entrySet()) {
            Source source = entry.getValue();
            require(source != null && registry.table(entry.getKey()).qualifiedName().equals(source.qualifiedName()), "Source table does not match registry");
            require(Set.of("VIEW", "TABLE").contains(source.kind()) && Set.of("PROJECT_READY", "BLOCKED").contains(source.status())
                    && source.rows() >= 0 && hash(source.definitionSha256()), "Invalid source validation");
        }
    }

    public Set<String> requiredSources(StockSlotSqlArtifact artifact) {
        var required = new LinkedHashSet<String>();
        required.add("basic");
        if (artifact.coveragePlan() == null) unavailable("This query has no verified availability plan");
        if (artifact.coveragePlan().extensionRequired()) required.add("extension");
        if (artifact.logicalPlan().stream().anyMatch(p -> p.kind().equals("CodeJoin"))) required.add("code");
        for (var call : artifact.semanticModel().calls()) {
            if (Set.of("belong_industry", "industry_max").contains(call.function())
                    || call.slots().stream().anyMatch(s -> s.name().equals("filter_scope") && !s.rawValue().isEmpty()))
                unavailable("Industry capability is not validated by the supplied official data");
        }
        for (String key : required) {
            Source source = certificate.sources().get(key);
            if (source == null || !source.status().equals("PROJECT_READY")) unavailable("Project source capability is not ready: " + key);
        }
        return Collections.unmodifiableSet(required);
    }

    public DorisExecutionArtifact.SnapshotVersion verify(Connection connection, String snapshotId,
                                                         Set<String> required, int timeout) throws SQLException {
        if (!certificate.snapshotId().equals(snapshotId)) unavailable("Project validation does not match requested snapshot");
        for (String key : required) {
            Source source = certificate.sources().get(key);
            try (var statement = connection.createStatement()) {
                statement.setQueryTimeout(timeout);
                try (var rows = statement.executeQuery("SELECT COUNT(*) FROM " + source.qualifiedName())) {
                    if (!rows.next() || rows.getLong(1) != source.rows()) unavailable("Source rows changed after project validation: " + key);
                }
            }
            if (!ProjectSourceDefinition.fingerprint(connection, source.qualifiedName(), source.kind(), timeout).equals(source.definitionSha256()))
                unavailable("Source definition changed after project validation: " + key);
        }
        return new DorisExecutionArtifact.SnapshotVersion(snapshotId, certificate.contractVersion(), certificate.manifestSha256());
    }

    private static boolean hash(String value) { return value != null && value.matches("[0-9a-f]{64}"); }
    static String sha(byte[] bytes) {
        try { return HexFormat.of().formatHex(java.security.MessageDigest.getInstance("SHA-256").digest(bytes)); }
        catch (java.security.NoSuchAlgorithmException error) { throw new IllegalStateException(error); }
    }
    private static void require(boolean condition, String message) {
        if (!condition) throw new IllegalArgumentException(message);
    }
    private static void unavailable(String message) {
        throw new DorisExecutionException(DorisExecutionException.Category.DATA_UNAVAILABLE, message);
    }
}
