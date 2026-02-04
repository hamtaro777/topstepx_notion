#!/usr/bin/env python3
"""
往復トレード変換モジュール (roundtrip_transformer.py)

TopstepX APIの片道トレードデータを往復トレードデータに変換

データ形式:
- 入力: TopstepX APIのトレードデータ（片道）
  - side: 0=BUY, 1=SELL
  - profitAndLoss: null=エントリー、値あり=エグジット

- 出力: 往復トレード（ラウンドトリップ）
  - entry/exit がペアリングされた構造
  - 統計情報（勝率、P&L、プロフィットファクター等）
"""

import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple
from collections import defaultdict


def parse_timestamp(ts: str) -> datetime:
    """ISO形式のタイムスタンプをパース"""
    formats = [
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(ts, fmt)
        except ValueError:
            continue
    # フォールバック
    if '+' in ts:
        ts = ts.rsplit('+', 1)[0]
    elif ts.endswith('Z'):
        ts = ts[:-1]
    return datetime.fromisoformat(ts)


def extract_contract_symbol(contract_id: str) -> str:
    """
    契約IDからシンボルを抽出
    例: CON.F.US.MNQ.Z25 -> MNQ
    """
    known_symbols = ["MNQ", "MES", "NQ", "ES", "MCL", "MGC", "CL", "GC", "M2K", "MYM"]
    for symbol in known_symbols:
        if symbol in contract_id.upper():
            return symbol
    parts = contract_id.split('.')
    if len(parts) >= 4:
        return parts[3]
    return contract_id


# 契約ごとのポイント単価（1ポイントあたりのドル価値）
CONTRACT_POINT_VALUES = {
    "MNQ": 2.0,    # Micro E-mini Nasdaq: $2 per point
    "MES": 5.0,    # Micro E-mini S&P 500: $5 per point
    "NQ": 20.0,    # E-mini Nasdaq: $20 per point
    "ES": 50.0,    # E-mini S&P 500: $50 per point
    "MCL": 10.0,   # Micro WTI Crude Oil: $10 per point
    "CL": 1000.0,  # WTI Crude Oil: $1000 per point
    "MGC": 10.0,   # Micro Gold: $10 per point
    "GC": 100.0,   # Gold: $100 per point
    "M2K": 5.0,    # Micro E-mini Russell 2000: $5 per point
    "MYM": 0.50,   # Micro E-mini Dow: $0.50 per point
}


def get_point_value(contract_symbol: str) -> float:
    """契約シンボルからポイント単価を取得"""
    return CONTRACT_POINT_VALUES.get(contract_symbol.upper(), 1.0)


def format_duration(seconds: int) -> str:
    """秒数を読みやすい形式に変換"""
    if seconds < 60:
        return f"{seconds}秒"
    elif seconds < 3600:
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}分{secs}秒"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}時間{minutes}分"


