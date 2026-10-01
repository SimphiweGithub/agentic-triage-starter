package za.kinguard.app;

import android.os.Bundle;

import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(SmsInboxPlugin.class);  // our own plugins: registered before the bridge starts
        registerPlugin(CallMonitorPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
