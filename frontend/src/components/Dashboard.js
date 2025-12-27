import React, { useEffect, useState, useRef } from 'react';
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { SignalCard } from "./SignalCard";
import { Activity, Zap, Shield, BarChart2, TrendingUp, TrendingDown, RefreshCcw, AlertTriangle, DollarSign, XCircle, ChevronDown, ChevronUp, Terminal, Info, CheckCircle2, Circle, Volume2, VolumeX, Radio } from "lucide-react";
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from "@/components/ui/collapsible";

// Dynamic URL logic - detect backend location
const isLocalDev = window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1';
const backendPort = '8001';

let WS_URL, API_URL;

if (isLocalDev) {
    WS_URL = `ws://localhost:${backendPort}/api/ws`;
    API_URL = `http://localhost:${backendPort}/api/state`;
} else {
    const currentUrl = new URL(window.location.href);
    const backendHost = currentUrl.hostname.replace(/--3000--/, `--${backendPort}--`);
    const protocol = currentUrl.protocol === 'https:' ? 'wss:' : 'ws:';
    const httpProtocol = currentUrl.protocol;
    WS_URL = `${protocol}//${backendHost}/api/ws`;
    API_URL = `${httpProtocol}//${backendHost}/api/state`;
}

console.log('🔌 WS URL:', WS_URL);
console.log('📡 API URL:', API_URL);

