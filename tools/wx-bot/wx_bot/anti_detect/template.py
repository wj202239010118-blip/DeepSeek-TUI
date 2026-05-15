"""Content template randomization engine.

Makes automated messages less detectable by:
- Synonym substitution (random rate-based replacement)
- Random emoji insertion
- Tone variation (casual / enthusiastic / neutral)
- Minor typo simulation (optional, off by default)
"""

import random
import re
from typing import Optional

from ..config import get_config, TemplateConfig


# ── Synonym database (extensible) ────────────────────────────

SYNONYMS: dict[str, list[str]] = {
    "好的": ["好嘞", "OK", "收到", "明白", "好"],
    "谢谢": ["感谢", "多谢", "谢啦", "谢谢啦", "thx"],
    "你好": ["嗨", "哈喽", "嘿", "Hi", "在吗"],
    "可以": ["行", "没问题", "OK", "妥", "得"],
    "知道了": ["了解了", "明白", "get", "清楚", "收到"],
    "辛苦了": ["辛苦", "麻烦啦", "受累了", "费心了"],
    "没问题": ["没毛病", "OK的", "稳", "妥妥的"],
    "厉害": ["牛", "强", "666", "牛逼", "太强了"],
    "开心": ["高兴", "快乐", "nice", "美滋滋", "爽"],
    "加油": ["冲", "干就完了", "fighting", "冲冲冲"],
    "方便": ["OK", "没问题", "没问题呀", "可以呀", "行的"],
    "什么时候": ["啥时候", "何时", "几点", "啥时间"],
    "在哪里": ["在哪", "哪儿呢", "位置", "坐标"],
    "多少钱": ["价格", "多少米", "费用", "how much"],
}

TONE_PREFIXES: dict[str, list[str]] = {
    "casual": ["话说", "对了", "那个", "嗯", ""],
    "enthusiastic": ["哇", "太棒了！", "嘿！", "好消息", "天呐"],
    "neutral": ["通知一下", "说明一下", "同步：", "更新：", ""],
}

TONE_SUFFIXES: dict[str, list[str]] = {
    "casual": ["哈", "～", "啦", "哦", "呢"],
    "enthusiastic": ["！！！", "！！", "冲！", "开心！"],
    "neutral": ["。", "。", "。", ""],
}

EMOJIS: dict[str, list[str]] = {
    "casual": ["😄", "👍", "😊", "🤔", "😂", "🙌", "💪", "✨", "😎", "👀"],
    "enthusiastic": ["🎉", "🔥", "💯", "🚀", "⚡", "🥳", "🌟", "💥", "🎯", "🏆"],
    "neutral": ["✅", "📌", "💡", "📎", "ℹ️", "🔍", "📋", "⬆️"],
}


class TemplateEngine:
    """Randomizes message content to appear more human."""

    def __init__(self, cfg: TemplateConfig | None = None):
        self.cfg = cfg or get_config().anti_detect.template
        self._used_messages: set[str] = set()  # deduplication

    @property
    def tone(self) -> str:
        return self.cfg.default_tone

    def randomize(self, text: str, tone: str | None = None) -> str:
        """Apply all randomization layers to a message."""
        tone = tone or self.tone
        result = text

        # 1. Synonym replacement
        result = self._apply_synonyms(result)

        # 2. Tone wrapper (prefix + suffix)
        result = self._apply_tone(result, tone)

        # 3. Emoji insertion
        result = self._apply_emoji(result, tone)

        # Deduplication: if duplicate, add subtle variation
        if result in self._used_messages:
            result = self._add_variation(result, tone)

        self._used_messages.add(result)
        return result

    # ── internal methods ─────────────────────────────────────

    def _apply_synonyms(self, text: str) -> str:
        """Randomly replace known words/phrases with synonyms."""
        for original, alternatives in SYNONYMS.items():
            if original in text and random.random() < self.cfg.synonym_rate:
                replacement = random.choice(alternatives)
                text = text.replace(original, replacement, 1)
        return text

    def _apply_tone(self, text: str, tone: str) -> str:
        """Add tone-appropriate prefix and suffix."""
        prefix = random.choice(TONE_PREFIXES.get(tone, [""]))
        suffix = random.choice(TONE_SUFFIXES.get(tone, [""]))

        if prefix:
            text = prefix + " " + text
        if suffix and not text.endswith(suffix):
            text = text.rstrip("。！？～") + suffix
        return text

    def _apply_emoji(self, text: str, tone: str) -> str:
        """Insert random emoji with configured probability."""
        if random.random() >= self.cfg.emoji_rate:
            return text

        emoji_list = EMOJIS.get(tone, EMOJIS["casual"])
        emoji = random.choice(emoji_list)

        # Insert at end (70%) or after first sentence (30%)
        positions = [m.end() for m in re.finditer(r"[。！？\n]", text)]
        if positions and random.random() < 0.3:
            pos = random.choice(positions)
            return text[:pos] + " " + emoji + text[pos:]
        return text.rstrip() + " " + emoji

    def _add_variation(self, text: str, tone: str) -> str:
        """Add subtle variation to a duplicate message."""
        variations = [
            text + " ",
            " " + text,
            text + random.choice(["~", "～"]),
        ]
        return random.choice(variations)

    # ── batch API ────────────────────────────────────────────

    def randomize_batch(
        self, texts: list[str], tone: str | None = None
    ) -> list[str]:
        """Randomize a batch of messages, ensuring variety across them."""
        tone = tone or self.tone
        results = []
        for text in texts:
            result = self.randomize(text, tone)
            results.append(result)
        return results

    def generate_variants(
        self, text: str, count: int = 3, tone: str | None = None
    ) -> list[str]:
        """Generate multiple distinct randomized variants of the same text."""
        tone = tone or self.tone
        variants = []
        for _ in range(count):
            variant = self.randomize(text, tone)
            variants.append(variant)
        return variants

    def clear_history(self) -> None:
        """Clear message deduplication history."""
        self._used_messages.clear()
