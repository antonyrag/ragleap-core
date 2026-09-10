package com.ragleap.rag.guardrails;

import org.junit.jupiter.api.Test;

import java.util.List;
import java.util.function.UnaryOperator;

import static org.junit.jupiter.api.Assertions.*;

class GuardrailRunnerTest {

    @Test
    void nullGuardrailsReturnsTextUnchanged() {
        assertEquals("hello world", GuardrailRunner.runGuardrails("hello world", null));
    }

    @Test
    void emptyGuardrailsReturnsTextUnchanged() {
        assertEquals("hello world", GuardrailRunner.runGuardrails("hello world", List.of()));
    }

    @Test
    void singleGuardrailTransformsText() {
        UnaryOperator<String> upper = String::toUpperCase;
        assertEquals("HELLO", GuardrailRunner.runGuardrails("hello", List.of(upper)));
    }

    @Test
    void multipleGuardrailsThreadTextInOrder() {
        UnaryOperator<String> upper = String::toUpperCase;
        UnaryOperator<String> exclaim = s -> s + "!";
        assertEquals("HELLO!", GuardrailRunner.runGuardrails("hello", List.of(upper, exclaim)));
    }

    @Test
    void guardrailViolationPropagatesNotSwallowed() {
        UnaryOperator<String> rejecting = s -> {
            throw new GuardrailViolation("contains banned phrase");
        };
        GuardrailViolation ex = assertThrows(GuardrailViolation.class,
                () -> GuardrailRunner.runGuardrails("bad text", List.of(rejecting)));
        assertEquals("contains banned phrase", ex.getMessage());
    }

    @Test
    void nonGuardrailExceptionAlsoPropagates() {
        // The Python source has no try/except at all - ANY exception
        // propagates, not just GuardrailViolation. Confirm that holds here too.
        UnaryOperator<String> buggy = s -> {
            throw new IllegalStateException("unrelated bug");
        };
        assertThrows(IllegalStateException.class,
                () -> GuardrailRunner.runGuardrails("text", List.of(buggy)));
    }

    @Test
    void laterGuardrailNeverRunsAfterEarlierOneThrows() {
        boolean[] secondRan = {false};
        UnaryOperator<String> throwsFirst = s -> {
            throw new GuardrailViolation("rejected");
        };
        UnaryOperator<String> second = s -> {
            secondRan[0] = true;
            return s;
        };

        assertThrows(GuardrailViolation.class,
                () -> GuardrailRunner.runGuardrails("text", List.of(throwsFirst, second)));
        assertFalse(secondRan[0]);
    }
}
