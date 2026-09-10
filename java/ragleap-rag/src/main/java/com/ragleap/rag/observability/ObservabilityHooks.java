package com.ragleap.rag.observability;

import java.util.List;
import java.util.Map;
import java.util.function.Consumer;
import java.util.logging.Logger;

/**
 * Lightweight observability hooks for ragleap-rag - fire-and-forget
 * event emission points that other tools (logging, metrics, tracing)
 * can consume. Java port of ragleap-rag's observability.py.
 *
 * This does NOT implement any dashboard, storage, or analysis itself -
 * it is purely the instrumentation seam.
 *
 * Design philosophy, preserved exactly from the Python source: a broken
 * or slow hook must never break the actual RAG operation. Every hook
 * call is wrapped in try/catch - an exception in a hook is logged as a
 * warning and swallowed, never propagated. This is fire-and-forget, not
 * a guarantee of delivery.
 */
public final class ObservabilityHooks {

    private static final Logger logger = Logger.getLogger(ObservabilityHooks.class.getName());

    private ObservabilityHooks() {
    }

    /**
     * Call each handler with the event map, in order. A handler throwing
     * an exception is logged and swallowed - never propagated, since
     * observability must never break the actual RAG operation.
     */
    public static void fireEvent(Map<String, Object> event, List<Consumer<Map<String, Object>>> handlers, String hookName) {
        if (handlers == null || handlers.isEmpty()) {
            return;
        }
        for (Consumer<Map<String, Object>> handler : handlers) {
            try {
                handler.accept(event);
            } catch (Exception e) {
                logger.warning("Observability hook '" + hookName + "' raised an exception (swallowed): " + e);
            }
        }
    }
}
