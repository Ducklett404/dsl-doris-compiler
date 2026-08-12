package com.acme.dorisdsl.executor.doris;

import java.io.IOException;
import java.net.URI;
import java.net.URLEncoder;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.Base64;
import java.util.Locale;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

public final class QueryProfileCollector {
    private static final Pattern BYTES = Pattern.compile("(?im)^\\s*-?\\s*(?:BytesRead|ScanBytes|CompressedBytesRead)\\s*:\\s*([^\\r\\n]+)");
    private static final Pattern ROWS = Pattern.compile("(?im)^\\s*-?\\s*(?:RowsRead|ScanRows|RowsProduced)\\s*:\\s*([0-9,]+)");
    private static final Pattern MEMORY = Pattern.compile("(?im)^\\s*-?\\s*(?:PeakMemoryUsage|MemoryUsagePeak|PeakUsedReservation)\\s*:\\s*([^\\r\\n]+)");
    private static final Pattern TOTAL = Pattern.compile("(?im)^\\s*-?\\s*Total\\s*:\\s*([^\\r\\n]+)");
    private final ProfileTextClient client;

    public QueryProfileCollector(ProfileTextClient client) { this.client = client; }

    public QueryProfile collect(String queryId) throws IOException, InterruptedException {
        String raw = client.fetch(queryId);
        return new QueryProfile(queryId, raw, maxSize(BYTES, raw), maxLong(ROWS, raw),
                durationNanos(first(TOTAL, raw)), maxSize(MEMORY, raw));
    }

    @FunctionalInterface
    public interface ProfileTextClient { String fetch(String queryId) throws IOException, InterruptedException; }

    public static ProfileTextClient http(URI feBaseUri, String user, String password) {
        HttpClient http = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(10)).build();
        String authorization = "Basic " + Base64.getEncoder().encodeToString((user + ":" + password)
                .getBytes(StandardCharsets.UTF_8));
        return queryId -> {
            String encoded = URLEncoder.encode(queryId, StandardCharsets.UTF_8);
            URI uri = feBaseUri.resolve("/api/profile/text?query_id=" + encoded);
            HttpRequest request = HttpRequest.newBuilder(uri).timeout(Duration.ofSeconds(30))
                    .header("Authorization", authorization).GET().build();
            HttpResponse<String> response = http.send(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (response.statusCode() != 200)
                throw new IOException("Doris profile endpoint returned HTTP " + response.statusCode());
            return response.body();
        };
    }

    public record QueryProfile(String queryId, String rawProfile, long scannedBytes, long scannedRows,
                               long elapsedNanos, long peakMemoryBytes) {}

    private static long maxLong(Pattern pattern, String raw) {
        long result = -1;
        Matcher matcher = pattern.matcher(raw);
        while (matcher.find()) result = Math.max(result, Long.parseLong(matcher.group(1).replace(",", "")));
        return result;
    }

    private static long maxSize(Pattern pattern, String raw) {
        long result = -1;
        Matcher matcher = pattern.matcher(raw);
        while (matcher.find()) result = Math.max(result, sizeBytes(matcher.group(1)));
        return result;
    }

    static long sizeBytes(String value) {
        Matcher matcher = Pattern.compile("(?i)([0-9]+(?:\\.[0-9]+)?)\\s*(B|KB|MB|GB|TB)?").matcher(value.strip());
        if (!matcher.find()) return -1;
        double amount = Double.parseDouble(matcher.group(1));
        String unit = matcher.group(2) == null ? "B" : matcher.group(2).toUpperCase(Locale.ROOT);
        long multiplier = switch (unit) { case "KB" -> 1L << 10; case "MB" -> 1L << 20;
            case "GB" -> 1L << 30; case "TB" -> 1L << 40; default -> 1L; };
        return Math.round(amount * multiplier);
    }

    static long durationNanos(String value) {
        if (value == null) return -1;
        Matcher matcher = Pattern.compile("(?i)([0-9]+(?:\\.[0-9]+)?)\\s*(ns|us|ms|s|min)").matcher(value.strip());
        long total = 0;
        while (matcher.find()) {
            double amount = Double.parseDouble(matcher.group(1));
            double multiplier = switch (matcher.group(2).toLowerCase(Locale.ROOT)) {
                case "us" -> 1_000d; case "ms" -> 1_000_000d; case "s" -> 1_000_000_000d;
                case "min" -> 60_000_000_000d; default -> 1d;
            };
            total += Math.round(amount * multiplier);
        }
        return total == 0 ? -1 : total;
    }

    private static String first(Pattern pattern, String raw) {
        Matcher matcher = pattern.matcher(raw);
        return matcher.find() ? matcher.group(1) : null;
    }
}
