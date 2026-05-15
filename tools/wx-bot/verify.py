"""Quick import validation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

from wx_bot.config import get_config
from wx_bot.anti_detect import MouseSimulator, WindowManager, DelayManager, SleepScheduler, TemplateEngine
from wx_bot.actions import MomentsPoster, MessageSender
from wx_bot.orchestrator import Orchestrator, DecisionEngine, WxCliClient

print("All imports OK")

cfg = get_config()
print(f"Config loaded: {cfg.safety.max_daily_messages} msgs/day, sleep={'ON' if cfg.anti_detect.sleep.enabled else 'OFF'}")
print(f"Mouse: Bezier {cfg.anti_detect.mouse.bezier_waypoints} waypoints, speed {cfg.anti_detect.mouse.speed_min}-{cfg.anti_detect.mouse.speed_max}")
print(f"Template: synonym={cfg.anti_detect.template.synonym_rate}, emoji={cfg.anti_detect.template.emoji_rate}")
print(f"Moments: max {cfg.safety.max_daily_moments}/day, cooldown {cfg.safety.min_interval_between_moments_minutes}min")
print("\nAll modules verified.")
