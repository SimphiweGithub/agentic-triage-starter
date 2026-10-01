package za.kinguard.app;

import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.Context;
import android.content.SharedPreferences;
import android.os.Build;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;

import org.json.JSONArray;
import org.json.JSONException;
import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Locale;
import java.util.TimeZone;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.regex.Pattern;

/**
 * Sends messages caught on the phone straight to the Scam Stop server, without the app being open.
 * The app only stores where to send them (server, person, pairing code) and the privacy filter.
 * Anything that cannot be sent waits in a small queue and goes with the next message.
 */
final class Forwarder {
    private static final String PREFS = "scamstop.bridge";
    private static final int MAX_QUEUE = 200;
    private static final String CHANNEL = "scamstop.warnings";
    private static final ExecutorService WORKER = Executors.newSingleThreadExecutor();  // one at a time, in order

    private Forwarder() {}

    static SharedPreferences prefs(Context context) {
        return context.getSharedPreferences(PREFS, Context.MODE_PRIVATE);
    }

    /** Saved by the app after pairing. `patterns` is the server's privacy filter, from GET /api/privacy/patterns. */
    static void configure(Context context, String server, String person, String code, JSONArray patterns) {
        prefs(context).edit().putString("server", server).putString("person", person).putString("code", code)
            .putString("patterns", patterns.toString()).apply();
    }

    static boolean configured(Context context) {
        SharedPreferences prefs = prefs(context);
        return !prefs.getString("server", "").isEmpty() && !prefs.getString("person", "").isEmpty();
    }

    /** True when the text hands over a one-time PIN, password or recovery code: such a message never leaves the phone. */
    static boolean withheld(Context context, String text) {
        try {
            JSONArray patterns = new JSONArray(prefs(context).getString("patterns", "[]"));
            for (int index = 0; index < patterns.length(); index++) {
                if (Pattern.compile(patterns.getString(index), Pattern.CASE_INSENSITIVE).matcher(text).find()) {
                    return true;
                }
            }
            return false;
        } catch (JSONException error) {
            return true;  // no usable filter: send nothing rather than risk a code
        }
    }

    /** Queue one message and try to send everything waiting. Runs off the main thread. */
    static void forward(Context context, String channel, String sender, String text, long millis) {
        forward(context, channel, sender, text, millis, null);
    }

    /** The same, then `done` once it has been sent or queued, so a receiver can let Android go only then. */
    static void forward(Context context, String channel, String sender, String text, long millis, Runnable done) {
        Context app = context.getApplicationContext();
        WORKER.execute(() -> {
            try {
                send(app, channel, sender, text, millis);
            } finally {
                if (done != null) {
                    done.run();
                }
            }
        });
    }

    private static void send(Context app, String channel, String sender, String text, long millis) {
        if (!configured(app) || text == null || text.trim().isEmpty() || withheld(app, text)) {
            return;
        }
        try {
            if (!firstTime(app, channel + "|" + sender + "|" + millis / 1000 + "|" + text)) {
                return;  // chat apps re-post earlier messages with every new one
            }
            JSONArray queue = new JSONArray(prefs(app).getString("queue", "[]"));
            queue.put(new JSONObject().put("text", text).put("sender", sender == null ? "" : sender)
                .put("channel", channel).put("timestamp", iso(millis)));
            while (queue.length() > MAX_QUEUE) {
                queue.remove(0);  // keep the newest if the server has been away a long time
            }
            prefs(app).edit().putString("queue", queue.toString()).apply();
            flush(app);
        } catch (JSONException ignored) {
            // a message that cannot be written as JSON is dropped
        }
    }

