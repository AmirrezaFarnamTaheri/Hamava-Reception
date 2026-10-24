package ir.hamava.reception;

import org.junit.Test;
import static org.junit.Assert.*;

public class ServerPolicyTest {
    @Test public void acceptsSecureOrigins() {
        assertEquals("https://clinic.example", ServerPolicy.origin("https://clinic.example/"));
        assertEquals("https://127.0.0.1:8443", ServerPolicy.origin("https://127.0.0.1:8443"));
    }
    @Test public void rejectsUntrustedProfiles() {
        for (String url : new String[]{"http://clinic.example", "http://127.0.0.1:8000", "http://localhost:8000", "http://[::1]:8000", "file:///tmp/test", "https://user:pass@clinic.example", "https://clinic.example/api", "https://clinic.example?q=secret", "https://clinic.example/#secret", "https://clinic.example:99999"}) {
            try { ServerPolicy.origin(url); fail(url); } catch (IllegalArgumentException expected) { }
        }
    }
    @Test public void rejectsLocalApplicationLaunches() {
        for (String url : new String[]{"javascript:alert(1)", "file:///etc/passwd", "intent://example", "https://user@clinic.example"}) {
            try { ServerPolicy.external(url); fail(url); } catch (IllegalArgumentException expected) { }
        }
    }
    @Test public void rejectsMalformedOrOversizedVaultValues() {
        assertTrue(ServerPolicy.token("aaaaaaaaaaaaaaaaaaaa.bbbbbbbbbbbbbbbbbbbb.cccccccccccccccccccc"));
        assertFalse(ServerPolicy.token(null));
        assertFalse(ServerPolicy.token("not a token"));
        assertFalse(ServerPolicy.token(new String(new char[17000]).replace('\0', 'x')));
    }
}
