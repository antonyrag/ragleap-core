package com.ragleap.rag.structured;

/**
 * Which validation approach actually ran. Java equivalent of the
 * "jsonschema" / "basic_type_check_only" strings returned by
 * structured.py's parse_and_validate()/parse_and_validate_object().
 *
 * Unlike Python, where BASIC_TYPE_CHECK_ONLY happens when the optional
 * jsonschema extra isn't installed at runtime, the Java port always
 * bundles com.networknt:json-schema-validator as a hard Maven
 * dependency - there's no equivalent "maybe not installed" state. So
 * StructuredOutputValidator's public methods always return JSONSCHEMA;
 * BASIC_TYPE_CHECK_ONLY exists here for documentation parity with the
 * Python source and is reachable only via the explicitly-named
 * basicTypeCheckOnly() method, not through the normal validation path.
 */
public enum ValidationMethod {
    JSONSCHEMA,
    BASIC_TYPE_CHECK_ONLY
}
