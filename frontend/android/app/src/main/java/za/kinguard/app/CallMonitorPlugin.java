package za.kinguard.app;

import android.Manifest;
import android.content.Context;
import android.content.SharedPreferences;

import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

/**
 * Lets the app switch the call reminders on or off and ask for the one permission they need:
 * the phone's call state. CallReceiver does the work, with or without the app open.
 */
@CapacitorPlugin(
    name = "CallMonitor",
    permissions = { @Permission(strings = { Manifest.permission.READ_PHONE_STATE }, alias = "phone") }
)
public class CallMonitorPlugin extends Plugin {

    private SharedPreferences prefs() {
        return getContext().getSharedPreferences(CallReceiver.PREFS, Context.MODE_PRIVATE);
    }

    /** Asks for call-state access if needed. Resolves with {granted}. */
    @PluginMethod
    public void requestAccess(PluginCall call) {
        if (getPermissionState("phone") == PermissionState.GRANTED) {
            call.resolve(new JSObject().put("granted", true));
        } else {
            requestPermissionForAlias("phone", call, "accessAnswered");
        }
    }

    @PermissionCallback
    private void accessAnswered(PluginCall call) {
        call.resolve(new JSObject().put("granted", getPermissionState("phone") == PermissionState.GRANTED));
    }

    /** Whether reminders can work, whether they are on, and when the last incoming call ended. Never who called. */
    @PluginMethod
    public void status(PluginCall call) {
        SharedPreferences prefs = prefs();
        long last = prefs.getLong("lastCallAt", 0);
        call.resolve(new JSObject().put("granted", getPermissionState("phone") == PermissionState.GRANTED)
            .put("enabled", prefs.getBoolean("enabled", true)).put("calls", prefs.getInt("calls", 0))
            .put("lastCall", last == 0 ? "" : Forwarder.iso(last)).put("lastAnswered", prefs.getBoolean("lastAnswered", false))
            .put("tips", CallReceiver.TIPS));
    }

    /** Switch the reminders on or off. */
    @PluginMethod
    public void setEnabled(PluginCall call) {
        prefs().edit().putBoolean("enabled", call.getBoolean("enabled", true)).apply();
        call.resolve();
    }
}
