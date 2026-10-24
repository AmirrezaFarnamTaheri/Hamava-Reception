package ir.hamava.reception;

import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import android.util.Base64;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import java.nio.charset.StandardCharsets;
import java.security.KeyStore;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.json.JSONObject;

@CapacitorPlugin(name = "HamavaDevice")
public class HamavaDevicePlugin extends Plugin {
    private static final String ALIAS = "hamava.session.v1";
    private static final String PREFS = "hamava_secure_session";
    private static final String RECORD = "encrypted_record";

    private SharedPreferences preferences() {
        return getContext().getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    private SecretKey key() throws Exception {
        KeyStore keys = KeyStore.getInstance("AndroidKeyStore");
        keys.load(null);
        if (!keys.containsAlias(ALIAS)) {
            KeyGenerator generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT | KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256).setRandomizedEncryptionRequired(true).build());
            generator.generateKey();
        }
        return ((KeyStore.SecretKeyEntry) keys.getEntry(ALIAS, null)).getSecretKey();
    }

    @PluginMethod
    public synchronized void getInfo(PluginCall call) {
        boolean available;
        try { key(); available = true; } catch (Exception ignored) { available = false; }
        JSObject result = new JSObject();
        result.put("version", BuildConfig.VERSION_NAME);
        result.put("secureStorage", available);
        call.resolve(result);
    }

    @PluginMethod
    public synchronized void readSession(PluginCall call) {
        JSObject result = new JSObject();
        result.put("token", JSONObject.NULL);
        try {
            String server = ServerPolicy.origin(call.getString("server"));
            String record = preferences().getString(RECORD, null);
            if (record != null) {
                if (record.length() > 32768) throw new IllegalArgumentException("Invalid record");
                String[] parts = record.split(":", 2);
                if (parts.length != 2) throw new IllegalArgumentException("Invalid record");
                byte[] iv = Base64.decode(parts[0], Base64.NO_WRAP);
                if (iv.length != 12) throw new IllegalArgumentException("Invalid nonce");
                Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
                cipher.init(Cipher.DECRYPT_MODE, key(), new GCMParameterSpec(128, iv));
                cipher.updateAAD(ALIAS.getBytes(StandardCharsets.UTF_8));
                JSONObject data = new JSONObject(new String(cipher.doFinal(Base64.decode(parts[1], Base64.NO_WRAP)), StandardCharsets.UTF_8));
                String token = data.optString("token");
                if (server.equals(data.optString("server")) && ServerPolicy.token(token)) result.put("token", token);
            }
            call.resolve(result);
        } catch (Exception ignored) {
            // Invalidated/tampered keys fail closed and require a fresh staff login.
            preferences().edit().clear().commit();
            call.resolve(result);
        }
    }

    @PluginMethod
    public synchronized void writeSession(PluginCall call) {
        try {
            String server = ServerPolicy.origin(call.getString("server"));
            String token = call.getString("token");
            if (!ServerPolicy.token(token)) throw new IllegalArgumentException("Invalid token");
            JSONObject data = new JSONObject().put("server", server).put("token", token);
            Cipher cipher = Cipher.getInstance("AES/GCM/NoPadding");
            cipher.init(Cipher.ENCRYPT_MODE, key());
            cipher.updateAAD(ALIAS.getBytes(StandardCharsets.UTF_8));
            String record = Base64.encodeToString(cipher.getIV(), Base64.NO_WRAP) + ":" +
                Base64.encodeToString(cipher.doFinal(data.toString().getBytes(StandardCharsets.UTF_8)), Base64.NO_WRAP);
            if (!preferences().edit().putString(RECORD, record).commit()) throw new IllegalStateException("Storage failed");
            call.resolve();
        } catch (Exception ignored) {
            call.reject("Secure device storage is unavailable; the session remains in memory only.");
        }
    }

    @PluginMethod
    public synchronized void clearSession(PluginCall call) {
        try {
            // Destroy the key as well as the ciphertext, including after interrupted writes.
            KeyStore keys = KeyStore.getInstance("AndroidKeyStore");
            keys.load(null);
            keys.deleteEntry(ALIAS);
            if (!preferences().edit().clear().commit()) throw new IllegalStateException("Storage failed");
            call.resolve();
        } catch (Exception ignored) { call.reject("Could not clear device session."); }
    }

    @PluginMethod
    public void openExternal(PluginCall call) {
        try {
            String url = ServerPolicy.external(call.getString("url"));
            getActivity().startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)).addCategory(Intent.CATEGORY_BROWSABLE));
            call.resolve();
        } catch (Exception ignored) { call.reject("Could not open this link."); }
    }
}
