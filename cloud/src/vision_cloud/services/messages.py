"""Alert message text in English and Arabic (CLD-08).

Channels (WhatsApp templates, Telegram, email) render `AlertMessage` in their own format; the
words come from here so both languages stay in one place. The edge's own `Event.message` is
English and detailed ("Queue of 7 ... longest wait 1m 00s"); it is shown in English messages
only, and Arabic messages use the translated rule label.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

RULE_LABELS: dict[str, dict[str, str]] = {
    "zone_occupancy_over": {"en": "Too many people", "ar": "ازدحام في المنطقة"},
    "queue_length_over": {"en": "Queue too long", "ar": "طابور طويل"},
    "zone_empty": {"en": "Station unattended", "ar": "المكان بدون موظف"},
    "presence_after_hours": {"en": "Someone on site after hours", "ar": "وجود خارج ساعات العمل"},
    "dwell_over": {"en": "Staying too long", "ar": "بقاء طويل في المنطقة"},
    "line_crossing": {"en": "Busy entrance", "ar": "حركة كثيفة عند المدخل"},
}

SEVERITY: dict[str, dict[str, str]] = {
    "info": {"en": "Info", "ar": "معلومة", "icon": "ℹ️"},
    "warning": {"en": "Warning", "ar": "تنبيه", "icon": "⚠️"},
    "critical": {"en": "Critical", "ar": "حرج", "icon": "🚨"},
}

TEXT: dict[str, dict[str, str]] = {
    "camera": {"en": "Camera", "ar": "الكاميرا"},
    "site": {"en": "Site", "ar": "الموقع"},
    "time": {"en": "Time", "ar": "الوقت"},
    "events": {"en": "Events in this alert", "ar": "عدد الأحداث في هذا التنبيه"},
    "escalated": {"en": "Escalated: nobody has responded yet", "ar": "تصعيد: لم يرد أحد بعد"},
}


@dataclass(frozen=True)
class AlertMessage:
    language: str
    title: str
    body: str
    severity: str
    snapshot_url: str | None = None

    @property
    def text(self) -> str:
        return f"{self.title}\n{self.body}"


def label(rule_type: str, language: str) -> str:
    return RULE_LABELS.get(rule_type, {}).get(language) or rule_type.replace("_", " ")


def render(
    *,
    language: str,
    rule_type: str,
    rule_name: str,
    severity: str,
    camera: str,
    site: str,
    timezone: str,
    triggered_at: datetime,
    edge_message: str,
    event_count: int = 1,
    escalated: bool = False,
    snapshot_url: str | None = None,
) -> AlertMessage:
    lang = "ar" if language == "ar" else "en"
    sev = SEVERITY.get(severity, SEVERITY["warning"])
    local = triggered_at.astimezone(ZoneInfo(timezone)).strftime("%H:%M")
    heading = rule_name.strip() if lang == "en" and rule_name.strip() else label(rule_type, lang)
    title = f"{sev['icon']} {sev[lang]}: {heading}"
    lines = []
    if escalated:
        lines.append(TEXT["escalated"][lang])
    if lang == "en" and edge_message:
        lines.append(edge_message)
    lines += [
        f"{TEXT['camera'][lang]}: {camera}",
        f"{TEXT['site'][lang]}: {site}",
        f"{TEXT['time'][lang]}: {local}",
    ]
    if event_count > 1:
        lines.append(f"{TEXT['events'][lang]}: {event_count}")
    return AlertMessage(lang, title, "\n".join(lines), severity, snapshot_url)
