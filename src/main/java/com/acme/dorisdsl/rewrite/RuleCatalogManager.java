package com.acme.dorisdsl.rewrite;

import com.acme.dorisdsl.compiler.CompileException;

import java.util.ArrayDeque;
import java.util.LinkedHashMap;
import java.util.Map;

/** Thread-safe activation and rollback of immutable rule configurations. */
public final class RuleCatalogManager {
    private final Map<String, RuleCatalog.RuleSet> versions = new LinkedHashMap<>();
    private final ArrayDeque<String> history = new ArrayDeque<>();
    private final String compilerVersion;
    private volatile String activeVersion;

    RuleCatalogManager(RuleCatalog catalog, String compilerVersion) {
        this.compilerVersion = compilerVersion;
        for (var version : catalog.versions()) versions.put(version.version(), version);
        requireCompatible(catalog.activeVersion());
        activeVersion = catalog.activeVersion();
    }

    public String activeVersion() { return activeVersion; }

    public synchronized void activate(String version) {
        requireCompatible(version);
        if (version.equals(activeVersion)) return;
        history.push(activeVersion);
        activeVersion = version;
    }

    public synchronized String rollback() {
        if (history.isEmpty()) throw new CompileException("RULE_ROLLBACK_UNAVAILABLE", "No prior rule version", 1, 1);
        String previous = history.pop();
        requireCompatible(previous);
        activeVersion = previous;
        return previous;
    }

    public synchronized void rollbackTo(String version) {
        requireCompatible(version);
        if (!version.equals(activeVersion)) {
            history.push(activeVersion);
            activeVersion = version;
        }
    }

    public DeclarativeRuleEngine engine() { return new DeclarativeRuleEngine(versions.get(activeVersion)); }

    private void requireCompatible(String version) {
        RuleCatalog.RuleSet set = versions.get(version);
        if (set == null) throw new CompileException("RULE_VERSION_UNKNOWN", "Unknown rule version: " + version, 1, 1);
        if (compare(compilerVersion, set.minCompilerVersion()) < 0
                || compare(compilerVersion, set.maxCompilerVersionExclusive()) >= 0)
            throw new CompileException("RULE_VERSION_INCOMPATIBLE",
                    "Rule version " + version + " is incompatible with compiler " + compilerVersion, 1, 1);
    }

    private static int compare(String left, String right) {
        if (right == null || right.isBlank()) throw new CompileException("RULE_CONFIG_INVALID", "Missing compatibility version", 1, 1);
        int[] a = parse(left), b = parse(right);
        for (int i = 0; i < 3; i++) if (a[i] != b[i]) return Integer.compare(a[i], b[i]);
        return 0;
    }

    private static int[] parse(String version) {
        String[] values = version.split("\\.");
        if (values.length != 3) throw new CompileException("RULE_CONFIG_INVALID", "Expected semantic version: " + version, 1, 1);
        try { return new int[]{Integer.parseInt(values[0]), Integer.parseInt(values[1]), Integer.parseInt(values[2])}; }
        catch (NumberFormatException e) { throw new CompileException("RULE_CONFIG_INVALID", "Expected semantic version: " + version, 1, 1); }
    }
}
