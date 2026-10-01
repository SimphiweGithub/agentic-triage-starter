package za.kinguard.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.os.Build;
import android.telephony.TelephonyManager;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

/**
 * Hears that a call rang and then ended, and reminds the person of common call scams.
 *
 * It never listens to a call and never learns who called: Android only tells it the phone's state
 * (ringing, in a call, idle). The caller's number would need call-log access, which is not asked for.
 * Android delivers this broadcast even when the app is closed.
 */
public class CallReceiver extends BroadcastReceiver {
    static final String PREFS = "scamstop.calls";
    private static final String CHANNEL = "scamstop.calls";
    private static final long RECENT_WARNING_MS = 2 * 60 * 60 * 1000L;  // a call within 2 hours of a scam warning
    private static final int NOTIFICATION_ID = 7301;  // one call notification at a time; a new call replaces it

    static final String TIPS =
        "• A bank never asks for your PIN, OTP or card number.\n"
        + "• \"Your grandchild is in trouble, send money\": phone them on the number you already have.\n"
        + "• A prize you must pay a fee to collect is not a prize.\n"
        + "• Never read out a code sent to you by SMS: it lets them take your number and your bank.\n"
        + "• Tax, police or fines callers do not demand payment over the phone.\n"
        + "• Do not install anything a caller asks you to, such as AnyDesk.\n"
        + "Not sure? Hang up, then call the number on your card or bill yourself.";

    @Override
    public void onReceive(Context context, Intent intent) {
        if (!TelephonyManager.ACTION_PHONE_STATE_CHANGED.equals(intent.getAction())) {
            return;
        }
        String state = intent.getStringExtra(TelephonyManager.EXTRA_STATE);
        SharedPreferences prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
        if (TelephonyManager.EXTRA_STATE_RINGING.equals(state)) {
            prefs.edit().putBoolean("ringing", true).putBoolean("answered", false).apply();
        } else if (TelephonyManager.EXTRA_STATE_OFFHOOK.equals(state)) {
            if (prefs.getBoolean("ringing", false)) {
                prefs.edit().putBoolean("answered", true).apply();  // an incoming call was picked up; an outgoing one is ignored
            }
        } else if (TelephonyManager.EXTRA_STATE_IDLE.equals(state) && prefs.getBoolean("ringing", false)) {
            boolean answered = prefs.getBoolean("answered", false);
            prefs.edit().putBoolean("ringing", false).putLong("lastCallAt", System.currentTimeMillis())
                .putBoolean("lastAnswered", answered).putInt("calls", prefs.getInt("calls", 0) + 1).apply();
            if (prefs.getBoolean("enabled", true)) {
                remind(context, answered);
            }
        }
    }

    /** The notification: plain words, the common scams, and a stronger line if a scam message came just before. */
    private static void remind(Context context, boolean answered) {
        if (!NotificationManagerCompat.from(context).areNotificationsEnabled()) {
            return;
        }
        long lastWarning = Forwarder.prefs(context).getLong("lastWarningAt", 0);
        boolean afterScam = System.currentTimeMillis() - lastWarning < RECENT_WARNING_MS;
        String title = answered ? "You just had a phone call" : "You missed a phone call";
        String lead = afterScam
            ? "Scam Stop warned you about a scam message shortly before this call. Scammers often send a message first, then call. "
            + "If this caller mentioned that message, it is probably the same scam.\n\n"
            : "Scam Stop did not listen to the call. Here are common call scams to watch out for.\n\n";
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            context.getSystemService(NotificationManager.class)
                .createNotificationChannel(new NotificationChannel(CHANNEL, "Call safety tips", NotificationManager.IMPORTANCE_HIGH));
        }
        Intent open = context.getPackageManager().getLaunchIntentForPackage(context.getPackageName());
        PendingIntent tap = open == null ? null : PendingIntent.getActivity(context, 0, open, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        try {
            NotificationManagerCompat.from(context).notify(NOTIFICATION_ID,
                new NotificationCompat.Builder(context, CHANNEL).setSmallIcon(R.mipmap.ic_launcher).setContentTitle(title)
                    .setContentText(afterScam ? "This call came soon after a scam message. Be careful." : "Here are common call scams to watch out for.")
                    .setStyle(new NotificationCompat.BigTextStyle().bigText(lead + TIPS))
                    .setPriority(NotificationCompat.PRIORITY_HIGH).setContentIntent(tap).setAutoCancel(true).build());
        } catch (SecurityException ignored) {
            // notification permission withdrawn: nothing to show
        }
    }
}
