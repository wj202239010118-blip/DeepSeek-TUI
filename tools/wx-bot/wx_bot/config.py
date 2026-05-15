"""Configuration loader for wx-bot."""

import json
from pathlib import Path
from dataclasses import dataclass, field


@dataclass
class MouseConfig:
    bezier_waypoints: tuple = (3, 6)
    speed_min: int = 400
    speed_max: int = 1200
    overshoot_pct: float = 0.15
    overshoot_distance: tuple = (5, 20)


@dataclass
class WindowConfig:
    focus_delay_ms: tuple = (200, 800)
    post_click_pause_ms: tuple = (100, 400)


@dataclass
class DelayConfig:
    action_interval_ms: tuple = (500, 3000)
    typing_delay_ms: tuple = (80, 250)
    think_time_ms: tuple = (2000, 8000)


@dataclass
class SleepConfig:
    enabled: bool = True
    night_start: str = "23:00"
    night_end: str = "07:00"
    sleep_duration_hours: tuple = (6, 8)
    weekend_sleep_in_hours: tuple = (0, 2)


@dataclass
class TemplateConfig:
    synonym_rate: float = 0.3
    emoji_rate: float = 0.4
    tone_variants: list = field(default_factory=lambda: ["casual", "enthusiastic", "neutral"])
    default_tone: str = "casual"


@dataclass
class AntiDetectConfig:
    mouse: MouseConfig = field(default_factory=MouseConfig)
    window: WindowConfig = field(default_factory=WindowConfig)
    delay: DelayConfig = field(default_factory=DelayConfig)
    sleep: SleepConfig = field(default_factory=SleepConfig)
    template: TemplateConfig = field(default_factory=TemplateConfig)


@dataclass
class WxCliConfig:
    exe_path: str = ""
    daemon_auto_start: bool = True


@dataclass
class WeChatConfig:
    process_name: str = "Weixin.exe"
    window_title_contains: str = "微信"
    window_class_contains: str = "WeChatMainWndForPC"


@dataclass
class SafetyConfig:
    max_daily_moments: int = 3
    max_daily_messages: int = 50
    min_interval_between_moments_minutes: int = 120
    cooldown_after_flag_minutes: int = 1440


@dataclass
class BotConfig:
    wx_cli: WxCliConfig = field(default_factory=WxCliConfig)
    wechat: WeChatConfig = field(default_factory=WeChatConfig)
    anti_detect: AntiDetectConfig = field(default_factory=AntiDetectConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)

    @classmethod
    def load(cls, path: Path | None = None) -> "BotConfig":
        if path is None:
            path = Path(__file__).parent.parent / "config.json"

        if not path.exists():
            return cls()

        with open(path, encoding="utf-8") as f:
            raw = json.load(f)

        wx_cli = WxCliConfig(
            exe_path=raw.get("wx_cli", {}).get("exe_path", ""),
            daemon_auto_start=raw.get("wx_cli", {}).get("daemon_auto_start", True),
        )

        wechat = WeChatConfig(
            process_name=raw.get("wechat", {}).get("process_name", "Weixin.exe"),
            window_title_contains=raw.get("wechat", {}).get("window_title_contains", "微信"),
            window_class_contains=raw.get("wechat", {}).get("window_class_contains", ""),
        )

        ad_raw = raw.get("anti_detect", {})
        mouse = MouseConfig(
            bezier_waypoints=tuple(ad_raw.get("mouse", {}).get("bezier_waypoints", [3, 6])),
            speed_min=ad_raw.get("mouse", {}).get("speed_min", 400),
            speed_max=ad_raw.get("mouse", {}).get("speed_max", 1200),
            overshoot_pct=ad_raw.get("mouse", {}).get("overshoot_pct", 0.15),
            overshoot_distance=tuple(ad_raw.get("mouse", {}).get("overshoot_distance", [5, 20])),
        )
        win = WindowConfig(
            focus_delay_ms=tuple(ad_raw.get("window", {}).get("focus_delay_ms", [200, 800])),
            post_click_pause_ms=tuple(ad_raw.get("window", {}).get("post_click_pause_ms", [100, 400])),
        )
        delay = DelayConfig(
            action_interval_ms=tuple(ad_raw.get("delay", {}).get("action_interval_ms", [500, 3000])),
            typing_delay_ms=tuple(ad_raw.get("delay", {}).get("typing_delay_ms", [80, 250])),
            think_time_ms=tuple(ad_raw.get("delay", {}).get("think_time_ms", [2000, 8000])),
        )
        sleep = SleepConfig(
            enabled=ad_raw.get("sleep", {}).get("enabled", True),
            night_start=ad_raw.get("sleep", {}).get("night_start", "23:00"),
            night_end=ad_raw.get("sleep", {}).get("night_end", "07:00"),
            sleep_duration_hours=tuple(ad_raw.get("sleep", {}).get("sleep_duration_hours", [6, 8])),
            weekend_sleep_in_hours=tuple(ad_raw.get("sleep", {}).get("weekend_sleep_in_hours", [0, 2])),
        )
        tpl = TemplateConfig(
            synonym_rate=ad_raw.get("template", {}).get("synonym_rate", 0.3),
            emoji_rate=ad_raw.get("template", {}).get("emoji_rate", 0.4),
            tone_variants=ad_raw.get("template", {}).get("tone_variants", ["casual", "enthusiastic", "neutral"]),
            default_tone=ad_raw.get("template", {}).get("default_tone", "casual"),
        )
        anti_detect = AntiDetectConfig(mouse=mouse, window=win, delay=delay, sleep=sleep, template=tpl)

        safety = SafetyConfig(
            max_daily_moments=raw.get("safety", {}).get("max_daily_moments", 3),
            max_daily_messages=raw.get("safety", {}).get("max_daily_messages", 50),
            min_interval_between_moments_minutes=raw.get("safety", {}).get("min_interval_between_moments_minutes", 120),
            cooldown_after_flag_minutes=raw.get("safety", {}).get("cooldown_after_flag_minutes", 1440),
        )

        return cls(wx_cli=wx_cli, wechat=wechat, anti_detect=anti_detect, safety=safety)


_config: BotConfig | None = None


def get_config() -> BotConfig:
    global _config
    if _config is None:
        _config = BotConfig.load()
    return _config
