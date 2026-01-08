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
    const interval = setInterval(fetchTrades, 5000); // Refresh every 5 seconds
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

  const getOutcomeBadge = (outcome) => {
    if (!outcome) return null;
    
    const variants = {
      WIN: 'bg-green-500/20 text-green-400 border-green-500/30',
      LOSS: 'bg-red-500/20 text-red-400 border-red-500/30',
      EXPIRED: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
    };
    
    return (
      <Badge className={`${variants[outcome] || 'bg-gray-500/20 text-gray-400'} border`}>
        {outcome}
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
    // Convert "BTC-USDT-SWAP" to "BTC"
    return symbol.split('-')[0];
  };

  return (
    <Card className="bg-slate-800/50 border-slate-700 mt-6">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg font-semibold text-white flex items-center gap-2">
            📊 Trade History
          </CardTitle>
          
          {/* Stats Summary */}
          {stats.total_trades > 0 && (
            <div className="flex items-center gap-4 text-sm">
              <span className="text-slate-400">
                Trades: <span className="text-white font-medium">{stats.total_trades}</span>
              </span>
              <span className="text-slate-400">
                Win Rate: <span className={`font-medium ${stats.win_rate >= 50 ? 'text-green-400' : 'text-red-400'}`}>
                  {stats.win_rate?.toFixed(1)}%
                </span>
              </span>
              <span className="text-slate-400">
                Total P&L: <span className={`font-medium ${stats.total_pnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                  {stats.total_pnl >= 0 ? '+' : ''}${stats.total_pnl?.toFixed(2)}
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
            <p className="text-sm">Trades will appear here when signals are triggered and closed</p>
          </div>
        ) : (
          <div className="rounded-lg border border-slate-700 overflow-hidden">
            <Table>
              <TableHeader>
                <TableRow className="border-slate-700 hover:bg-slate-800/50">
                  <TableHead className="text-slate-400 font-medium">Time</TableHead>
                  <TableHead className="text-slate-400 font-medium">Symbol</TableHead>
                  <TableHead className="text-slate-400 font-medium">Direction</TableHead>
                  <TableHead className="text-slate-400 font-medium text-right">Entry</TableHead>
                  <TableHead className="text-slate-400 font-medium text-center">Outcome</TableHead>
                  <TableHead className="text-slate-400 font-medium text-right">P&L</TableHead>
                  <TableHead className="text-slate-400 font-medium text-right">MFE</TableHead>
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
                    <TableCell className="text-right text-slate-300 font-mono">
                      {formatPrice(trade.entry_price)}
                    </TableCell>
                    <TableCell className="text-center">
                      {getOutcomeBadge(trade.outcome)}
                    </TableCell>
                    <TableCell className={`text-right font-mono font-medium ${
                      trade.pnl_absolute >= 0 ? 'text-green-400' : 'text-red-400'
                    }`}>
                      {formatPnL(trade.pnl_absolute)}
                    </TableCell>
                    <TableCell className="text-right text-green-400 font-mono text-sm">
                      {trade.max_favorable ? `+$${trade.max_favorable.toFixed(2)}` : '-'}
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
