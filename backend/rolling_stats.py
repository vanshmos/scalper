import time
from collections import deque
from typing import Optional
import statistics

class RollingStats:
    """
    Statistical tracker for dynamic thresholding.
    Tracks mean and standard deviation over rolling window.
    """
    
    def __init__(self, window_seconds: int = 3600):
        """
        Args:
            window_seconds: Rolling window size (default 60 minutes)
        """
        self.window_seconds = window_seconds
        self.data = deque()  # [(timestamp, value), ...]
        
    def add(self, value: float):
        """Add new data point with current timestamp"""
        current_time = time.time()
        self.data.append((current_time, value))
        self._cleanup()
    
    def _cleanup(self):
        """Remove data points older than window"""
        current_time = time.time()
        cutoff_time = current_time - self.window_seconds
        
        while self.data and self.data[0][0] < cutoff_time:
            self.data.popleft()
    
    def get_mean(self) -> Optional[float]:
        """Get mean of values in window"""
        if len(self.data) < 10:  # Need minimum 10 samples
            return None
        
        values = [v for _, v in self.data]
        return statistics.mean(values)
    
    def get_stdev(self) -> Optional[float]:
        """Get standard deviation of values in window"""
        if len(self.data) < 10:
            return None
        
        values = [v for _, v in self.data]
        try:
            return statistics.stdev(values)
        except statistics.StatisticsError:
            return None
    
    def get_threshold(self, mode: str = 'lower', std_multiplier: float = 0.5) -> Optional[float]:
        """
        Get dynamic threshold based on statistics
        
        Args:
            mode: 'lower' (mean - std) or 'upper' (mean + std)
            std_multiplier: How many standard deviations
            
        Returns:
            Dynamic threshold or None if insufficient data
        """
        mean = self.get_mean()
        stdev = self.get_stdev()
        
        if mean is None or stdev is None:
            return None
        
        if mode == 'lower':
            return mean - (std_multiplier * stdev)
        elif mode == 'upper':
            return mean + (std_multiplier * stdev)
        else:
            return mean
    
    def count(self) -> int:
        """Get number of data points in window"""
        self._cleanup()
        return len(self.data)
    
    def percentile(self, pct: float) -> Optional[float]:
        """
        Get percentile value from the data
        
        Args:
            pct: Percentile to calculate (0-100)
            
        Returns:
            Percentile value or None if insufficient data
        """
        if len(self.data) < 10:
            return None
        
        values = sorted([v for _, v in self.data])
        index = int((pct / 100) * len(values))
        index = max(0, min(index, len(values) - 1))
        return values[index]
