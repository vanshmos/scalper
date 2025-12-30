import logging
import os
import requests
from typing import Optional

logger = logging.getLogger(__name__)

class AlertManager:
    def __init__(self):
        # Telegram configuration (optional)
        self.telegram_bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
        self.telegram_chat_id = os.environ.get('TELEGRAM_CHAT_ID')
        self.telegram_enabled = bool(self.telegram_bot_token and self.telegram_chat_id)
        
        if self.telegram_enabled:
            logger.info("Telegram alerts enabled")
        else:
            logger.info("Telegram alerts disabled (credentials not configured)")
    
    def send_signal_alert(
        self,
        direction: str,
        confidence: int,
        entry: float,
        stop_loss: float,
        tp1: float,
        tp2: float
    ):
        """Send alert when signal goes ACTIVE"""
        
        # Calculate R:R ratio
        risk = abs(entry - stop_loss)
        reward = abs(entry - tp2)
        rr_ratio = reward / risk if risk > 0 else 0
        
        # Prepare message
        emoji = "🔴" if direction == "SHORT" else "🟢"
        message = f"""{emoji} {direction} BTC
Confidence: {confidence}/100
Entry: ${entry:,.2f}
SL: ${stop_loss:,.2f}
TP1: ${tp1:,.2f}
TP2: ${tp2:,.2f}
R:R: {rr_ratio:.1f}"""
        
        logger.info(f"Signal alert: {direction} at ${entry:,.2f}")
        
        # Send Telegram alert if enabled
        if self.telegram_enabled:
            self._send_telegram_message(message)
    
    def _send_telegram_message(self, message: str):
        """Send message via Telegram Bot API"""
        try:
            url = f"https://api.telegram.org/bot{self.telegram_bot_token}/sendMessage"
            payload = {
                "chat_id": self.telegram_chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info("Telegram alert sent successfully")
            else:
                logger.warning(f"Telegram alert failed: {response.status_code} - {response.text}")
                
        except Exception as e:
            logger.error(f"Error sending Telegram alert: {e}")
