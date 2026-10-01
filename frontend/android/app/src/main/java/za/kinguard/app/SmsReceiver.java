package za.kinguard.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Telephony;
import android.telephony.SmsMessage;

/**
 * Declared in the manifest, so Android starts it for every new text even when Scam Stop is closed.
 * It only reads the text and forwards it; it never blocks, deletes or answers a message.
 */
public class SmsReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Telephony.Sms.Intents.SMS_RECEIVED_ACTION.equals(intent.getAction())) {
            return;
        }
        SmsMessage[] parts = Telephony.Sms.Intents.getMessagesFromIntent(intent);
        if (parts == null || parts.length == 0) {
            return;
        }
        StringBuilder body = new StringBuilder();  // a long text arrives in several parts
        for (SmsMessage part : parts) {
            body.append(part.getMessageBody());
        }
        PendingResult pending = goAsync();  // keep Android from stopping us until the text is sent or queued
        Forwarder.forward(context, "sms", parts[0].getOriginatingAddress(), body.toString(), parts[0].getTimestampMillis(), pending::finish);
    }
}
