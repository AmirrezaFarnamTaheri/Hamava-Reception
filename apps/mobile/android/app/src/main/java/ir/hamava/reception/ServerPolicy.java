package ir.hamava.reception;

import java.net.URI;
import java.util.Locale;

/** A clinic connection is an origin, never a URL carrying credentials or a path. */
public final class ServerPolicy {
    private ServerPolicy() {}

    public static String origin(String value) {
        if (value == null || value.length() > 2048) throw new IllegalArgumentException("Invalid server");
        URI uri = URI.create(value);
        String host = uri.getHost();
        String scheme = uri.getScheme();
        if (host == null || scheme == null || uri.getRawUserInfo() != null || uri.getRawQuery() != null || uri.getRawFragment() != null ||
            !"https".equals(scheme) ||
            !(uri.getRawPath() == null || uri.getRawPath().isEmpty() || "/".equals(uri.getRawPath())) ||
            uri.getPort() < -1 || uri.getPort() > 65535 || uri.getPort() == 0)
            throw new IllegalArgumentException("Invalid server origin");
        return scheme + "://" + host.toLowerCase(Locale.ROOT) + (uri.getPort() == -1 ? "" : ":" + uri.getPort());
    }

    public static String external(String value) {
        URI uri = URI.create(value);
        if (uri.getHost() == null || uri.getRawUserInfo() != null ||
            !("https".equals(uri.getScheme()) || "http".equals(uri.getScheme())))
            throw new IllegalArgumentException("Unsupported external link");
        return uri.toString();
    }

    public static boolean token(String value) {
        return value != null && value.length() >= 32 && value.length() <= 16384 &&
            value.matches("[A-Za-z0-9_=-]+\\.[A-Za-z0-9_=-]+\\.[A-Za-z0-9_=-]+");
    }
}
