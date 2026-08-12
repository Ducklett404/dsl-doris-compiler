package com.acme.dorisdsl.catalog;

import com.acme.dorisdsl.compiler.CompileException;
import com.acme.dorisdsl.util.JsonSupport;

import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;

public final class CatalogSnapshotLoader {
    public CatalogSnapshot loadDefault() {
        try (InputStream input = CatalogSnapshotLoader.class.getResourceAsStream("/catalog-snapshot.json")) {
            if (input == null) throw new IllegalStateException("Missing /catalog-snapshot.json");
            return read(input);
        } catch (IOException e) {
            throw new CompileException("CATALOG_IO", e.getMessage(), 1, 1);
        }
    }

    public CatalogSnapshot load(Path path) {
        try (InputStream input = Files.newInputStream(path)) {
            return read(input);
        } catch (IOException e) {
            throw new CompileException("CATALOG_IO", "Cannot read catalog snapshot: " + e.getMessage(), 1, 1);
        }
    }

    private CatalogSnapshot read(InputStream input) throws IOException {
        try {
            return JsonSupport.MAPPER.readValue(input, CatalogSnapshot.class);
        } catch (IllegalArgumentException e) {
            throw new CompileException("CATALOG_INVALID", e.getMessage(), 1, 1);
        }
    }
}