export default function Dashboard() {
    const [data, setData] = useState(null);
    const [connected, setConnected] = useState(false);
    const [usingPolling, setUsingPolling] = useState(false);
    const [isDebugOpen, setIsDebugOpen] = useState(false);
    const [testSignal, setTestSignal] = useState(null);
    const [soundEnabled, setSoundEnabled] = useState(true);
    
    const prevSignalStatus = useRef("IDLE");
    const formingSound = useRef(new Audio('https://assets.mixkit.co/active_storage/sfx/2869/2869-preview.mp3'));
    const activeSound = useRef(new Audio('https://assets.mixkit.co/active_storage/sfx/2865/2865-preview.mp3'));

    // WebSocket Logic
    useEffect(() => {
        let ws;
        let pollInterval;

        const startPolling = () => {
            if (pollInterval) return;
            console.log("⚠️ Switching to HTTP Polling");
            setUsingPolling(true);
            
            const fetchState = async () => {
                try {
                    const res = await fetch(API_URL);
                    if (res.ok) {
                        const json = await res.json();
                        setData(json);
                    }
                } catch (e) {
                    console.error("Poll Error", e);
                }
            };
            fetchState(); // Initial fetch
            pollInterval = setInterval(fetchState, 1000);
        };

        const connectWS = () => {
            console.log("Connecting to WS:", WS_URL);
            ws = new WebSocket(WS_URL);
            
            ws.onopen = () => {
                console.log("WS Connected");
                setConnected(true);
                setUsingPolling(false);
                if (pollInterval) {
                    clearInterval(pollInterval);
                    pollInterval = null;
                }
            };
            
            ws.onclose = (e) => {
                console.log("WS Closed", e.code);
                setConnected(false);
                // Fallback to polling immediately on close
                startPolling();
                // Retry WS every 5s
                setTimeout(connectWS, 5000);
            };
            
            ws.onmessage = (event) => {
                try {
                    const msg = JSON.parse(event.data);
                    setData(msg);
                } catch (e) {
                    console.error("WS Parse Error", e);
                }
            };
            
            ws.onerror = (e) => {
                console.error("WS Error", e);
                // Don't rely on onerror, onclose will trigger
            };
        };

        connectWS();

        return () => {
            if (ws) ws.close();
            if (pollInterval) clearInterval(pollInterval);
        };
    }, []);

    // Sound Logic
    useEffect(() => {
        if (!data || !soundEnabled) return;
        const currentStatus = data.signal_status;
        const prevStatus = prevSignalStatus.current;
        if (currentStatus !== prevStatus) {
            if (currentStatus === "FORMING") formingSound.current.play().catch(e => console.log(e));
            else if (currentStatus === "ACTIVE") activeSound.current.play().catch(e => console.log(e));
        }
        prevSignalStatus.current = currentStatus;
    }, [data, soundEnabled]);

    const toggleTestSignal = () => {
        if (testSignal) setTestSignal(null);
        else setTestSignal({
            id: "TEST-123", direction: "LONG", entry_min: 88500.50, entry_max: 88550.00, stop_loss: 88200.00,
            tp1: 88900.00, tp2: 89500.00, sl_pct: 0.35, tp1_pct: 0.45, tp2_pct: 1.15, rr_ratio: 1.5,
            confidence: 85, reasons: ["Test Signal", "Structure Aligned"], timestamp: Date.now() / 1000
        });
    };

    if (!data) return (
        <div className="flex h-screen items-center justify-center bg-slate-950 text-slate-200" data-testid="loading-screen">
            <div className="text-center">
                <RefreshCcw className="animate-spin h-8 w-8 mx-auto mb-4 text-slate-500" />
                <p>Connecting to Engine...</p>
                <div className="text-xs text-slate-600 mt-2 space-y-1">
                    <p>WS: {WS_URL}</p>
                    <p>API: {API_URL}</p>
                </div>
            </div>
        </div>
    );

    const { price, regime, trends, gates_passed, indicators, checklist, signal_status, current_signal, warmup_progress, is_warmed_up, backfill_error, backfill_failed_final, debug } = data;
    const displaySignal = testSignal || current_signal;
    const displayStatus = testSignal ? "ACTIVE" : signal_status;

    return (
        <div className="min-h-screen bg-slate-950 text-slate-200 p-4 md:p-6 font-mono pb-32">
            {/* Header */}
            <div className="grid grid-cols-1 md:grid-cols-4 gap-4 mb-6">
                <Card className="bg-slate-900 border-slate-800">
                    <CardContent className="pt-6">
                        <div className="flex justify-between items-start">
                            <div className="text-sm text-slate-500 uppercase tracking-wider mb-1">BTC/USDT Price</div>
                            {usingPolling && <Badge variant="secondary" className="text-[10px] bg-amber-500/10 text-amber-400">POLLING</Badge>}
                        </div>
                        <div className="text-3xl font-bold text-white tracking-tight" data-testid="price-display">
                            ${price?.toLocaleString(undefined, { minimumFractionDigits: 2 })}
                        </div>
                    </CardContent>
                </Card>

                <Card className="bg-slate-900 border-slate-800">
                    <CardContent className="pt-6">
                        <div className="text-sm text-slate-500 uppercase tracking-wider mb-1">Market Regime</div>
                        <div className="flex items-center gap-2">
                            <Badge variant="outline" className={`${regime?.includes('TRENDING') ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20' : regime === 'CHAOTIC' ? 'bg-rose-500/10 text-rose-400 border-rose-500/20' : 'bg-amber-500/10 text-amber-400 border-amber-500/20'}`}>
                                {regime}
                            </Badge>
                            {gates_passed ? <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">GATES PASS</Badge> : <Badge className="bg-rose-500/10 text-rose-400 border-rose-500/20">GATES FAIL</Badge>}
                        </div>
                    </CardContent>
                </Card>

                <Card className="bg-slate-900 border-slate-800 md:col-span-2">
                    <CardContent className="pt-6">
                         <div className="flex justify-between items-center mb-2">
                            <div className="text-sm text-slate-500 uppercase tracking-wider">System Status</div>
                            <div className="flex items-center gap-4">
                                <div className="text-xs text-slate-600 flex items-center gap-2">
                                    {connected ? <span className="text-emerald-400 flex items-center gap-1"><Radio className="h-3 w-3" /> LIVE WS</span> : <span className="text-amber-400 flex items-center gap-1"><RefreshCcw className="h-3 w-3 animate-spin" /> POLLING</span>}
                                </div>
                                <Button variant="ghost" size="icon" className="h-6 w-6 text-slate-400 hover:text-white" onClick={() => setSoundEnabled(!soundEnabled)}>
                                    {soundEnabled ? <Volume2 className="h-4 w-4" /> : <VolumeX className="h-4 w-4" />}
                                </Button>
                            </div>
                         </div>
                         {!is_warmed_up ? (
                             <div className="space-y-2">
                                 <div className="flex justify-between text-xs text-slate-400">
                                     <span>Building History (Live Mode)</span>
                                     <span>{warmup_progress}% ({debug?.candle_count_1m}/50 candles)</span>
                                 </div>
                                 <Progress value={warmup_progress} className="h-2 bg-slate-800" indicatorClassName="bg-blue-500" />
                             </div>
                         ) : (
                             <div className="flex items-center gap-4 text-emerald-400 text-sm">
                                 <Zap className="h-4 w-4" /> System Ready & Scanning
                             </div>
                         )}
                    </CardContent>
                </Card>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="lg:col-span-1 space-y-4">
                     <Card className="bg-slate-900 border-slate-800">
                         <CardHeader><CardTitle className="text-lg flex items-center gap-2"><BarChart2 className="h-4 w-4" /> Signal Checklist</CardTitle></CardHeader>
                         <CardContent className="space-y-2">
                            {checklist ? (
                                <>
                                <CheckItem label="Regime" passed={checklist.regime?.pass} value={checklist.regime?.value} />
                                <CheckItem label="Structure" passed={checklist.structure?.pass} value={checklist.structure?.value} />
                                <CheckItem label="CVD 5m" passed={checklist.cvd?.pass} value={checklist.cvd?.value} />
                                <CheckItem label="OBI" passed={checklist.obi?.pass} value={checklist.obi?.value} />
                                <CheckItem label="Price EMA20" passed={checklist.ema_dist?.pass} value={checklist.ema_dist?.value} />
                                <CheckItem label="Gates" passed={checklist.gates?.pass} value={checklist.gates?.value} />
                                </>
                            ) : <div className="text-sm text-slate-500">Waiting for data...</div>}
                         </CardContent>
                     </Card>

                    <Card className="bg-slate-900 border-slate-800">
                        <CardHeader><CardTitle className="text-lg flex items-center gap-2"><Activity className="h-4 w-4" /> Indicators</CardTitle></CardHeader>
                        <CardContent className="space-y-4">
                            <IndicatorRow label="RSI (14)" value={indicators?.rsi} format="0.00" threshold={50} isRSI={true} />
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
                            <IndicatorRow label="OBI" value={indicators?.obi} format="0.00" threshold={0.12} />
                            <IndicatorRow label="CVD 1m" value={indicators?.cvd_1m} format="0.00" threshold={0.0} />
                            <IndicatorRow label="CVD 5m" value={indicators?.cvd_5m} format="0.00" threshold={0.15} />
                            <div className="flex justify-between items-center py-2 border-b border-slate-800">
                                <span className="text-slate-400">ATR</span>
                                <span className="font-mono text-slate-200">{indicators?.atr?.toFixed(2) ?? '-'}</span>
                            </div>
                            <div className="flex justify-between items-center py-2 border-b border-slate-800">
                                <span className="text-slate-400">Spread</span>
                                <span className={`font-mono ${indicators?.spread > 1.5 ? 'text-rose-400' : 'text-emerald-400'}`}>
                                    {indicators?.spread?.toFixed(2) ?? '-'}
                                </span>
                            </div>
                            <div className="flex justify-between items-center py-2">
                                <span className="text-slate-400">Depth</span>
                                <span className={`font-mono ${indicators?.smoothed_depth < 50000 ? 'text-rose-400' : 'text-emerald-400'}`}>
                                    {indicators?.smoothed_depth ? `$${(indicators?.smoothed_depth / 1000).toFixed(0)}k` : '-'}
                                </span>
                            </div>
                        </CardContent>
                    </Card>
                </div>

                <div className="lg:col-span-2 space-y-4">
                    <SignalCard status={displayStatus} signal={displaySignal} formingSince={data.forming_since} />
                    {testSignal && <div className="text-center bg-amber-500/10 border border-amber-500/20 text-amber-400 p-2 rounded text-sm font-bold">⚠️ DISPLAYING TEST SIGNAL DATA</div>}
                </div>
            </div>

            <Collapsible open={isDebugOpen} onOpenChange={setIsDebugOpen} className="fixed bottom-0 left-0 right-0 bg-slate-900 border-t border-slate-800 z-50">
                <div className="flex items-center justify-between p-2 px-4 cursor-pointer hover:bg-slate-800" onClick={() => setIsDebugOpen(!isDebugOpen)}>
                    <div className="flex items-center gap-2 text-slate-400 text-xs font-mono uppercase">
                        <Terminal className="h-3 w-3" /> Engine Debug
                    </div>
                    {isDebugOpen ? <ChevronDown className="h-4 w-4 text-slate-500" /> : <ChevronUp className="h-4 w-4 text-slate-500" />}
                </div>
                <CollapsibleContent>
                    <div className="p-4 grid grid-cols-1 md:grid-cols-4 gap-4 text-xs font-mono bg-slate-950/50">
                        <div className="space-y-2">
                            <h4 className="text-slate-500 font-bold uppercase">Candles</h4>
                            <DebugRow label="1m Count" value={`${debug?.candle_count_1m} / 50`} status={debug?.candle_count_1m >= 50} />
                            <DebugRow label="5m Count" value={`${debug?.candle_count_5m} / 20`} status={debug?.candle_count_5m >= 20} />
                            <div className="border-t border-slate-800 pt-1 mt-1">
                                <div className="text-slate-600">Last 5m Candle:</div>
                                <div className="text-slate-400 truncate">{debug?.last_candle_5m ? new Date(debug.last_candle_5m.startTime).toISOString().substr(11, 8) : '-'}</div>
                            </div>
                        </div>
                        <div className="space-y-2">
                            <h4 className="text-slate-500 font-bold uppercase">Data Flow</h4>
                            <DebugRow label="WS Rate" value={`${debug?.ws_rate?.toFixed(1)} msg/s`} status={debug?.ws_rate > 0} />
                            <DebugRow label="Trades Buffer" value={debug?.trade_buffer_size} status={debug?.trade_buffer_size > 0} />
                        </div>
                        <div className="space-y-2">
                            <h4 className="text-slate-500 font-bold uppercase">Connection</h4>
                            <div className={`p-2 rounded bg-slate-900 text-slate-400`}>
                                {usingPolling ? "Using HTTP Polling" : "Using WebSocket"}
                            </div>
                            <div className="mt-2">
                                <Button size="sm" variant="outline" className="w-full" onClick={(e) => { e.stopPropagation(); toggleTestSignal(); }}>{testSignal ? "Hide Test" : "Show Test"}</Button>
                            </div>
                        </div>
                    </div>
                </CollapsibleContent>
            </Collapsible>
        </div>
    );
}

const CheckItem = ({ label, passed, value }) => (
    <div className="flex justify-between items-center text-xs py-1 border-b border-slate-800 last:border-0">
        <span className="text-slate-400">{label}</span>
        <div className="flex items-center gap-2">
            <span className="text-slate-500">{value}</span>
            {passed ? <CheckCircle2 className="h-4 w-4 text-emerald-400" /> : <Circle className="h-4 w-4 text-rose-400" />}
        </div>
    </div>
);

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

const IndicatorRow = ({ label, value, format, threshold, isPercentage, isRSI, suffix = "" }) => {
    let color = 'text-slate-400';
    const displayValue = value === null || value === undefined ? '-' : value.toFixed(label === "Funding Rate" ? 4 : 2);
    if (value !== null && value !== undefined) {
        if (label === "Funding Rate") {
            if (value > 0.03 || value < -0.02) color = 'text-rose-400';
            else if ((value > 0.01 && value <= 0.03) || (value >= -0.02 && value < -0.01)) color = 'text-amber-400';
            else color = 'text-emerald-400';
        } else if (isRSI) {
            if (value > 70) color = 'text-rose-400';
            else if (value < 30) color = 'text-emerald-400';
            else color = 'text-white';
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

const DebugRow = ({ label, value, status }) => (
    <div className="flex justify-between items-center">
        <span className="text-slate-500">{label}</span>
        <span className={`font-bold ${status ? 'text-emerald-400' : 'text-rose-400'}`}>{value}</span>
    </div>
);
