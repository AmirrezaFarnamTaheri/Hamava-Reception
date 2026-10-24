package ir.hamava.reception;

import android.os.Bundle;
import android.view.WindowManager;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(HamavaDevicePlugin.class);
        super.onCreate(savedInstanceState);
        // Keep reception details out of screenshots and the recent-apps preview.
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_SECURE);
    }
}
