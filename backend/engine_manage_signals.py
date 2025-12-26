    async def manage_signals(self):
        now = time.time()
        
        if self.signal_state.status == "ACTIVE":
            if now > self.signal_state.active_until:
                self.signal_state.status = "IDLE"
                self.signal_state.cooldown_until = now + 600
                self.signal_state.current_signal = None
            return 

        if now < self.signal_state.cooldown_until:
            return

        # Core Conditions Check (Regime, Structure, CVD, OBI, EMA)
        checklist = self.state.checklist
        core_pass = (
            "TRENDING" in self.state.regime and
            checklist['structure']['pass'] and
            checklist['cvd']['pass'] and 
            checklist['obi']['pass'] and 
            checklist['ema_dist']['pass']
        )

        is_long = self.state.regime == "TRENDING_BULL"

        # Signal State Machine
        if self.signal_state.status == "IDLE":
            # Start Forming ONLY if Core + Gates pass
            if core_pass and self.state.gates_passed:
                self.signal_state.status = "FORMING"
                self.signal_state.forming_since = now
                logger.info("Signal FORMING...")
        
        elif self.signal_state.status == "FORMING":
            # If Core fails, reset immediately
            if not core_pass:
                self.reset_forming()
                return
            
            # If Gates fail, DO NOT RESET. Keep forming.
            
            # Check duration
            if now - self.signal_state.forming_since >= 30:
                # Activation Logic
                score = 30 # Structure
                score += 25 # CVD (implied pass)
                score += 20 # EMA (implied pass)
                score += 20 # OBI (implied pass)
                score += 5 # Base/Funding placeholder

                funding = self.state.indicators.get('funding_rate')
                reasons = ["Structure Aligned", "CVD Strength", "OBI Support"]
                
                if funding:
                    if is_long:
                        if funding < 0:
                            score += 5
                            reasons.append(f"Funding Supportive ({funding:.3f}%)")
                        if funding > 0.03:
                            score -= 5
                            reasons.append(f"Caution: Extreme Long Funding ({funding:.3f}%)")
                    else: 
                        if funding > 0:
                            score += 5
                            reasons.append(f"Funding Supportive ({funding:.3f}%)")
                        if funding < -0.02:
                            score -= 5
                            reasons.append(f"Caution: Extreme Short Funding ({funding:.3f}%)")
                
                rsi = self.state.indicators.get('rsi')
                if rsi:
                    if is_long and rsi > 75:
                        score -= 15
                        reasons.append(f"RSI Overbought ({rsi:.1f})")
                    if not is_long and rsi < 25:
                        score -= 15
                        reasons.append(f"RSI Oversold ({rsi:.1f})")

                # Gate Warning
                if not self.state.gates_passed:
                    reasons.append("Warning: Gates Failed at Activation")

                if score > 70:
                    await self.activate_signal(is_long, score, reasons)
                else:
                    self.reset_forming()
