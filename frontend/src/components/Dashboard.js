import React, { useEffect, useState } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { SignalCard } from "./SignalCard";
import { Activity, Zap, Shield, BarChart2, TrendingUp, TrendingDown, RefreshCcw, AlertTriangle, DollarSign, XCircle } from "lucide-react";

const WS_URL = process.env.REACT_APP_BACKEND_URL.replace('http', 'ws') + '/api/ws';

export default function Dashboard() {
    const [data, setData] = useState(null);
    const [connected, setConnected] = useState(false);

    useEffect(() => {
        let ws;
        const connect = () => {
            ws = new WebSocket(WS_URL);
            ws.onopen = () => setConnected(true);
            ws.onclose = () => {
                setConnected(false);
                setTimeout(connect, 3000);
            };
            ws.onmessage = (event) => {
                const msg = JSON.parse(event.data);
                setData(msg);
            };
        };
        connect();
        return () => ws?.close();
    }, []);

    if (!data) return (
        <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-200" data-testid="loading-screen">
            <div className="text-center">
                <RefreshCcw className="animate-spin h-8 w-8 mx-auto mb-4 text-slate-500" />
                <p>Connecting to Engine...</p>
            </div>
        </div>
    );

    const { price, regime, trends, gates_passed, indicators, signal_status, current_signal, warmup_progress, is_warmed_up, backfill_error, backfill_failed_final } = data;

    return (
        <div className="min-h-screen bg-slate-950 text-slate-200 p-4 md:p-6 font-mono">
            {/* Header / Status Bar */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <Card className="bg-slate-900 border-slate-800">
                    <CardContent className="pt-6">
                        <div className="text-sm text-slate-500 uppercase tracking-wider mb-1">BTC/USDT Price</div>
                        <div className="text-3xl font-bold text-white tracking-tight" data-testid="price-display">
                            ${price?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </div>
                    </CardContent>
                </Card>

                <Card className="bg-slate-900 border-slate-800">
                    <CardContent className="pt-6">
                        <div className="text-sm text-slate-500 uppercase tracking-wider mb-1">Market Regime</div>
                        <div className="flex items-center gap-2">
                            <Badge variant="outline" className={`
                                ${regime?.includes('TRENDING') ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : 
                                  regime === 'CHAOTIC' ? 'bg-rose-500/10 text-rose-400 border-rose-500/20' : 
                                  'bg-amber-500/10 text-amber-400 border-amber-500/20'}
                            `} data-testid="regime-badge">
                                {regime}
                            </Badge>
                            {gates_passed ? 
                                <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20" data-testid="gates-pass">GATES PASS</Badge> : 
                                <Badge className="bg-rose-500/10 text-rose-400 border-rose-500/20" data-testid="gates-fail">GATES FAIL</Badge>
                            }
                        </div>
                    </CardContent>
                </Card>

                <Card className="bg-slate-900 border-slate-800 md:col-span-2">
                    <CardContent className="pt-6">
                         <div className="flex justify-between items-center mb-2">
                            <div className="text-sm text-slate-500 uppercase tracking-wider">System Status</div>
                            <div className="text-xs text-slate-600">{connected ? 'WS CONNECTED' : 'WS DISCONNECTED'}</div>
                         </div>
                         {!is_warmed_up && !backfill_failed_final ? (
                             <div className="space-y-2">
                                 <div className="flex justify-between text-xs text-slate-400">
                                     <span>Warmup Progress {backfill_error && "(Retrying...)"}</span>
                                     <span>{warmup_progress}%</span>
                                 </div>
                                 <Progress value={warmup_progress} className="h-2 bg-slate-800" indicatorClassName={backfill_error ? "bg-amber-500" : "bg-blue-500"} data-testid="warmup-progress" />
                                 {backfill_error && <div className="flex items-center gap-1 text-xs text-amber-500"><AlertTriangle className="h-3 w-3" /> Backfill Failed - Retrying</div>}
                             </div>
                         ) : backfill_failed_final ? (
                             <div className="flex flex-col gap-2">
                                 <div className="flex items-center gap-2 text-rose-400 text-sm font-bold">
                                     <XCircle className="h-4 w-4" /> Backfill Failed - Data Unavailable
                                 </div>
                                 <p className="text-xs text-slate-400">
                                     Unable to fetch historical data (API Error). Engine is running in real-time only mode. Indicators like ATR will normalize as new candles form.
                                 </p>
                             </div>
                         ) : (
                             <div className="flex items-center gap-4 text-emerald-400 text-sm" data-testid="system-ready">
                                 <Zap className="h-4 w-4" /> System Ready & Scanning
                             </div>
                         )}
                    </CardContent>
                </Card>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Left Column: Indicators */}
                <div className="lg:col-span-1 space-y-4">
                     <Card className="bg-slate-900 border-slate-800">
                         <CardHeader><CardTitle className="text-lg flex items-center gap-2"><BarChart2 className="h-4 w-4" /> Structure</CardTitle></CardHeader>
                         <CardContent className="space-y-4">
                            <div className="grid grid-cols-3 gap-2 text-center">
                                <TrendBox label="1m" trend={trends?.['1m']} />
                                <TrendBox label="5m" trend={trends?.['5m']} />
                                <TrendBox label="15m" trend={trends?.['15m']} />
                            </div>
                         </CardContent>
                     </Card>

                    <Card className="bg-slate-900 border-slate-800">
                        <CardHeader><CardTitle className="text-lg flex items-center gap-2"><Activity className="h-4 w-4" /> Indicators</CardTitle></CardHeader>
                        <CardContent className="space-y-4">
                            <IndicatorRow label="Funding Rate" value={indicators?.funding_rate} format="0.000%" threshold={0.01} isPercentage={true} suffix="%" />
                            <div className="flex justify-between items-center py-2 border-b border-slate-800">
                                <span className="text-slate-400">Open Interest</span>
                                <div className="text-right">
                                    <div className="font-mono text-slate-200">
                                        {indicators?.open_interest ? `$${(indicators?.open_interest / 1000000).toFixed(2)}M` : '-'}
                                    </div>
                                    <div className={`text-xs ${indicators?.oi_change_5m > 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                                        {indicators?.oi_change_5m ? `${indicators?.oi_change_5m > 0 ? '+' : ''}${indicators?.oi_change_5m?.toFixed(2)}% (5m)` : '-'}
                                    </div>
                                </div>
                            </div>
                            
                            <IndicatorRow label="OBI (Order Book Imbalance)" value={indicators?.obi} format="0.00" threshold={0.12} />
                            <IndicatorRow label="CVD 1m" value={indicators?.cvd_1m} format="0.00" threshold={0.0} />
                            <IndicatorRow label="CVD 5m" value={indicators?.cvd_5m} format="0.00" threshold={0.15} />
                            
                            <div className="flex justify-between items-center py-2 border-b border-slate-800">
                                <span className="text-slate-400">ATR (Volatility)</span>
                                <span className="font-mono text-slate-200">{indicators?.atr?.toFixed(2) ?? '-'}</span>
                            </div>
                            <div className="flex justify-between items-center py-2 border-b border-slate-800">
                                <span className="text-slate-400">Spread (bps)</span>
                                <span className={`font-mono ${indicators?.spread > 1.5 ? 'text-rose-400' : 'text-emerald-400'}`}>
                                    {indicators?.spread?.toFixed(2) ?? '-'}
                                </span>
                            </div>
                            <div className="flex justify-between items-center py-2">
                                <span className="text-slate-400">Depth ($)</span>
                                <span className={`font-mono ${indicators?.depth < 250000 ? 'text-rose-400' : 'text-emerald-400'}`}>
                                    {indicators?.depth ? `$${(indicators?.depth / 1000).toFixed(0)}k` : '-'}
                                </span>
                            </div>
                        </CardContent>
                    </Card>
                </div>

                {/* Center/Right: Signal Area */}
                <div className="lg:col-span-2">
                    <SignalCard 
                        status={signal_status} 
                        signal={current_signal} 
                        formingSince={data.forming_since}
                    />
                </div>
            </div>
        </div>
    );
}

const TrendBox = ({ label, trend }) => {
    const isBull = trend === 'BULL';
    const isBear = trend === 'BEAR';
    const bg = isBull ? 'bg-emerald-500/10 border-emerald-500/20' : isBear ? 'bg-rose-500/10 border-rose-500/20' : 'bg-slate-800 border-slate-700';
    const text = isBull ? 'text-emerald-400' : isBear ? 'text-rose-400' : 'text-slate-400';
    const Icon = isBull ? TrendingUp : isBear ? TrendingDown : Activity;

    return (
        <div className={`border rounded p-2 flex flex-col items-center ${bg}`}>
            <span className="text-xs text-slate-500 uppercase mb-1">{label}</span>
            <Icon className={`h-4 w-4 mb-1 ${text}`} />
            <span className={`text-xs font-bold ${text}`}>{trend}</span>
        </div>
    )
}

const IndicatorRow = ({ label, value, format, threshold, isPercentage, suffix = "" }) => {
    let color = 'text-slate-400';
    const displayValue = value === null || value === undefined ? '-' : value.toFixed(label === "Funding Rate" ? 4 : 2);
    
    if (value !== null && value !== undefined) {
        if (label === "Funding Rate") {
            if (value > 0.03 || value < -0.02) color = 'text-rose-400';
            else if ((value > 0.01 && value <= 0.03) || (value >= -0.02 && value < -0.01)) color = 'text-amber-400';
            else if (value >= -0.01 && value <= 0.01) color = 'text-emerald-400';
        } else {
            const isBull = value > threshold;
            const isBear = value < -threshold;
            color = isBull ? 'text-emerald-400' : isBear ? 'text-rose-400' : 'text-slate-400';
        }
    }
    
    return (
        <div className="flex justify-between items-center py-2 border-b border-slate-800 last:border-0">
            <span className="text-slate-400">{label}</span>
            <span className={`font-mono font-bold ${color}`} data-testid={`indicator-${label.split(' ')[0]}`}>
                {displayValue}{value !== null && value !== undefined ? suffix : ''}
            </span>
        </div>
    );
};