class RoundtripTransformer:
    """往復トレード変換クラス"""
    
    def __init__(self):
        self.roundtrips: List[Dict[str, Any]] = []
        self.open_positions: List[Dict[str, Any]] = []
        self.unmatched_exits: List[Dict[str, Any]] = []
    
    def transform(self, trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        片道トレードを往復トレードに変換
        
        Args:
            trades: TopstepX APIからの生トレードデータ
        
        Returns:
            往復トレードのリスト
        """
        self.roundtrips = []
        self.open_positions = []
        self.unmatched_exits = []
        
        # 契約ごとにトレードをグループ化
        trades_by_contract = defaultdict(list)
        for trade in trades:
            contract_id = trade.get('contractId', '')
            trades_by_contract[contract_id].append(trade)
        
        roundtrip_id = 0
        
        for contract_id, contract_trades in trades_by_contract.items():
            # 時系列でソート
            contract_trades.sort(key=lambda x: x.get('creationTimestamp', ''))
            
            # エントリーとエグジットを分離
            entries = [t for t in contract_trades if t.get('profitAndLoss') is None]
            exits = [t for t in contract_trades if t.get('profitAndLoss') is not None]
            
            entry_queue = list(entries)
            
            for exit_trade in exits:
                if not entry_queue:
                    self.unmatched_exits.append(exit_trade)
                    continue
                
                # 対応するエントリーを探す
                entry_trade = self._find_matching_entry(entry_queue, exit_trade)
                
                if entry_trade is None:
                    entry_trade = entry_queue.pop(0)
                
                roundtrip_id += 1
                roundtrip = self._create_roundtrip(
                    roundtrip_id, contract_id, entry_trade, exit_trade
                )
                self.roundtrips.append(roundtrip)
            
            # 未決済のエントリーを記録
            self.open_positions.extend(entry_queue)
        
        # 時系列でソート
        self.roundtrips.sort(key=lambda x: x['exit']['timestamp'])
        
        return self.roundtrips
    
    def _find_matching_entry(
        self, 
        entry_queue: List[Dict], 
        exit_trade: Dict
    ) -> Optional[Dict]:
        """マッチするエントリーを検索"""
        for i, entry in enumerate(entry_queue):
            # 反対のside、同じサイズ
            if (entry.get('side') != exit_trade.get('side') and 
                entry.get('size') == exit_trade.get('size')):
                return entry_queue.pop(i)
        return None
    
    def _create_roundtrip(
        self,
        roundtrip_id: int,
        contract_id: str,
        entry_trade: Dict,
        exit_trade: Dict
    ) -> Dict[str, Any]:
        """往復トレードデータを作成"""
        direction = "LONG" if entry_trade.get('side') == 0 else "SHORT"

        entry_ts = parse_timestamp(entry_trade.get('creationTimestamp', ''))
        exit_ts = parse_timestamp(exit_trade.get('creationTimestamp', ''))
        duration_seconds = int((exit_ts - entry_ts).total_seconds())

        entry_price = float(entry_trade.get('price', 0))
        exit_price = float(exit_trade.get('price', 0))
        size = exit_trade.get('size', 1)

        if direction == "LONG":
            points = exit_price - entry_price
        else:
            points = entry_price - exit_price

        entry_fees = float(entry_trade.get('fees', 0) or 0)
        exit_fees = float(exit_trade.get('fees', 0) or 0)
        total_fees = entry_fees + exit_fees

        # PnLの計算: Order形式の場合はポイントから計算
        pnl_from_api = exit_trade.get('profitAndLoss')
        is_from_order = entry_trade.get('_source') == 'order' or exit_trade.get('_source') == 'order'

        if pnl_from_api is not None and pnl_from_api != 0.0 and not is_from_order:
            # Trade/searchからの場合: APIからのPnLを使用
            pnl = float(pnl_from_api)
        else:
            # Order/searchからの場合: ポイントとポイント単価から計算
            contract_symbol = extract_contract_symbol(contract_id)
            point_value = get_point_value(contract_symbol)
            pnl = points * point_value * size

        net_pnl = pnl - total_fees

        return {
            "roundtrip_id": roundtrip_id,
            "contract": extract_contract_symbol(contract_id),
            "contract_id": contract_id,
            "direction": direction,
            "size": size,
            "entry": {
                "trade_id": entry_trade.get('id'),
                "order_id": entry_trade.get('orderId'),
                "timestamp": entry_trade.get('creationTimestamp'),
                "price": entry_price,
                "side": "BUY" if entry_trade.get('side') == 0 else "SELL",
                "fees": entry_fees
            },
            "exit": {
                "trade_id": exit_trade.get('id'),
                "order_id": exit_trade.get('orderId'),
                "timestamp": exit_trade.get('creationTimestamp'),
                "price": exit_price,
                "side": "BUY" if exit_trade.get('side') == 0 else "SELL",
                "fees": exit_fees
            },
            "pnl": round(pnl, 2),
            "total_fees": total_fees,
            "net_pnl": round(net_pnl, 2),
            "points": round(points, 2),
            "duration_seconds": duration_seconds,
            "duration_formatted": format_duration(duration_seconds)
        }
    
    def get_statistics(self) -> Dict[str, Any]:
        """往復トレードの統計を計算"""
        if not self.roundtrips:
            return {}
        
        total = len(self.roundtrips)
        winners = [rt for rt in self.roundtrips if rt['pnl'] > 0]
        losers = [rt for rt in self.roundtrips if rt['pnl'] < 0]
        breakeven = [rt for rt in self.roundtrips if rt['pnl'] == 0]
        
        total_pnl = sum(rt['pnl'] for rt in self.roundtrips)
        total_fees = sum(rt['total_fees'] for rt in self.roundtrips)
        
        avg_win = sum(rt['pnl'] for rt in winners) / len(winners) if winners else 0
        avg_loss = sum(rt['pnl'] for rt in losers) / len(losers) if losers else 0
        
        gross_profit = sum(rt['pnl'] for rt in winners)
        gross_loss = abs(sum(rt['pnl'] for rt in losers))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else 0
        
        avg_duration = sum(rt['duration_seconds'] for rt in self.roundtrips) / total
        
        # 契約別・方向別の集計
        by_contract = self._group_stats('contract')
        by_direction = self._group_stats('direction')
        
        return {
            "total_roundtrips": total,
            "winning_trades": len(winners),
            "losing_trades": len(losers),
            "breakeven_trades": len(breakeven),
            "win_rate": round(len(winners) / total * 100, 1),
            "total_pnl": round(total_pnl, 2),
            "total_fees": round(total_fees, 2),
            "total_net_pnl": round(total_pnl - total_fees, 2),
            "avg_win": round(avg_win, 2),
            "avg_loss": round(avg_loss, 2),
            "profit_factor": profit_factor,
            "max_win": round(max(rt['pnl'] for rt in self.roundtrips), 2),
            "max_loss": round(min(rt['pnl'] for rt in self.roundtrips), 2),
            "avg_duration_seconds": int(avg_duration),
            "avg_duration_formatted": format_duration(int(avg_duration)),
            "by_contract": by_contract,
            "by_direction": by_direction,
            "open_positions": len(self.open_positions),
            "unmatched_exits": len(self.unmatched_exits)
        }
    
    def _group_stats(self, group_key: str) -> Dict[str, Dict]:
        """指定キーでグループ化した統計"""
        groups = defaultdict(lambda: {"count": 0, "pnl": 0.0, "wins": 0, "losses": 0})
        for rt in self.roundtrips:
            key = rt.get(group_key)
            groups[key]["count"] += 1
            groups[key]["pnl"] += rt['pnl']
            if rt['pnl'] > 0:
                groups[key]["wins"] += 1
            elif rt['pnl'] < 0:
                groups[key]["losses"] += 1
        return dict(groups)
    
    def to_dict(self) -> Dict[str, Any]:
        """結果を辞書形式で出力"""
        return {
            "statistics": self.get_statistics(),
            "roundtrips": self.roundtrips,
            "open_positions": [
                {
                    "trade_id": p.get('id'),
                    "contract_id": p.get('contractId'),
                    "side": "BUY" if p.get('side') == 0 else "SELL",
                    "price": p.get('price'),
                    "size": p.get('size'),
                    "timestamp": p.get('creationTimestamp')
                }
                for p in self.open_positions
            ]
        }


def transform_trades(trades: List[Dict[str, Any]]) -> Tuple[List[Dict], Dict]:
    """
    簡易関数: 片道トレードを往復トレードに変換
    
    Args:
        trades: TopstepXの生トレードデータ
    
    Returns:
        (roundtrips, statistics) のタプル
    """
    transformer = RoundtripTransformer()
    roundtrips = transformer.transform(trades)
    statistics = transformer.get_statistics()
    return roundtrips, statistics


# スタンドアロン実行用
if __name__ == "__main__":
    import sys
    
    # JSONファイルから読み込み
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    else:
        input_file = "trade_data_raw.json"
    
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f"❌ ファイルが見つかりません: {input_file}")
        sys.exit(1)
    
    trades = data.get("trades", [])
    account = data.get("account", {})
    
    print(f"📊 アカウント: {account.get('name')}")
    print(f"   片道トレード数: {len(trades)}")
    
    # 変換
    transformer = RoundtripTransformer()
    roundtrips = transformer.transform(trades)
    stats = transformer.get_statistics()
    
    print(f"\n✅ 変換完了")
    print(f"   往復トレード: {stats.get('total_roundtrips')}件")
    print(f"   勝率: {stats.get('win_rate')}%")
    print(f"   純損益: ${stats.get('total_net_pnl'):,.2f}")
    print(f"   プロフィットファクター: {stats.get('profit_factor')}")
    
    # 結果を保存
    output = {
        "timestamp": data.get("timestamp"),
        "account": account,
        **transformer.to_dict()
    }
    
    output_file = input_file.replace(".json", "_roundtrips.json")
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)
    
    print(f"\n💾 保存: {output_file}")