import urllib.parse
import urllib.request

from django.utils import timezone

from parking.constants import NUMERIC_SETTING_KEYS, PARKING_SETTING_DEFAULTS
from parking.models import ParkingNotification, ParkingSetting, ParkingShift


def get_setting(key, default_val=None):
    if default_val is None and key in PARKING_SETTING_DEFAULTS:
        default_val = PARKING_SETTING_DEFAULTS[key][0]
    try:
        return ParkingSetting.objects.get(key=key).value
    except ParkingSetting.DoesNotExist:
        return default_val


def get_all_settings():
    return {key: float(get_setting(key)) for key in NUMERIC_SETTING_KEYS}


def dispatch_notification(notification_type, recipient, message):
    """Saves notification in DB and sends Telegram message when configured."""
    try:
        ParkingNotification.objects.create(
            notification_type=notification_type,
            recipient=recipient,
            message=message,
        )

        if notification_type != 'TELEGRAM':
            return

        bot_token = get_setting('telegram_bot_token', '')
        chat_id = get_setting('telegram_chat_id', '')
        if not bot_token or not chat_id:
            return

        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = urllib.parse.urlencode({
            'chat_id': chat_id,
            'text': message,
            'parse_mode': 'Markdown',
        }).encode('utf-8')
        req = urllib.request.Request(url, data=payload, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=5):
            pass
    except Exception as e:
        print(f"Notification dispatch error: {e}")


def get_active_shift():
    return ParkingShift.objects.filter(is_active=True).first()
