import json
import os
import logging
from typing import Dict, Any
from pathlib import Path

logger = logging.getLogger(__name__)

class StatePersistence:
    """
    STATE PERSISTENCE: Prevent data amnesia on restart
    
    Saves critical flow data (trades, OBI/CVD history) to prevent
    loss of market context when engine restarts.
    """
    
    def __init__(self, symbol: str, data_dir: str = "/app/data"):
        self.symbol = symbol
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.state_file = self.data_dir / f"{symbol}_state.json"
    
    def save_state(self, state_data: Dict[str, Any]) -> bool:
        """
        Save engine state to JSON file
        
        Args:
            state_data: Dictionary containing recent_trades, obi_history, cvd_history, etc.
            
        Returns:
            bool: True if save successful
        """
        try:
            with open(self.state_file, 'w') as f:
                json.dump(state_data, f, indent=2)
            logger.debug(f"{self.symbol}: State saved to {self.state_file}")
            return True
        except Exception as e:
            logger.error(f"{self.symbol}: Error saving state: {e}")
            return False
    
    def load_state(self) -> Dict[str, Any]:
        """
        Load engine state from JSON file
        
        Returns:
            Dict: State data or empty dict if file doesn't exist
        """
        try:
            if self.state_file.exists():
                with open(self.state_file, 'r') as f:
                    state_data = json.load(f)
                logger.info(f"{self.symbol}: State loaded from {self.state_file}")
                return state_data
            else:
                logger.info(f"{self.symbol}: No previous state file found")
                return {}
        except Exception as e:
            logger.error(f"{self.symbol}: Error loading state: {e}")
            return {}
