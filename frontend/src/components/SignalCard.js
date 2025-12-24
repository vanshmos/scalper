import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle, CardFooter } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Timer, ArrowUpCircle, ArrowDownCircle, Target, ShieldAlert, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "sonner";

export function SignalCard({ status, signal, formingSince }) {
    const [countdown, setCountdown] = useState(30);

    useEffect(() => {
        if (status === 'FORMING' && formingSince) {
            const interval = setInterval(() => {
                const elapsed = (Date.now() / 1000) - formingSince;
                const remaining = Math.max(0, 30 - elapsed);
                setCountdown(remaining);
            }, 100);
            return () => clearInterval(interval);
        }
    }, [status, formingSince]);

    if (status === 'IDLE') return null;

    if (status === 'FORMING') {
        return (
            <Card className="bg-slate-900 border-blue-500/30 border-2 animate-pulse" data-testid="signal-card-forming">
                <CardHeader>
                    <CardTitle className="flex items-center gap-2 text-blue-400">
                        <Timer className="h-5 w-5" />
                        Signal Forming...
                    </CardTitle>
                </CardHeader>
                <CardContent>
                    <div className="flex flex-col items-center py-6">
                        <div className="text-4xl font-bold font-mono text-white mb-2">{countdown.toFixed(1)}s</div>
                        <p className="text-slate-400 text-sm">Validating Conditions</p>
                    </div>
                    <div className="space-y-2">
                        <div className="flex items-center gap-2 text-sm text-slate-300">
                            <CheckCircle2 className="h-4 w-4 text-emerald-400" /> Structure Aligned
                        </div>
                        <div className="flex items-center gap-2 text-sm text-slate-300">
                            <CheckCircle2 className="h-4 w-4 text-emerald-400" /> Gates Passed
                        </div>
                        <div className="flex items-center gap-2 text-sm text-slate-300">
                            <Timer className="h-4 w-4 text-blue-400" /> Hold Duration > 30s
                        </div>
                    </div>
                </CardContent>
            </Card>
        );
    }

    if (status === 'ACTIVE' && signal) {
        const isLong = signal.direction === 'LONG';
        const accentColor = isLong ? 'emerald' : 'rose';
        const Icon = isLong ? ArrowUpCircle : ArrowDownCircle;

        return (
            <Card className={`bg-slate-900 border-${accentColor}-500 border-2 shadow-lg shadow-${accentColor}-500/10`} data-testid="signal-card-active">
                <CardHeader className={`border-b border-slate-800 pb-4`}>
                    <div className="flex justify-between items-start">
                        <div className="flex items-center gap-3">
                            <Icon className={`h-8 w-8 text-${accentColor}-400`} />
                            <div>
                                <CardTitle className={`text-2xl font-bold text-${accentColor}-400`}>
                                    {signal.direction}
                                </CardTitle>
                                <p className="text-xs text-slate-400 mt-1">ID: {signal.id}</p>
                            </div>
                        </div>
                        <Badge variant="outline" className="text-lg py-1 px-3 border-slate-700 bg-slate-800 text-white">
                            Score: {signal.confidence}/100
                        </Badge>
                    </div>
                </CardHeader>
                
                <CardContent className="pt-6 grid grid-cols-1 md:grid-cols-2 gap-8">
                    {/* Levels */}
                    <div className="space-y-6">
                        <div>
                            <div className="text-xs text-slate-500 uppercase mb-1">Entry Zone</div>
                            <div className="text-2xl font-mono text-white font-bold">
                                {signal.entry_min} - {signal.entry_max}
                            </div>
                        </div>
                        
                        <div className="flex gap-8">
                             <div>
                                <div className="text-xs text-slate-500 uppercase mb-1 flex items-center gap-1">
                                    <ShieldAlert className="h-3 w-3" /> Stop Loss
                                </div>
                                <div className="text-xl font-mono text-rose-400 font-bold">
                                    {signal.stop_loss}
                                </div>
                                <div className="text-xs text-rose-400/70">-{signal.sl_pct}%</div>
                            </div>
                            
                            <div>
                                <div className="text-xs text-slate-500 uppercase mb-1 flex items-center gap-1">
                                    <Target className="h-3 w-3" /> Take Profit 1
                                </div>
                                <div className="text-xl font-mono text-emerald-400 font-bold">
                                    {signal.tp1}
                                </div>
                                <div className="text-xs text-emerald-400/70">+{signal.tp1_pct}%</div>
                            </div>

                             <div>
                                <div className="text-xs text-slate-500 uppercase mb-1 flex items-center gap-1">
                                    <Target className="h-3 w-3" /> Take Profit 2
                                </div>
                                <div className="text-xl font-mono text-emerald-400 font-bold">
                                    {signal.tp2}
                                </div>
                                <div className="text-xs text-emerald-400/70">+{signal.tp2_pct}%</div>
                            </div>
                        </div>
                        
                        <div>
                            <div className="text-xs text-slate-500 uppercase mb-1">Risk : Reward</div>
                            <div className="text-lg font-mono text-white">1 : {signal.rr_ratio}</div>
                        </div>
                    </div>

                    {/* Reasons & Actions */}
                    <div className="flex flex-col justify-between">
                         <div className="space-y-2 mb-6">
                            <h4 className="text-sm font-semibold text-slate-400 uppercase">Analysis</h4>
                            {signal.reasons.map((reason, i) => (
                                <div key={i} className="flex items-center gap-2 text-sm text-slate-300 bg-slate-800/50 p-2 rounded">
                                    <CheckCircle2 className="h-4 w-4 text-blue-400" /> {reason}
                                </div>
                            ))}
                        </div>

                        <div className="flex gap-3">
                            <Button 
                                className="flex-1 bg-emerald-600 hover:bg-emerald-700 text-white"
                                onClick={() => toast.success("Signal Marked as Taken")}
                                data-testid="btn-mark-taken"
                            >
                                Mark as Taken
                            </Button>
                            <Button 
                                variant="outline" 
                                className="flex-1 border-slate-700 text-slate-400 hover:text-white hover:bg-slate-800"
                                onClick={() => toast.success("Signal Dismissed")}
                                data-testid="btn-dismiss"
                            >
                                Dismiss
                            </Button>
                        </div>
                    </div>
                </CardContent>
                <CardFooter className="bg-slate-900/50 border-t border-slate-800 py-2">
                     <div className="w-full flex justify-between text-xs text-slate-500">
                         <span>Invalidation: {signal.stop_loss}</span>
                         <span>Valid for 5 mins</span>
                     </div>
                </CardFooter>
            </Card>
        );
    }

    return null;
}
