package com.ragleap.rag.structured;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.*;

class StructuredOutputValidatorTest {

    private static final ObjectMapper MAPPER = new ObjectMapper();

    private JsonNode node(String json) throws Exception {
        return MAPPER.readTree(json);
    }

    @Test
    void validObjectPassesSchemaValidation() throws Exception {
        JsonNode schema = node("""
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
            """);
        ValidationResult result = StructuredOutputValidator.parseAndValidate("{\"name\": \"RagLeap\"}", schema);

        assertTrue(result.valid());
        assertEquals(ValidationMethod.JSONSCHEMA, result.method());
        assertEquals("RagLeap", result.parsed().get("name").asText());
    }

    @Test
    void objectMissingRequiredFieldFailsValidation() throws Exception {
        JsonNode schema = node("""
            {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
            """);
        ValidationResult result = StructuredOutputValidator.parseAndValidate("{}", schema);

        assertFalse(result.valid());
        // parsed is still returned even when invalid - matches Python's
        // (parsed, False, method), not (None, False, method)
        assertNotNull(result.parsed());
    }

    @Test
    void malformedJsonReturnsNullParsedAndInvalid() throws Exception {
        JsonNode schema = node("{\"type\": \"object\"}");
        ValidationResult result = StructuredOutputValidator.parseAndValidate("{not valid json", schema);

        assertNull(result.parsed());
        assertFalse(result.valid());
    }

    @Test
    void nestedStructureIsGenuinelyValidatedNotJustTopLevelType() throws Exception {
        // Proves this is real jsonschema-style validation, not the
        // basic_type_check_only fallback which would only check that
        // the top-level value is an object.
        JsonNode schema = node("""
            {
              "type": "object",
              "properties": {
                "age": {"type": "integer", "minimum": 0}
              }
            }
            """);
        ValidationResult result = StructuredOutputValidator.parseAndValidate("{\"age\": -5}", schema);

        assertFalse(result.valid());
    }

    @Test
    void invalidSchemaItselfHandledGracefullyNotThrown() throws Exception {
        // A schema with a malformed regex pattern - networknt should
        // surface this as a schema-level problem, not throw uncaught.
        JsonNode schema = node("""
            {"type": "string", "pattern": "[invalid("}
            """);
        assertDoesNotThrow(() -> StructuredOutputValidator.parseAndValidate("\"test\"", schema));
    }

    @Test
    void parseAndValidateObjectAcceptsAlreadyParsedNode() throws Exception {
        JsonNode schema = node("{\"type\": \"array\", \"items\": {\"type\": \"number\"}}");
        JsonNode obj = node("[1, 2, 3]");

        ValidationResult result = StructuredOutputValidator.parseAndValidateObject(obj, schema);
        assertTrue(result.valid());
    }

    @Test
    void basicTypeCheckOnlyMatchesObjectType() throws Exception {
        JsonNode schema = node("{\"type\": \"object\"}");
        assertTrue(StructuredOutputValidator.basicTypeCheckOnly(node("{}"), schema));
        assertFalse(StructuredOutputValidator.basicTypeCheckOnly(node("[]"), schema));
    }

    @Test
    void basicTypeCheckOnlyMatchesArrayType() throws Exception {
        JsonNode schema = node("{\"type\": \"array\"}");
        assertTrue(StructuredOutputValidator.basicTypeCheckOnly(node("[1,2]"), schema));
        assertFalse(StructuredOutputValidator.basicTypeCheckOnly(node("\"str\""), schema));
    }

    @Test
    void basicTypeCheckOnlyDoesNotCatchNestedViolations() throws Exception {
        // Demonstrates exactly the documented limitation: a top-level
        // object "passes" even though a nested field violates the schema
        // - this is the gap that makes it a fallback, not a substitute.
        JsonNode schema = node("""
            {"type": "object", "properties": {"age": {"type": "integer", "minimum": 0}}}
            """);
        JsonNode instance = node("{\"age\": -5}");
        assertTrue(StructuredOutputValidator.basicTypeCheckOnly(instance, schema));
    }
}
