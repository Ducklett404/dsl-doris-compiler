package com.acme.dorisdsl;

import com.acme.dorisdsl.stockslot.DorisExecutionPolicy;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

final class DorisExecutionPolicyTest {
    @Test void controlledDefaultsAreBoundedAndRequireReadOnlyAccount() {
        var policy = DorisExecutionPolicy.controlledDefaults();
        assertTrue(policy.requireReadOnlyAccount());
        assertEquals(10, policy.queryTimeoutSeconds());
        assertEquals(1_000_000, policy.maxEstimatedScanRows());
        assertEquals(1_000, policy.maxReturnRows());
    }

    @Test void rejectsUnboundedOrInvalidLimits() {
        assertThrows(IllegalArgumentException.class, () -> new DorisExecutionPolicy(11, 1, 1, 64L << 20, 1, true));
        assertThrows(IllegalArgumentException.class, () -> new DorisExecutionPolicy(1, 0, 1, 64L << 20, 1, true));
        assertThrows(IllegalArgumentException.class, () -> new DorisExecutionPolicy(1, 1, 0, 64L << 20, 1, true));
        assertThrows(IllegalArgumentException.class, () -> new DorisExecutionPolicy(1, 1, 1, 1, 1, true));
    }
}
