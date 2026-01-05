import logging
import time
from typing import Optional, Dict
from enum import Enum
from signal_detector import SignalDirection

logger = logging.getLogger(__name__)

class SignalState(str, Enum):
    IDLE = "IDLE"
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"

class SignalStateMachine:
    def __init__(self):
        self.state = SignalState.IDLE
        self.direction: Optional[SignalDirection] = None
        self.forming_start_time: Optional[float] = None
        self.active_start_time: Optional[float] = None
        self.last_cancel_time: Optional[float] = None
        
        # Locked levels (set when ACTIVE)
        self.entry_price: Optional[float] = None
        self.stop_loss: Optional[float] = None
        self.tp1: Optional[float] = None
        self.tp2: Optional[float] = None
        self.confidence: Optional[int] = None
        
        # Cooldowns (direction -> cooldown_end_time)
        self.cooldowns: Dict[str, float] = {}
        
        # V1.5 Configuration
        self.forming_duration = 12  # Reduced from 20 to 12 seconds
        self.active_duration = 300  # 5 minutes
        self.signal_cooldown = 300  # 5 minutes after signal fires
        self.cancel_cooldown = 120  # 2 minutes after signal cancels
        
    def is_in_cooldown(self, direction: SignalDirection) -> bool:
        """Check if direction is in cooldown"""
        if direction.value not in self.cooldowns:
            return False
        
        return time.time() < self.cooldowns[direction.value]
    
    def start_cooldown(self, direction: SignalDirection, is_cancel: bool = False):
        """Start cooldown for direction"""
        cooldown_duration = self.cancel_cooldown if is_cancel else self.signal_cooldown
        self.cooldowns[direction.value] = time.time() + cooldown_duration
        logger.info(f"Started {cooldown_duration}s cooldown for {direction.value} ({'cancel' if is_cancel else 'signal'})")
    
    def check_core_conditions(
        self,
        signal_ready: bool,
        hard_gates_pass: bool
    ) -> bool:
        """Check if core conditions (score + hard gates) are passing"""
        return signal_ready and hard_gates_pass
    
    def calculate_levels(
        self,
        current_price: float,
        atr: float,
        direction: SignalDirection
    ) -> Dict:
        """Calculate entry, SL, and TP levels"""
        try:
            # Entry: Current price with 0.05% zone
            entry = current_price
            
            # Stop loss: 1.5 x ATR from entry
            if direction == SignalDirection.SHORT:
                stop_loss = entry + (1.5 * atr)
            else:  # LONG
                stop_loss = entry - (1.5 * atr)
            
            # TP1: 2 x ATR from entry
            if direction == SignalDirection.SHORT:
                tp1 = entry - (2 * atr)
            else:  # LONG
                tp1 = entry + (2 * atr)
            
            # TP2: 3.5 x ATR from entry
            if direction == SignalDirection.SHORT:
                tp2 = entry - (3.5 * atr)
            else:  # LONG
                tp2 = entry + (3.5 * atr)
            
            # Calculate R:R ratio
            risk = abs(entry - stop_loss)
            reward = abs(entry - tp2)
            rr_ratio = reward / risk if risk > 0 else 0
            
            return {
                'entry': entry,
                'stop_loss': stop_loss,
                'tp1': tp1,
                'tp2': tp2,
                'rr_ratio': rr_ratio
            }
        except Exception as e:
            logger.error(f"Error calculating levels: {e}")
            return None
    
    def update(
        self,
        signals: Dict,
        current_price: Optional[float],
        atr: Optional[float]
    ) -> Dict:
        """Update state machine and return current signal info"""
        
        current_time = time.time()
        signal_triggered = False
        
        # Determine which direction has signal ready
        short_ready = signals.get('short', {}).get('signal_ready', False)
        long_ready = signals.get('long', {}).get('signal_ready', False)
        
        short_hard_gates = signals.get('short', {}).get('hard_gates', {}).get('all_pass', False)
        long_hard_gates = signals.get('long', {}).get('hard_gates', {}).get('all_pass', False)
        
        short_score = signals.get('short', {}).get('score', 0)
        long_score = signals.get('long', {}).get('score', 0)
        
        # Check cooldowns
        short_in_cooldown = self.is_in_cooldown(SignalDirection.SHORT)
        long_in_cooldown = self.is_in_cooldown(SignalDirection.LONG)
        
        # Apply cooldown filter
        if short_in_cooldown:
            short_ready = False
        if long_in_cooldown:
            long_ready = False
        
        # State machine logic
        if self.state == SignalState.IDLE:
            # Check if any signal is ready to form
            if short_ready and not long_ready:
                self.state = SignalState.FORMING
                self.direction = SignalDirection.SHORT
                self.forming_start_time = current_time
                self.confidence = short_score
                logger.info(f"Signal entering FORMING state: SHORT (score: {short_score})")
            elif long_ready and not short_ready:
                self.state = SignalState.FORMING
                self.direction = SignalDirection.LONG
                self.forming_start_time = current_time
                self.confidence = long_score
                logger.info(f"Signal entering FORMING state: LONG (score: {long_score})")
            elif short_ready and long_ready:
                # Both ready: choose higher score
                if short_score > long_score:
                    self.state = SignalState.FORMING
                    self.direction = SignalDirection.SHORT
                    self.forming_start_time = current_time
                    self.confidence = short_score
                    logger.info(f"Signal entering FORMING state: SHORT (score: {short_score}, higher than LONG {long_score})")
                else:
                    self.state = SignalState.FORMING
                    self.direction = SignalDirection.LONG
                    self.forming_start_time = current_time
                    self.confidence = long_score
                    logger.info(f"Signal entering FORMING state: LONG (score: {long_score}, higher than SHORT {short_score})")
        
        elif self.state == SignalState.FORMING:
            # Check if core conditions still pass
            if self.direction == SignalDirection.SHORT:
                core_pass = self.check_core_conditions(short_ready, short_hard_gates)
            else:
                core_pass = self.check_core_conditions(long_ready, long_hard_gates)
            
            if not core_pass:
                # Core conditions failed - reset to IDLE with cancel cooldown
                logger.info(f"Signal FORMING cancelled: conditions failed for {self.direction.value}")
                self.start_cooldown(self.direction, is_cancel=True)
                self.last_cancel_time = current_time
                self.state = SignalState.IDLE
                self.direction = None
                self.forming_start_time = None
                self.confidence = None
            else:
                # Check if 12 seconds have passed
                elapsed = current_time - self.forming_start_time
                if elapsed >= self.forming_duration:
                    # Transition to ACTIVE
                    if current_price and atr:
                        levels = self.calculate_levels(current_price, atr, self.direction)
                        if levels:
                            self.entry_price = levels['entry']
                            self.stop_loss = levels['stop_loss']
                            self.tp1 = levels['tp1']
                            self.tp2 = levels['tp2']
                            
                            self.state = SignalState.ACTIVE
                            self.active_start_time = current_time
                            signal_triggered = True
                            
                            logger.info(f"Signal ACTIVE: {self.direction.value} at ${self.entry_price:.2f}")
                        else:
                            logger.error("Failed to calculate levels, returning to IDLE")
                            self.state = SignalState.IDLE
                            self.direction = None
                            self.forming_start_time = None
                    else:
                        logger.error("Missing price or ATR data, returning to IDLE")
                        self.state = SignalState.IDLE
                        self.direction = None
                        self.forming_start_time = None
        
        elif self.state == SignalState.ACTIVE:
            # Check if 5 minutes have passed
            elapsed = current_time - self.active_start_time
            if elapsed >= self.active_duration:
                # Transition to EXPIRED
                logger.info(f"Signal EXPIRED: {self.direction.value}")
                self.state = SignalState.EXPIRED
                self.start_cooldown(self.direction)
                
                # Reset after showing EXPIRED briefly
                self.state = SignalState.IDLE
                self.direction = None
                self.entry_price = None
                self.stop_loss = None
                self.tp1 = None
                self.tp2 = None
                self.confidence = None
                self.active_start_time = None
        
        # Build status response
        status = {
            'state': self.state,
            'direction': self.direction.value if self.direction else None,
            'signal_triggered': signal_triggered,
            'cooldowns': {
                'short': max(0, self.cooldowns.get('SHORT', 0) - current_time) if 'SHORT' in self.cooldowns else 0,
                'long': max(0, self.cooldowns.get('LONG', 0) - current_time) if 'LONG' in self.cooldowns else 0
            }
        }
        
        if self.state == SignalState.FORMING:
            elapsed = current_time - self.forming_start_time
            status['forming_elapsed'] = elapsed
            status['forming_remaining'] = max(0, self.forming_duration - elapsed)
        
        if self.state == SignalState.ACTIVE:
            elapsed = current_time - self.active_start_time
            status['active_elapsed'] = elapsed
            status['active_remaining'] = max(0, self.active_duration - elapsed)
            status['entry'] = self.entry_price
            status['stop_loss'] = self.stop_loss
            status['tp1'] = self.tp1
            status['tp2'] = self.tp2
            status['confidence'] = self.confidence
        
        return status
