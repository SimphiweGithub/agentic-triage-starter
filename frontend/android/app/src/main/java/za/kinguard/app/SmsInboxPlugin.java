package za.kinguard.app;

import android.Manifest;
import android.content.Intent;
import android.content.SharedPreferences;
import android.database.Cursor;
import android.provider.Settings;
import android.provider.Telephony;

import androidx.core.app.NotificationManagerCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import org.json.JSONArray;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * Reads the phone's SMS inbox for the first sync, and sets up the native bridge (SmsReceiver and
 * NotificationBridge) that forwards new messages to the server even when the app is closed.
 * It only reads; it never sends, deletes or changes a message.
 */
@CapacitorPlugin(
    name = "SmsInbox",
    permissions = { @Permission(strings = { Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS }, alias = "sms") }
)
public class SmsInboxPlugin extends Plugin {

    /** On every start, make sure Android has the notification listener connected (it can drop it after an update). */
    @Override
    public void load() {
        if (NotificationManagerCompat.getEnabledListenerPackages(getContext()).contains(getContext().getPackageName())) {
            NotificationBridge.rebind(getContext());
        }
    }

    /** Asks for SMS access if needed. Resolves with {granted: true|false}. */
    @PluginMethod
    public void requestAccess(PluginCall call) {
        if (getPermissionState("sms") == PermissionState.GRANTED) {
            call.resolve(new JSObject().put("granted", true));
        } else {
            requestPermissionForAlias("sms", call, "accessAnswered");
        }
    }

    @PermissionCallback
    private void accessAnswered(PluginCall call) {
        boolean granted = getPermissionState("sms") == PermissionState.GRANTED;
        call.resolve(new JSObject().put("granted", granted));
    }

    /** Save where the native bridge sends messages: server, person id, pairing code and the server's privacy patterns. */
    @PluginMethod
    public void configureBridge(PluginCall call) {
        try {
            JSONArray patterns = call.getArray("patterns", new com.getcapacitor.JSArray());
            Forwarder.configure(getContext(), call.getString("server", ""), call.getString("person", ""), call.getString("code", ""), patterns);
            call.resolve();
        } catch (Exception error) {
            call.reject("Could not save the bridge settings: " + error.getMessage());
        }
    }

    /** Whether the bridge can work, and how it is doing. */
    @PluginMethod
    public void bridgeStatus(PluginCall call) {
        SharedPreferences prefs = Forwarder.prefs(getContext());
        int queued;
        try {
            queued = new JSONArray(prefs.getString("queue", "[]")).length();
        } catch (Exception error) {
            queued = 0;
        }
        call.resolve(new JSObject()
            .put("notificationAccess", NotificationManagerCompat.getEnabledListenerPackages(getContext()).contains(getContext().getPackageName()))
            .put("sms", getPermissionState("sms") == PermissionState.GRANTED)
            .put("configured", Forwarder.configured(getContext()))
            .put("queued", queued)
            .put("sent", prefs.getLong("sent", 0))
            .put("lastSent", prefs.getString("lastSent", ""))
            .put("lastError", prefs.getString("lastError", "")));
    }

    /** Opens Android's notification access screen. Android only lets the person switch this on themselves. */
    @PluginMethod
    public void openNotificationAccess(PluginCall call) {
        Intent intent = new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        getContext().startActivity(intent);
        call.resolve();
    }

    /** Received texts newer than `since` (milliseconds), oldest first, at most `limit`. */
    @PluginMethod
    public void getMessages(PluginCall call) {
        if (getPermissionState("sms") != PermissionState.GRANTED) {
            call.reject("SMS access has not been granted");
            return;
        }
        long since = call.getLong("since", 0L);
        int limit = call.getInt("limit", 200);
        JSArray messages = new JSArray();
        String[] columns = { Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE };
        try (Cursor cursor = getContext().getContentResolver().query(
                Telephony.Sms.Inbox.CONTENT_URI, columns, Telephony.Sms.DATE + " > ?",
                new String[] { String.valueOf(since) }, Telephony.Sms.DATE + " ASC")) {
            while (cursor != null && cursor.moveToNext() && messages.length() < limit) {
                messages.put(message(cursor.getString(0), cursor.getString(1), cursor.getLong(2)));
            }
        }
        call.resolve(new JSObject().put("messages", messages));
    }

    private static JSObject message(String sender, String text, long millis) {
        return new JSObject()
            .put("sender", sender == null ? "" : sender)
            .put("text", text == null ? "" : text)
            .put("timestamp", iso(millis))
            .put("millis", millis);
    }

    /** The time as ISO 8601 in UTC, which the server uses to recognise a message it has already seen. */
    private static String iso(long millis) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date(millis));
    }
}
