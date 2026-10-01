package za.kinguard.app;

import android.app.Notification;
import android.content.ComponentName;
import android.content.Context;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import androidx.core.app.NotificationCompat;

import java.util.HashMap;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * Hears notifications from messaging apps once the person has allowed notification access in Android
 * settings. Android keeps this service running by itself, so WhatsApp messages are checked even when
 * Scam Stop is closed. Only the listed apps are read; everything else is ignored, never sent.
 */
public class NotificationBridge extends NotificationListenerService {
    /** Package name -> the channel name the server records. SMS is not here: SmsReceiver handles texts. */
    private static final Map<String, String> APPS = new HashMap<>();
    static {
        APPS.put("com.whatsapp", "whatsapp");
        APPS.put("com.whatsapp.w4b", "whatsapp");
        APPS.put("org.telegram.messenger", "telegram");
        APPS.put("com.facebook.orca", "messenger");
        APPS.put("org.thoughtcrime.securesms", "signal");
    }
    private static final Pattern SUMMARY = Pattern.compile("^\\d+ new messages?( from \\d+ chats?)?$|^Checking for new messages$", Pattern.CASE_INSENSITIVE);

    /** Ask Android to connect the listener again. It drops it when the app is updated and does not always come back by itself. */
    static void rebind(Context context) {
        requestRebind(new ComponentName(context, NotificationBridge.class));
    }

    @Override
    public void onListenerDisconnected() {
        rebind(this);
    }

    /** On connecting, check what is already in the tray: messages that came while the listener was away. Repeats are skipped. */
    @Override
    public void onListenerConnected() {
        Forwarder.retry(this);
        try {
            for (StatusBarNotification posted : getActiveNotifications()) {
                onNotificationPosted(posted);
            }
        } catch (RuntimeException ignored) {
            // Android can refuse while it is still connecting; new messages still arrive as usual
        }
    }

    @Override
    public void onNotificationPosted(StatusBarNotification posted) {
        String channel = APPS.get(posted.getPackageName());
        if (channel == null) {
            return;
        }
        Notification notification = posted.getNotification();
        if ((notification.flags & Notification.FLAG_GROUP_SUMMARY) != 0) {
            return;  // "3 new messages" rolls up others we read one by one
        }
        NotificationCompat.MessagingStyle style = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(notification);
        if (style != null) {
            // Chat apps list each message with its own sender and time, so each is forwarded once.
            for (NotificationCompat.MessagingStyle.Message message : style.getMessages()) {
                if (message.getPerson() == null || message.getText() == null) {
                    continue;  // a message with no person is the phone owner's own reply
                }
                CharSequence name = message.getPerson().getName();
                Forwarder.forward(this, channel, name == null ? "" : name.toString(), message.getText().toString(), message.getTimestamp());
            }
            return;
        }
        Bundle extras = notification.extras;
        CharSequence title = extras.getCharSequence(Notification.EXTRA_TITLE);
        CharSequence text = extras.getCharSequence(Notification.EXTRA_BIG_TEXT);
        if (text == null) {
            text = extras.getCharSequence(Notification.EXTRA_TEXT);
        }
        if (text == null || SUMMARY.matcher(text.toString().trim()).find()) {
            return;
        }
        Forwarder.forward(this, channel, title == null ? "" : title.toString(), text.toString(), posted.getPostTime());
    }
}