    /** Send the queue to the server; on success, empty it and warn the person about anything the agent flagged. */
    private static void flush(Context app) {
        SharedPreferences prefs = prefs(app);
        String queued = prefs.getString("queue", "[]");
        if ("[]".equals(queued)) {
            return;
        }
        try {
            String person = URLEncoder.encode(prefs.getString("person", ""), "UTF-8");
            URL url = new URL(prefs.getString("server", "") + "/api/people/" + person + "/intake/share/batch");
            HttpURLConnection connection = (HttpURLConnection) url.openConnection();
            connection.setConnectTimeout(8000);
            connection.setReadTimeout(30000);
            connection.setRequestMethod("POST");
            connection.setDoOutput(true);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setRequestProperty("X-Device-Key", prefs.getString("code", ""));
            try (OutputStream body = connection.getOutputStream()) {
                body.write(queued.getBytes(StandardCharsets.UTF_8));
            }
            int status = connection.getResponseCode();
            if (status / 100 != 2) {
                note(prefs, "Server answered " + status + (status == 401 ? ": pair the phone again" : ""));
                return;
            }
            JSONArray decisions = new JSONArray(read(connection.getInputStream()));
            int sent = new JSONArray(queued).length();
            prefs.edit().putString("queue", "[]").putLong("sent", prefs.getLong("sent", 0) + sent)
                .putString("lastSent", iso(System.currentTimeMillis())).remove("lastError").apply();
            warn(app, decisions);
        } catch (Exception error) {  // offline, server down: the queue waits for the next message
            note(prefs, error.getClass().getSimpleName() + ": " + error.getMessage());
        }
    }

    /** A warning the agent sent the person becomes a phone notification at once, even with the app closed. */
    private static void warn(Context app, JSONArray decisions) throws JSONException {
        List<String> messages = new ArrayList<>();
        for (int index = 0; index < decisions.length(); index++) {
            JSONObject decision = decisions.getJSONObject(index);
            JSONObject action = decision.optJSONObject("proposed_action");
            if (action != null && "EXECUTED".equals(decision.optString("action_outcome"))) {
                String message = action.optJSONObject("details") == null ? "" : action.getJSONObject("details").optString("message");
                if (!message.isEmpty()) {
                    messages.add(message);
                }
            }
        }
        if (messages.isEmpty() || !NotificationManagerCompat.from(app).areNotificationsEnabled()) {
            return;
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            NotificationManager manager = app.getSystemService(NotificationManager.class);
            manager.createNotificationChannel(new NotificationChannel(CHANNEL, "Scam warnings", NotificationManager.IMPORTANCE_HIGH));
        }
        for (String message : messages) {
            try {
                NotificationManagerCompat.from(app).notify((int) (System.nanoTime() & 0x7fffffff),
                    new NotificationCompat.Builder(app, CHANNEL).setSmallIcon(R.mipmap.ic_launcher).setContentTitle("Scam Stop")
                        .setContentText(message).setStyle(new NotificationCompat.BigTextStyle().bigText(message))
                        .setPriority(NotificationCompat.PRIORITY_HIGH).setAutoCancel(true).build());
            } catch (SecurityException ignored) {
                // notification permission withdrawn: the warning is still on the dashboard and in the app
            }
        }
    }

    /** True the first time a message is seen. Only a hash is kept, of the last 500 messages. */
    private static boolean firstTime(Context app, String key) throws JSONException {
        String hash = Integer.toHexString(key.hashCode());
        JSONArray seen = new JSONArray(prefs(app).getString("seen", "[]"));
        for (int index = 0; index < seen.length(); index++) {
            if (hash.equals(seen.getString(index))) {
                return false;
            }
        }
        seen.put(hash);
        while (seen.length() > 500) {
            seen.remove(0);
        }
        prefs(app).edit().putString("seen", seen.toString()).apply();
        return true;
    }

    private static void note(SharedPreferences prefs, String error) {
        prefs.edit().putString("lastError", error).apply();
    }

    private static String read(InputStream stream) throws java.io.IOException {
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            for (int count; (count = input.read(buffer)) != -1; ) {
                output.write(buffer, 0, count);
            }
            return output.toString("UTF-8");
        }
    }

    /** The time as ISO 8601 in UTC; the server builds the message's id from it, so a message sent twice is processed once. */
    static String iso(long millis) {
        SimpleDateFormat format = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.US);
        format.setTimeZone(TimeZone.getTimeZone("UTC"));
        return format.format(new Date(millis));
    }
}
