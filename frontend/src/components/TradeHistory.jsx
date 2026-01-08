import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import {
  Table,
  TableHeader,
  TableRow,
  TableHead,
  TableBody,
  TableCell,
} from '@/components/ui/table';
import { Badge } from '@/components/ui/badge';
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from '@/components/ui/tooltip';

const TradeHistory = () => {
  const [trades, setTrades] = useState([]);
  const [stats, setStats] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetchTrades = async () => {
    try {
      const backendUrl = process.env.REACT_APP_BACKEND_URL || '';
      const response = await fetch(`${backendUrl}/api/trades?limit=20`);
      
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
      }
      
      const data = await response.json();
      setTrades(data.trades || []);
      setStats(data.stats || {});
      setError(null);
    } catch (err) {
      console.error('Error fetching trades:', err);
      setError(err.message);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchTrades();
    const interval = setInterval(fetchTrades, 5000);
    return () => clearInterval(interval);
  }, []);

  const formatTime = (timestamp) => {
    if (!timestamp) return '-';
    const date = new Date(timestamp * 1000);
    return date.toLocaleTimeString('en-US', { 
      hour: '2-digit', 
      minute: '2-digit',
      second: '2-digit',
      hour12: false 
    });
  };

  const formatPrice = (price) => {
    if (price === null || price === undefined) return '-';
    return `$${parseFloat(price).toLocaleString('en-US', { 
      minimumFractionDigits: 2, 
      maximumFractionDigits: 2 
    })}`;
  };

  const formatPnL = (pnl) => {
    if (pnl === null || pnl === undefined) return '-';
    const value = parseFloat(pnl);
    const sign = value >= 0 ? '+' : '';
    return `${sign}$${value.toFixed(2)}`;
  };

  const formatROI = (roi) => {
    if (roi === null || roi === undefined) return '-';
    const value = parseFloat(roi);
    const sign = value >= 0 ? '+' : '';
    return `${sign}${value.toFixed(2)}%`;
  };

  const getOutcomeBadge = (outcome) => {
    if (!outcome) return null;
    
    const variants = {
      WIN: 'bg-green-500/20 text-green-400 border-green-500/30',
      LOSS: 'bg-red-500/20 text-red-400 border-red-500/30',
      EXPIRED: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
    };
    
    const labels = {
      WIN: 'TP HIT',
      LOSS: 'SL HIT',
      EXPIRED: 'EXPIRED'
    };
    
    return (
      <Badge className={`${variants[outcome] || 'bg-gray-500/20 text-gray-400'} border text-xs`}>
        {labels[outcome] || outcome}
      </Badge>
    );
  };

  const getDirectionBadge = (direction) => {
    if (!direction) return null;
    
    const isLong = direction === 'LONG';
    return (
      <Badge className={`${isLong ? 'bg-green-500/20 text-green-400 border-green-500/30' : 'bg-red-500/20 text-red-400 border-red-500/30'} border`}>
        {direction}
      </Badge>
    );
  };

  const getSymbolDisplay = (symbol) => {
    if (!symbol) return '-';
    return symbol.split('-')[0];
  };

  return (
    <Card className="bg-slate-800/50 border-slate-700 mt-6">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2">
            <CardTitle className="text-lg font-semibold text-white flex items-center gap-2">
              📊 Trade History
            </CardTitle>
            
            {/* Info Tooltip */}
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="cursor-help text-slate-400 hover:text-slate-300 text-sm">ℹ️</span>
                </TooltipTrigger>
                <TooltipContent className="bg-slate-700 border-slate-600 text-white max-w-xs">
                  <div className="text-sm">
                    <p className="font-semibold mb-1">P&L Calculation:</p>
                    <p className="text-slate-300">• Capital: $100,000</p>
                    <p className="text-slate-300">• Leverage: 10x</p>
                    <p className="text-slate-300">• Position Size: $1,000,000</p>
                    <p className="text-slate-400 mt-2 text-xs">
                      ROI% = P&L ÷ Capital × 100
                    </p>
                    <p className="text-slate-400 mt-1 text-xs">
                      Only signals with confidence ≥80 are tracked
                    </p>
                  </div>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>
          
          {/* Stats Summary */}
          {stats.total_trades > 0 && (
            <div className="flex items-center gap-4 text-sm flex-wrap">
              <span className="text-slate-400">
                Trades: <span className="text-white font-medium">{stats.total_trades}</span>
              </span>
              <span className="text-slate-400">
                Win Rate: <span className={`font-medium ${stats.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                  {stats.win_rate?.toFixed(1)}%
                </span>
              </span>
              <span className="text-slate-400">
                P&L: <span className={`font-medium ${stats.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl?.toFixed(2)}
                </span>
              </span>
              <span className="text-slate-400">
                ROI: <span className={`font-medium ${stats.total_roi >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {stats.total_roi >= 0 ? '+' : ''}{stats.total_roi?.toFixed(2)}%
                </span>
              </span>
            </div>
          )}
        </div>
      </CardHeader>
      
      <CardContent>
        {loading && trades.length === 0 ? (
          <div className="text-center py-8 text-slate-400">
            Loading trade history...
          </div>
        ) : error ? (
          <div className="text-center py-8 text-red-400">
            Error loading trades: {error}
          </div>
        ) : trades.length === 0 ? (
          <div className="text-center py-8 text-slate-400">
            <p className="text-lg mb-2">No trades recorded yet</p>
            <p className="text-sm">Trades will appear here when signals with confidence ≥80 are triggered</p>
          </div>
        ) : (
          <div className="rounded-lg border border-slate-700 overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-slate-700 hover:bg-slate-800/50">
                  <TableHead className="text-slate-400 font-medium">Time</TableHead>
                  <TableHead className="text-slate-400 font-medium">Symbol</TableHead>
                  <TableHead className="text-slate-400 font-medium">Dir</TableHead>
                  <TableHead className="text-slate-400 font-medium text-right">Entry</TableHead>
                  <TableHead className="text-slate-400 font-medium text-right">TP1</TableHead>
                  <TableHead className="text-slate-400 font-medium text-center">Score</TableHead>
                  <TableHead className="text-slate-400 font-medium text-center">Outcome</TableHead>
                  <TableHead className="text-slate-400 font-medium text-right">P&L</TableHead>
                  <TableHead className="text-slate-400 font-medium text-right">ROI%</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {trades.map((trade, index) => (
                  <TableRow 
                    key={trade.id || index} 
                    className="border-slate-700 hover:bg-slate-700/30"
                  >
                    <TableCell className="text-slate-300 font-mono text-sm">
                      {formatTime(trade.entry_time)}
                    </TableCell>
                    <TableCell className="font-medium text-white">
                      {getSymbolDisplay(trade.symbol)}
                    </TableCell>
                    <TableCell>
                      {getDirectionBadge(trade.direction)}
                    </TableCell>
                    <TableCell className="text-right text-slate-300 font-mono text-sm">
                      {formatPrice(trade.entry_price)}
                    </TableCell>
                    <TableCell className="text-right text-cyan-400 font-mono text-sm">
                      {formatPrice(trade.tp1)}
                    </TableCell>
                    <TableCell className="text-center">
                      <span className={`font-mono text-sm ${
                        (trade.confidence_score || 0) >= 90 ? 'text-green-400' : 
                        (trade.confidence_score || 0) >= 80 ? 'text-yellow-400' : 'text-slate-400'
                      }`}>
                        {trade.confidence_score || '-'}
                      </span>
                    </TableCell>
                    <TableCell className="text-center">
                      {getOutcomeBadge(trade.outcome)}
                    </TableCell>
                    <TableCell className={`text-right font-mono font-medium ${
                      trade.pnl_absolute >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {formatPnL(trade.pnl_absolute)}
                    </TableCell>
                    <TableCell className={`text-right font-mono text-sm ${
                      trade.roi_percent >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {formatROI(trade.roi_percent)}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </CardContent>
    </Card>
  );
};

export default TradeHistory;
