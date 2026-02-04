#!/usr/bin/env python3
"""
TopstepX トレードデータ取得スクリプト
Step 1: APIからトレードデータを取得して中身を確認
"""

import json
import sys
import os
from datetime import datetime, timedelta, timezone

# 現在のスクリプトのディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topstepx_client import TopstepXClient, format_trade, is_live_account, convert_orders_to_trades


def select_account(accounts: list) -> dict:
    """ユーザーにアカウントを選択させる"""
    
    # アカウントを種類別に分類
    live_accounts = []      # TOPX (Funded Live)
    express_accounts = []   # EXPRESS
    combine_accounts = []   # KTC (Combine)
    practice_accounts = []  # PRACTICE, PRAC
    
    for acc in accounts:
        name = acc.get('name', '').upper()
        if 'TOPX' in name:
            live_accounts.append(acc)
        elif 'EXPRESS' in name:
            express_accounts.append(acc)
        elif 'KTC' in name:
            combine_accounts.append(acc)
        elif 'PRACTICE' in name or 'PRAC-' in name:
            practice_accounts.append(acc)
        else:
            # 不明なタイプはCombineに分類
            combine_accounts.append(acc)
    
    # 最新のアカウントを優先（IDが大きい＝新しい）
    live_accounts.sort(key=lambda x: x.get('id', 0), reverse=True)
    express_accounts.sort(key=lambda x: x.get('id', 0), reverse=True)
    combine_accounts.sort(key=lambda x: x.get('id', 0), reverse=True)
    practice_accounts.sort(key=lambda x: x.get('id', 0), reverse=True)
    
    print("\n【アカウント概要】")
    print(f"  ライブ (TOPX): {len(live_accounts)} 個")
    print(f"  エクスプレス: {len(express_accounts)} 個")
    print(f"  コンバイン: {len(combine_accounts)} 個")
    print(f"  プラクティス: {len(practice_accounts)} 個")
    
    # 最新のアカウントを表示
    print("\n【最新のアカウント（各カテゴリ上位5件）】")
    
    display_accounts = []
    
    # Live（TOPX）を最優先で表示
    if live_accounts:
        print("\n--- ライブ (TOPX) ---")
        for i, acc in enumerate(live_accounts[:5]):
            display_accounts.append(acc)
            idx = len(display_accounts)
            print(f"  [{idx}] {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
    
    if express_accounts:
        print("\n--- エクスプレス ---")
        for i, acc in enumerate(express_accounts[:5]):
            display_accounts.append(acc)
            idx = len(display_accounts)
            print(f"  [{idx}] {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
    
    if combine_accounts:
        print("\n--- コンバイン ---")
        for i, acc in enumerate(combine_accounts[:3]):
            display_accounts.append(acc)
            idx = len(display_accounts)
            print(f"  [{idx}] {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
    
    if practice_accounts:
        print("\n--- プラクティス ---")
        for i, acc in enumerate(practice_accounts[:3]):
            display_accounts.append(acc)
            idx = len(display_accounts)
            print(f"  [{idx}] {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
    
    # ユーザー入力
    print(f"\n  [0] 全アカウント一覧を表示")
    
    while True:
        try:
            choice = input("\n選択してください (番号を入力): ").strip()
            
            if choice == '0':
                # 全アカウント表示
                print("\n【全アカウント一覧】")
                for i, acc in enumerate(accounts):
                    print(f"  [{i+1}] ID:{acc.get('id')} - {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
                
                choice = input("\n選択してください (番号を入力): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(accounts):
                    return accounts[idx]
            else:
                idx = int(choice) - 1
                if 0 <= idx < len(display_accounts):
                    return display_accounts[idx]
            
            print("無効な選択です。もう一度入力してください。")
        except ValueError:
            print("数字を入力してください。")
        except KeyboardInterrupt:
            print("\n中断されました。")
            sys.exit(0)


def main():
    print("=" * 60)
    print("TopstepX トレードデータ取得")
    print("=" * 60)
    
    # クライアントを初期化
    try:
        client = TopstepXClient("credentials.json")
    except FileNotFoundError as e:
        print(f"\n❌ エラー: {e}")
        print("\n📝 以下の手順で credentials.json を作成してください:")
        print("   1. credentials.example.json をコピーして credentials.json を作成")
        print("   2. username と api_key を自分のものに置き換える")
        return
    except Exception as e:
        print(f"\n❌ 初期化エラー: {e}")
        return
    
    # 認証
    print("\n🔐 認証中...")
    try:
        auth_result = client.authenticate()
        print(f"   トークン取得: {client.session_token[:20]}...")
    except Exception as e:
        print(f"\n❌ 認証エラー: {e}")
        return
    
    # アカウント一覧を取得
    print("\n📋 アカウント一覧を取得中...")
    try:
        accounts = client.get_accounts()
        print(f"   {len(accounts)} 個のアカウントが見つかりました")
        
        if not accounts:
            print("\n⚠️ アカウントが見つかりませんでした")
            return
        
        # アカウント選択
        account = select_account(accounts)
        account_id = account.get('id')
        print(f"\n📌 選択されたアカウント: '{account.get('name')}' (ID: {account_id})")
        print(f"   残高: ${account.get('balance', 0):,.2f}")
        
    except Exception as e:
        print(f"\n❌ アカウント取得エラー: {e}")
        return
    
    # LIVE口座かどうかを判定
    account_name = account.get('name', '')
    use_order_api = is_live_account(account_name)

    # トレード履歴を取得（過去30日間）
    trades = []
    print("\n📊 トレード履歴を取得中（過去30日間）...")
    if use_order_api:
        print("   🔄 LIVE口座検出: Order/search APIを使用")

    try:
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=30)

        if use_order_api:
            # LIVE口座: Order/searchを使用
            orders = client.get_order_history(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date
            )
            print(f"   {len(orders)} 件の約定済みオーダーが見つかりました")

            if orders:
                # Order形式をTrade形式に変換
                trades = convert_orders_to_trades(orders)
                print(f"   {len(trades)} 件の片道トレードに変換")
        else:
            # その他の口座: Trade/searchを使用
            trades = client.get_trades(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date
            )
            print(f"   {len(trades)} 件のトレードが見つかりました")

        if trades:
            print("\n【トレード履歴】")
            print("-" * 50)
            for i, trade in enumerate(trades[:10]):  # 最初の10件を表示
                print(f"\nTrade #{i+1}")
                print(format_trade(trade))

            if len(trades) > 10:
                print(f"\n... 他 {len(trades) - 10} 件のトレード")

            # 統計情報
            print("\n【統計情報】")
            print("-" * 50)

            # 完了したトレード（P&Lがnullでないもの）のみ集計
            completed_trades = [t for t in trades if t.get('profitAndLoss') is not None]

            total_pnl = sum(t.get('profitAndLoss', 0) for t in completed_trades)
            total_fees = sum(t.get('fees', 0) or 0 for t in trades)
            winning_trades = [t for t in completed_trades if t.get('profitAndLoss', 0) > 0]
            losing_trades = [t for t in completed_trades if t.get('profitAndLoss', 0) < 0]

            print(f"  総トレード数: {len(trades)}")
            print(f"  完了トレード: {len(completed_trades)}")
            print(f"  勝ちトレード: {len(winning_trades)}")
            print(f"  負けトレード: {len(losing_trades)}")
            if completed_trades:
                win_rate = len(winning_trades) / len(completed_trades) * 100
                print(f"  勝率: {win_rate:.1f}%")
            print(f"  総損益: ${total_pnl:,.2f}")
            print(f"  総手数料: ${total_fees:,.2f}")
            print(f"  純損益: ${total_pnl - total_fees:,.2f}")
        else:
            print("\n⚠️ 過去30日間のトレードはありませんでした")

            # より長い期間を試す
            print("\n📊 過去90日間を検索中...")
            start_date = end_date - timedelta(days=90)

            if use_order_api:
                orders = client.get_order_history(
                    account_id=account_id,
                    start_date=start_date,
                    end_date=end_date
                )
                if orders:
                    trades = convert_orders_to_trades(orders)
            else:
                trades = client.get_trades(
                    account_id=account_id,
                    start_date=start_date,
                    end_date=end_date
                )

            print(f"   {len(trades)} 件のトレードが見つかりました")

            if trades:
                print("\n【最新のトレード（最大10件）】")
                for i, trade in enumerate(trades[:10]):
                    print(f"\nTrade #{i+1}")
                    print(format_trade(trade))

    except Exception as e:
        print(f"\n❌ トレード取得エラー: {e}")
        import traceback
        traceback.print_exc()
    
    # 現在のポジション（オプション - エラーでも続行）
    positions = []
    print("\n📍 現在のポジションを取得中...")
    try:
        positions = client.get_positions(account_id)
        
        if positions:
            print(f"   {len(positions)} 件のポジションがあります")
            print("\n【ポジション】")
            for pos in positions:
                side = "LONG" if pos.get('side') == 0 else "SHORT"
                print(f"  Contract: {pos.get('contractId')}")
                print(f"  Side: {side}")
                print(f"  Size: {pos.get('size')}")
                print(f"  Avg Price: {pos.get('averagePrice')}")
                print()
        else:
            print("   ポジションなし")
            
    except Exception as e:
        print(f"   ⚠️ ポジション取得をスキップ: {e}")
    
    # RAWデータを保存（デバッグ用）
    print("\n💾 RAWデータを保存中...")
    try:
        output_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "account": account,
            "trades": trades,
            "positions": positions
        }
        
        with open("trade_data_raw.json", "w", encoding="utf-8") as f:
            json.dump(output_data, f, indent=2, ensure_ascii=False, default=str)
        
        print("   ✅ trade_data_raw.json に保存しました")
        
    except Exception as e:
        print(f"\n❌ データ保存エラー: {e}")
    
    print("\n" + "=" * 60)
    print("完了!")
    print("=" * 60)


if __name__ == "__main__":
    main()