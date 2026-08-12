package com.acme.dorisdsl.catalog;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.util.JsonSupport;

import java.io.IOException;
import java.io.InputStream;

public final class CatalogSnapshotLoader {
    public CatalogSnapshot loadDefault() {
        try (InputStream input = CatalogSnapshotLoader.class.getResourceAsStream("/catalog-snapshot.json")) {
            if (input == null) throw new IllegalStateException("Missing /catalog-snapshot.json");
            return JsonSupport.MAPPER.readValue(input, CatalogSnapshot.class);
        } catch (IOException | IllegalArgumentException e) {
            throw new CompileException("CATALOG_INVALID", e.getMessage(), 1, 1);
        }
    }
}
