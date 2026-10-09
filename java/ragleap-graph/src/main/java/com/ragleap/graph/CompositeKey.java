package com.ragleap.graph;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/** Deterministic MERGE key: SHA-256 of the parts joined with a NUL character. */
public final class CompositeKey {
    private CompositeKey() {
    }

    public static String of(String... parts) {
        String joined = String.join(String.valueOf((char) 0), parts);
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            return HexFormat.of().formatHex(md.digest(joined.getBytes(StandardCharsets.UTF_8)));
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }
}
