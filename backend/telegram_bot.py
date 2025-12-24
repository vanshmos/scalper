import os
import asyncio
import logging
from telegram import Bot
from telegram.error import TelegramError

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.bot = None
        if self.token and self.chat_id:
            try:
                self.bot = Bot(token=self.token)
                logger.info("Telegram bot initialized")
            except Exception as e:
                logger.error(f"Failed to initialize Telegram bot: {e}")

    async def send_signal(self, signal_data: dict):
        if not self.bot or not self.chat_id:
            return

        direction_emoji = "🟢" if signal_data['direction'] == 'LONG' else "🔴"
        
        message = (
            f"{direction_emoji} *NEW SIGNAL: {signal_data['direction']}*\n\n"
            f"🎯 *Entry*: {signal_data['entry_min']} - {signal_data['entry_max']}\n"
            f"🛑 *Stop Loss*: {signal_data['stop_loss']} ({signal_data['sl_pct']}%)\n"
            f"💰 *TP1*: {signal_data['tp1']} ({signal_data['tp1_pct']}%)\n"
            f"💰 *TP2*: {signal_data['tp2']} ({signal_data['tp2_pct']}%)\n"
            f"⚖️ *R:R*: {signal_data['rr_ratio']}\n"
            f"🧠 *Confidence*: {signal_data['confidence']}/100\n\n"
            f"📝 *Reasons*:\n" + "\n".join([f"- {r}" for r in signal_data['reasons']])
        )

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=message,
                parse_mode='Markdown'
            )
            logger.info("Telegram signal sent successfully")
        except TelegramError as e:
            logger.error(f"Failed to send Telegram message: {e}")
