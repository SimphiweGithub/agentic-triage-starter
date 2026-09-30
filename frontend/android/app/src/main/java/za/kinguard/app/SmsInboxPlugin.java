package za.kinguard.app;

import android.Manifest;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.database.Cursor;
import android.provider.Telephony;
import android.telephony.SmsMessage;

import androidx.core.content.ContextCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.PermissionState;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;
import java.util.TimeZone;

/**
 * Reads the phone's SMS inbox and reports new texts as they arrive.
 * It only reads; it never sends, deletes or changes a message.
 */
@CapacitorPlugin(
    name = "SmsInbox",
    permissions = { @Permission(strings = { Manifest.permission.READ_SMS, Manifest.permission.RECEIVE_SMS }, alias = "sms") }
)
public class SmsInboxPlugin extends Plugin {

    private BroadcastReceiver receiver;

    @Override
    public void load() {
        if (getPermissionState("sms") == PermissionState.GRANTED) {
            listen();
        }
    }

    /** Asks for SMS access if needed. Resolves with {granted: true|false}. */
    @PluginMethod
    public void requestAccess(PluginCall call) {
        if (getPermissionState("sms") == PermissionState.GRANTED) {
            listen();
            call.resolve(new JSObject().put("granted", true));
        } else {
            requestPermissionForAlias("sms", call, "accessAnswered");
        }
    }

    @PermissionCallback
    private void accessAnswered(PluginCall call) {
        boolean granted = getPermissionState("sms") == PermissionState.GRANTED;
        if (granted) {
            listen();
        }
        call.resolve(new JSObject().put("granted", granted));
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

    /** Hear each new text the moment it arrives, while the app is running. */
    private void listen() {
        if (receiver != null) {
            return;
        }
        receiver = new BroadcastReceiver() {
            @Override
            public void onReceive(Context context, Intent intent) {
                SmsMessage[] parts = Telephony.Sms.Intents.getMessagesFromIntent(intent);
                if (parts == null || parts.length == 0) {
                    return;
                }
                StringBuilder body = new StringBuilder();  // a long text arrives in several parts
                for (SmsMessage part : parts) {
                    body.append(part.getMessageBody());
                }
                notifyListeners("smsReceived", message(parts[0].getOriginatingAddress(), body.toString(), parts[0].getTimestampMillis()));
            }
        };
        ContextCompat.registerReceiver(getContext(), receiver, new IntentFilter(Telephony.Sms.Intents.SMS_RECEIVED_ACTION),
            ContextCompat.RECEIVER_EXPORTED);
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

    @Override
    protected void handleOnDestroy() {
        if (receiver != null) {
            getContext().unregisterReceiver(receiver);
            receiver = null;
        }
    }
}
