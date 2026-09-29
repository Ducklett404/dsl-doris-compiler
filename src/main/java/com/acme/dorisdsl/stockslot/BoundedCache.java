package com.acme.dorisdsl.stockslot;

import java.util.LinkedHashMap;
import java.util.Map;

/** Small synchronized LRU cache; compiler instances remain safe for concurrent HTTP requests. */
final class BoundedCache<K, V> {
    private final int capacity;
    private final LinkedHashMap<K, V> values;
    private long hits;
    private long misses;

    BoundedCache(int capacity) {
        if (capacity < 1) throw new IllegalArgumentException("cache capacity must be positive");
        this.capacity = capacity;
        this.values = new LinkedHashMap<>(capacity, .75f, true) {
            @Override protected boolean removeEldestEntry(Map.Entry<K, V> eldest) {
                return size() > BoundedCache.this.capacity;
            }
        };
    }

    synchronized V get(K key) {
        V value = values.get(key);
        if (value == null) misses++; else hits++;
        return value;
    }

    synchronized void put(K key, V value) { values.put(key, value); }
    synchronized void clear() { values.clear(); hits = 0; misses = 0; }
    synchronized Stats stats() { return new Stats(values.size(), capacity, hits, misses); }

    record Stats(int size, int capacity, long hits, long misses) {}
}
