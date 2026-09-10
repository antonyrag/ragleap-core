package com.ragleap.rag.observability;

import org.junit.jupiter.api.Test;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.function.Consumer;

import static org.junit.jupiter.api.Assertions.*;

class ObservabilityHooksTest {

    @Test
    void nullHandlersListDoesNothing() {
        assertDoesNotThrow(() -> ObservabilityHooks.fireEvent(Map.of("type", "test"), null, "hook"));
    }

    @Test
    void emptyHandlersListDoesNothing() {
        assertDoesNotThrow(() -> ObservabilityHooks.fireEvent(Map.of("type", "test"), List.of(), "hook"));
    }

    @Test
    void singleHandlerReceivesTheEvent() {
        List<Map<String, Object>> received = new ArrayList<>();
        Consumer<Map<String, Object>> handler = received::add;

        Map<String, Object> event = Map.of("type", "ask", "latency_ms", 42);
        ObservabilityHooks.fireEvent(event, List.of(handler), "on_ask");

        assertEquals(1, received.size());
        assertEquals(event, received.get(0));
    }

    @Test
    void allHandlersCalledInOrder() {
        List<Integer> callOrder = new ArrayList<>();
        Consumer<Map<String, Object>> first = e -> callOrder.add(1);
        Consumer<Map<String, Object>> second = e -> callOrder.add(2);
        Consumer<Map<String, Object>> third = e -> callOrder.add(3);

        ObservabilityHooks.fireEvent(Map.of(), List.of(first, second, third), "hook");

        assertEquals(List.of(1, 2, 3), callOrder);
    }

    @Test
    void throwingHandlerIsSwallowedNotPropagated() {
        Consumer<Map<String, Object>> throwing = e -> {
            throw new RuntimeException("boom");
        };

        assertDoesNotThrow(() -> ObservabilityHooks.fireEvent(Map.of(), List.of(throwing), "flaky_hook"));
    }

    @Test
    void throwingHandlerDoesNotStopSubsequentHandlers() {
        List<String> called = new ArrayList<>();
        Consumer<Map<String, Object>> throwing = e -> {
            throw new RuntimeException("boom");
        };
        Consumer<Map<String, Object>> afterThrow = e -> called.add("ran");

        ObservabilityHooks.fireEvent(Map.of(), List.of(throwing, afterThrow), "hook");

        assertEquals(List.of("ran"), called);
    }

    @Test
    void multipleHandlersEachThrowAreAllSwallowed() {
        List<String> called = new ArrayList<>();
        Consumer<Map<String, Object>> throwsFirst = e -> {
            throw new IllegalStateException("first failure");
        };
        Consumer<Map<String, Object>> succeeds = e -> called.add("succeeded");
        Consumer<Map<String, Object>> throwsSecond = e -> {
            throw new RuntimeException("second failure");
        };

        assertDoesNotThrow(() -> ObservabilityHooks.fireEvent(Map.of(), List.of(throwsFirst, succeeds, throwsSecond), "hook"));
        assertEquals(List.of("succeeded"), called);
    }
}
