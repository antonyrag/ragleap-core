package com.ragleap.vectorstores;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;

import java.nio.charset.StandardCharsets;
import java.nio.file.Path;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;

/** Unit tests that run everywhere (CI included); the Python comparison is in RedisParityTest. */
class RedisBackendTest {

    @Test
    void escapeTagMatchesWhatPythonSentForTheSameInput() {
        // string printed by the real Python backend for "a-b.c d{e}\\f\u00e9_ok:1"
        assertEquals("a\\-b\\.c\\ d\\{e\\}\\\\f\u00e9_ok\\:1", RedisBackend.escapeTag("a-b.c d{e}\\f\u00e9_ok:1"));
        assertEquals("plain", RedisBackend.escapeTag("plain"));
    }

    @Test
    void vectorsAreLittleEndianFloat32() {
        assertArrayEquals(new byte[] {0, 0, 0, 0x3f}, RedisBackend.floatBytes(List.of(0.5)));
        assertArrayEquals(new byte[] {0, 0, (byte) 0x80, 0x3f}, RedisBackend.floatBytes(List.of(1.0)));
        // float32 overflow gives infinity, like numpy
        assertArrayEquals(new byte[] {0, 0, (byte) 0x80, 0x7f}, RedisBackend.floatBytes(List.of(1e39)));
        assertEquals(0, RedisBackend.floatBytes(List.of()).length);
    }

    @Test
    void pyStrFollowsPython() {
        assertEquals("5", RedisBackend.pyStr(5));
        assertEquals("True", RedisBackend.pyStr(true));
        assertEquals("None", RedisBackend.pyStr(null));
        assertEquals("1.5", RedisBackend.pyStr(1.5));
        assertThrows(IllegalArgumentException.class, () -> RedisBackend.pyStr(List.of(1)));
    }

    @Test
    void pyFloatFollowsPython() {
        assertEquals(0.087655, RedisBackend.pyFloat("0.087655"));
        assertEquals(10.0, RedisBackend.pyFloat(" 1_0 "));
        assertEquals(1e-5, RedisBackend.pyFloat("1e-5"));
        assertEquals(Double.NEGATIVE_INFINITY, RedisBackend.pyFloat("-Infinity"));
        assertEquals(0.5, RedisBackend.pyFloat(".5"));
        assertThrows(NumberFormatException.class, () -> RedisBackend.pyFloat("abc"));
        assertThrows(NumberFormatException.class, () -> RedisBackend.pyFloat("1__0"));
        assertThrows(NumberFormatException.class, () -> RedisBackend.pyFloat("1d"));
        assertThrows(NumberFormatException.class, () -> RedisBackend.pyFloat("0x1p3"));
    }

    @Test
    void pyMinAndMaxFollowPythonIncludingNaN() {
        assertEquals(1.0, RedisBackend.pyMin(1.0, Double.NaN));
        assertEquals(0.5, RedisBackend.pyMin(1.0, 0.5));
        assertEquals(1.0, RedisBackend.pyMin(1.0, 2.0));
        assertEquals(0.0, RedisBackend.pyMax(0.0, Double.NaN));
        assertEquals(0.0, RedisBackend.pyMax(0.0, Double.NEGATIVE_INFINITY));
        assertEquals(0.7, RedisBackend.pyMax(0.0, 0.7));
    }

    @Test
    void respRequestIsAnArrayOfBulkStrings() {
        assertEquals("*2\r\n$4\r\nPING\r\n$3\r\n\u00e9a\r\n",
                new String(RespClient.encode("PING", "\u00e9a"), StandardCharsets.UTF_8));
        assertEquals("*1\r\n$4\r\nPING\r\n", new String(RespClient.encode("PING"), StandardCharsets.UTF_8));
    }

    private static String readLine(java.io.InputStream in) throws java.io.IOException {
        StringBuilder sb = new StringBuilder();
        int b;
        while ((b = in.read()) >= 0) {
            if (b == '\r') {
                in.read();
                return sb.toString();
            }
            sb.append((char) b);
        }
        return null;
    }

    /** Not covered by the Python parity scenarios: AUTH and SELECT come from the url, before the first command. */
    @Test
    void clientSendsAuthAndSelectBeforeTheFirstCommand() throws Exception {
        List<List<String>> seen = java.util.Collections.synchronizedList(new java.util.ArrayList<>());
        try (java.net.ServerSocket ss = new java.net.ServerSocket(0, 5, java.net.InetAddress.getByName("127.0.0.1"))) {
            Thread t = new Thread(() -> {
                try (java.net.Socket s = ss.accept()) {
                    java.io.InputStream in = new java.io.BufferedInputStream(s.getInputStream());
                    for (int i = 0; i < 3; i++) {
                        int n = Integer.parseInt(readLine(in).substring(1));
                        List<String> cmd = new java.util.ArrayList<>();
                        for (int k = 0; k < n; k++) {
                            int len = Integer.parseInt(readLine(in).substring(1));
                            cmd.add(new String(in.readNBytes(len), StandardCharsets.UTF_8));
                            in.readNBytes(2);
                        }
                        seen.add(cmd);
                        s.getOutputStream().write("+OK\r\n".getBytes(StandardCharsets.US_ASCII));
                        s.getOutputStream().flush();
                    }
                } catch (Exception e) {
                    e.printStackTrace();
                }
            });
            t.start();
            try (RespClient c = new RespClient("redis://user:p%40w@127.0.0.1:" + ss.getLocalPort() + "/3?ignored=1")) {
                assertEquals("OK", c.command("PING"));
            }
            t.join(5000);
        }
        assertEquals(List.of(List.of("AUTH", "user", "p@w"), List.of("SELECT", "3"), List.of("PING")), seen);
    }

    @Test
    void urlIsRequiredAndSchemeChecked(@TempDir Path tmp) {
        String reg = tmp.resolve("r.sqlite3").toString();
        assertThrows(IllegalArgumentException.class, () -> new RedisBackend("", "i", null, reg));
        assertThrows(IllegalArgumentException.class, () -> new RedisBackend(null, "i", null, reg));
        RedisBackend be = null;
        try {
            be = new RedisBackend("http://x:1", "i", null, reg);
            RedisBackend finalBe = be;
            assertThrows(IllegalArgumentException.class, () -> finalBe.initSchema(8));
        } catch (java.sql.SQLException e) {
            throw new IllegalStateException(e);
        }
    }
}
