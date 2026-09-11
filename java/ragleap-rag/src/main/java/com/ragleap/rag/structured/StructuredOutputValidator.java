package com.ragleap.rag.structured;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.networknt.schema.JsonSchema;
import com.networknt.schema.JsonSchemaFactory;
import com.networknt.schema.SchemaValidatorsConfig;
import com.networknt.schema.SpecVersion;
import com.networknt.schema.ValidationMessage;

import java.util.Set;
import java.util.logging.Logger;

/**
 * Structured output support for ragleap-rag - validates model responses
 * against a user-supplied JSON schema. Java port of ragleap-rag's
 * structured.py.
 *
 * Uses com.networknt:json-schema-validator for real schema validation -
 * the Java equivalent of Python's jsonschema library, supporting the
 * same range of JSON Schema drafts (v4 through 2020-12).
 *
 * See ValidationMethod's javadoc for why, unlike Python, the "library
 * not installed" fallback path is not reachable through the normal API
 * here - it's a hard Maven dependency, always present.
 */
public final class StructuredOutputValidator {

    private static final Logger logger = Logger.getLogger(StructuredOutputValidator.class.getName());
    private static final ObjectMapper MAPPER = new ObjectMapper();

    // Defaults to the 2020-12 draft when a schema doesn't declare its own
    // $schema - networknt's factory still honors an explicit $schema in
    // the supplied schema document via getSchema(), this is only the
    // fallback used when none is present.
    private static final JsonSchemaFactory SCHEMA_FACTORY =
            JsonSchemaFactory.getInstance(SpecVersion.VersionFlag.V202012);

    private StructuredOutputValidator() {
    }

    /**
     * Parse rawText as JSON and validate against schema. Never throws -
     * a malformed response results in a ValidationResult with a null
     * parsed value and valid=false.
     */
    public static ValidationResult parseAndValidate(String rawText, JsonNode schema) {
        JsonNode parsed;
        try {
            parsed = MAPPER.readTree(rawText);
        } catch (JsonProcessingException e) {
            return new ValidationResult(null, false, ValidationMethod.JSONSCHEMA);
        }
        return validateWithJsonSchema(parsed, schema);
    }

    /**
     * Same as parseAndValidate(), but for providers (Anthropic tool-use)
     * that hand back an already-parsed JsonNode instead of a raw JSON
     * string.
     */
    public static ValidationResult parseAndValidateObject(JsonNode obj, JsonNode schema) {
        return validateWithJsonSchema(obj, schema);
    }

    private static ValidationResult validateWithJsonSchema(JsonNode instance, JsonNode schema) {
        JsonSchema jsonSchema;
        try {
            jsonSchema = SCHEMA_FACTORY.getSchema(schema);
        } catch (Exception e) {
            logger.severe("Invalid JSON schema passed to response_format=: " + e.getMessage());
            return new ValidationResult(instance, false, ValidationMethod.JSONSCHEMA);
        }

        Set<ValidationMessage> errors = jsonSchema.validate(instance);
        if (!errors.isEmpty()) {
            String messages = errors.stream().map(ValidationMessage::getMessage)
                    .reduce((a, b) -> a + "; " + b).orElse("");
            logger.warning("Structured output failed schema validation: " + messages);
            return new ValidationResult(instance, false, ValidationMethod.JSONSCHEMA);
        }
        return new ValidationResult(instance, true, ValidationMethod.JSONSCHEMA);
    }

    /**
     * Basic top-level type check only - does NOT verify nested structure.
     * Ported for documentation parity with the Python source's fallback
     * path (see ValidationMethod's javadoc); not reachable through
     * parseAndValidate()/parseAndValidateObject() in the normal Java API,
     * since the real validator is always available here.
     */
    static boolean basicTypeCheckOnly(JsonNode instance, JsonNode schema) {
        JsonNode typeNode = schema.get("type");
        if (typeNode == null || !typeNode.isTextual()) {
            return true;
        }
        return switch (typeNode.asText()) {
            case "object" -> instance.isObject();
            case "array" -> instance.isArray();
            case "string" -> instance.isTextual();
            case "number" -> instance.isNumber();
            case "boolean" -> instance.isBoolean();
            default -> true;
        };
    }
}
