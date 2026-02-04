#!/usr/bin/env python3
"""
TopstepX → Notion 同期スクリプト（往復トレード版）
トレードデータをTopstepXから取得し、往復トレードに変換してNotionに登録

使い方:
  対話モード:
    python sync_to_notion.py
  
  自動モード:
    python sync_to_notion.py --auto
    python sync_to_notion.py --auto --days 7
    python sync_to_notion.py --auto --account 12345678
    python sync_to_notion.py --auto --account-type live --days 30
    python sync_to_notion.py --auto --account-name "50KTC"
    python sync_to_notion.py --auto --all-accounts --days 7
    python sync_to_notion.py --auto --quiet  # cron用（出力抑制）
"""

import argparse
import json
import sys
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

# 現在のスクリプトのディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from topstepx_client import TopstepXClient, is_live_account, convert_orders_to_trades
from notion_client import NotionRoundtripClient, load_credentials
from roundtrip_transformer import RoundtripTransformer


class Logger:
    """出力制御用ロガー"""
    
    def __init__(self, quiet: bool = False):
        self.quiet = quiet
    
    def print(self, *args, **kwargs):
        if not self.quiet:
            print(*args, **kwargs)
    
    def error(self, *args, **kwargs):
        # エラーは常に出力
        print(*args, **kwargs)


def classify_accounts(accounts: List[Dict]) -> Dict[str, List[Dict]]:
    """アカウントを種類別に分類"""
    live_accounts = []      # TOPX (Funded Live)
    express_accounts = []   # EXPRESS
    combine_accounts = []   # KTC (Combine)
    practice_accounts = []  # PRACTICE
    
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
    
    return {
        'live': live_accounts,
        'express': express_accounts,
        'combine': combine_accounts,
        'practice': practice_accounts
    }


def find_account_by_id(accounts: List[Dict], account_id: int) -> Optional[Dict]:
    """IDでアカウントを検索"""
    for acc in accounts:
        if acc.get('id') == account_id:
            return acc
    return None


def find_account_by_name(accounts: List[Dict], name_pattern: str) -> Optional[Dict]:
    """名前（部分一致）でアカウントを検索"""
    pattern = name_pattern.upper()
    for acc in accounts:
        if pattern in acc.get('name', '').upper():
            return acc
    return None


def get_accounts_by_type(
    classified: Dict[str, List[Dict]], 
    account_type: str
) -> List[Dict]:
    """タイプでアカウントを取得"""
    type_map = {
        'live': classified['live'],
        'express': classified['express'],
        'combine': classified['combine'],
        'practice': classified['practice'],
        'all': classified['live'] + classified['express'] + classified['combine'] + classified['practice']
    }
    return type_map.get(account_type, [])


def select_account_interactive(accounts: List[Dict]) -> Dict:
    """ユーザーにアカウントを選択させる（対話モード）"""
    classified = classify_accounts(accounts)
    
    print("\n【アカウント概要】")
    print(f"  ライブ (TOPX): {len(classified['live'])} 個")
    print(f"  エクスプレス: {len(classified['express'])} 個")
    print(f"  コンバイン: {len(classified['combine'])} 個")
    print(f"  プラクティス: {len(classified['practice'])} 個")
    
    display_accounts = []
    
    # Live（TOPX）を最優先で表示
    if classified['live']:
        print("\n--- ライブ (TOPX) ---")
        for acc in classified['live'][:5]:
            display_accounts.append(acc)
            idx = len(display_accounts)
            print(f"  [{idx}] {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
    
    if classified['express']:
        print("\n--- エクスプレス ---")
        for acc in classified['express'][:5]:
            display_accounts.append(acc)
            idx = len(display_accounts)
            print(f"  [{idx}] {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
    
    if classified['combine']:
        print("\n--- コンバイン ---")
        for acc in classified['combine'][:3]:
            display_accounts.append(acc)
            idx = len(display_accounts)
            print(f"  [{idx}] {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
    
    if classified['practice']:
        print("\n--- プラクティス ---")
        for acc in classified['practice'][:3]:
            display_accounts.append(acc)
            idx = len(display_accounts)
            print(f"  [{idx}] {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
    
    print(f"\n  [0] 全アカウント一覧を表示")
    
    while True:
        try:
            choice = input("\n選択してください (番号を入力): ").strip()
            
            if choice == '0':
                print("\n【全アカウント一覧】")
                all_accounts = (
                    classified['live'] + 
                    classified['express'] + 
                    classified['combine'] + 
                    classified['practice']
                )
                for i, acc in enumerate(all_accounts):
                    print(f"  [{i+1}] {acc.get('name')} - ${acc.get('balance', 0):,.2f}")
                
                choice = input("\n選択してください (番号を入力): ").strip()
                idx = int(choice) - 1
                if 0 <= idx < len(all_accounts):
                    return all_accounts[idx]
            else:
                idx = int(choice) - 1
                if 0 <= idx < len(display_accounts):
                    return display_accounts[idx]
            
            print("無効な選択です。")
        except ValueError:
            print("数字を入力してください。")
        except KeyboardInterrupt:
            print("\n中断されました。")
            sys.exit(0)


def select_period_interactive() -> int:
    """期間を対話的に選択"""
    print("\n📅 同期期間を選択:")
    print("  [1] 過去7日間")
    print("  [2] 過去30日間")
    print("  [3] 過去90日間")
    print("  [4] カスタム（日数を入力）")
    
    try:
        period_choice = input("\n選択 (1-4): ").strip()
        
        if period_choice == '1':
            return 7
        elif period_choice == '2':
            return 30
        elif period_choice == '3':
            return 90
        elif period_choice == '4':
            return int(input("日数を入力: ").strip())
        else:
            return 30
        
    except (ValueError, KeyboardInterrupt):
        return 30


def sync_account(
    topstepx: TopstepXClient,
    notion: NotionRoundtripClient,
    account: Dict,
    days: int,
    logger: Logger
) -> Dict[str, int]:
    """
    単一アカウントを同期

    Returns:
        {"created": n, "skipped": m, "errors": e, "roundtrips": r}
    """
    account_id = account.get('id')
    account_name = account.get('name')

    logger.print(f"\n📌 アカウント: {account_name} (ID: {account_id})")

    # LIVE口座かどうかを判定
    use_order_api = is_live_account(account_name)

    # トレードを取得
    logger.print(f"   📊 過去{days}日間のトレードを取得中...")
    if use_order_api:
        logger.print("   🔄 LIVE口座検出: Order/search APIを使用")

    try:
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        if use_order_api:
            # LIVE口座: Order/searchを使用
            orders = topstepx.get_order_history(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date
            )
            logger.print(f"   {len(orders)} 件の約定済みオーダーを取得")

            if not orders:
                logger.print("   ⚠️ オーダーなし")
                return {"created": 0, "skipped": 0, "errors": 0, "roundtrips": 0}

            # Order形式をTrade形式に変換
            trades = convert_orders_to_trades(orders)
            logger.print(f"   {len(trades)} 件の片道トレードに変換")
        else:
            # その他の口座: Trade/searchを使用
            trades = topstepx.get_trades(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date
            )
            logger.print(f"   {len(trades)} 件の片道トレードを取得")

        if not trades:
            logger.print("   ⚠️ トレードなし")
            return {"created": 0, "skipped": 0, "errors": 0, "roundtrips": 0}

    except Exception as e:
        logger.error(f"   ❌ トレード取得エラー: {e}")
        return {"created": 0, "skipped": 0, "errors": 1, "roundtrips": 0}
    
    # 往復トレードに変換
    logger.print("   🔄 往復トレードに変換中...")
    try:
        transformer = RoundtripTransformer()
        roundtrips = transformer.transform(trades)
        stats = transformer.get_statistics()
        
        logger.print(f"   {len(roundtrips)} 件の往復トレードに変換")
        
        if not roundtrips:
            if transformer.open_positions:
                logger.print(f"   ⚠️ オープンポジション: {len(transformer.open_positions)} 件")
            return {"created": 0, "skipped": 0, "errors": 0, "roundtrips": 0}
        
        logger.print(f"   勝率: {stats.get('win_rate', 0)}% / 純損益: ${stats.get('total_net_pnl', 0):,.2f}")
        
    except Exception as e:
        logger.error(f"   ❌ 変換エラー: {e}")
        return {"created": 0, "skipped": 0, "errors": 1, "roundtrips": 0}
    
    # Notionに同期
    logger.print("   📤 Notionに同期中...")
    try:
        sync_stats = notion.sync_roundtrips(
            roundtrips=roundtrips,
            account_name=account_name,
            skip_existing=True
        )
        
        logger.print(f"   ✅ 作成: {sync_stats['created']} / スキップ: {sync_stats['skipped']}")
        
        return {
            "created": sync_stats['created'],
            "skipped": sync_stats['skipped'],
            "errors": sync_stats['errors'],
            "roundtrips": len(roundtrips)
        }
        
    except Exception as e:
        logger.error(f"   ❌ 同期エラー: {e}")
        return {"created": 0, "skipped": 0, "errors": 1, "roundtrips": len(roundtrips)}


def run_auto_mode(args, logger: Logger) -> int:
    """
    自動モードで実行
    
    Returns:
        終了コード（0=成功, 1=エラー）
    """
    logger.print("=" * 60)
    logger.print("TopstepX → Notion 自動同期")
    logger.print("=" * 60)
    
    # 認証情報を読み込み
    try:
        creds = load_credentials("credentials.json")
    except FileNotFoundError:
        logger.error("❌ credentials.json が見つかりません")
        return 1
    
    topstepx_creds = creds.get("topstepx", {})
    notion_creds = creds.get("notion", {})
    
    if not topstepx_creds.get("username") or not topstepx_creds.get("api_key"):
        logger.error("❌ TopstepXの認証情報が設定されていません")
        return 1
    
    if not notion_creds.get("api_key") or not notion_creds.get("database_id"):
        logger.error("❌ Notionの認証情報が設定されていません")
        return 1
    
    # TopstepXクライアントを初期化
    logger.print("\n🔐 TopstepX認証中...")
    try:
        topstepx = TopstepXClient.__new__(TopstepXClient)
        topstepx.username = topstepx_creds["username"]
        topstepx.api_key = topstepx_creds["api_key"]
        topstepx.session_token = None
        topstepx.session = __import__('requests').Session()
        topstepx.BASE_URL = "https://api.topstepx.com/api"
        
        topstepx.authenticate()
        logger.print("   ✅ TopstepX認証成功")
    except Exception as e:
        logger.error(f"❌ TopstepX認証エラー: {e}")
        return 1
    
    # Notionクライアントを初期化
    logger.print("\n🔐 Notion接続中...")
    try:
        notion = NotionRoundtripClient(
            api_key=notion_creds["api_key"],
            database_id=notion_creds["database_id"]
        )
        db_info = notion.get_database()
        db_title = db_info.get('title', [{}])[0].get('plain_text', 'Database')
        logger.print(f"   ✅ Notion接続成功: {db_title}")
    except Exception as e:
        logger.error(f"❌ Notion接続エラー: {e}")
        return 1
    
    # アカウント一覧を取得
    logger.print("\n📋 アカウント一覧を取得中...")
    try:
        accounts = topstepx.get_accounts()
        logger.print(f"   {len(accounts)} 個のアカウントが見つかりました")
        
        if not accounts:
            logger.error("⚠️ アカウントが見つかりません")
            return 1
        
    except Exception as e:
        logger.error(f"❌ アカウント取得エラー: {e}")
        return 1
    
    # 対象アカウントを決定
    classified = classify_accounts(accounts)
    target_accounts = []
    
    if args.all_accounts:
        # 全アカウント
        target_accounts = accounts
        logger.print(f"\n🎯 全 {len(target_accounts)} アカウントを同期")
    
    elif args.account:
        # IDで指定
        try:
            account_id = int(args.account)
            acc = find_account_by_id(accounts, account_id)
        except ValueError:
            # 名前として検索
            acc = find_account_by_name(accounts, args.account)
        
        if acc:
            target_accounts = [acc]
        else:
            logger.error(f"❌ アカウントが見つかりません: {args.account}")
            return 1
    
    elif args.account_name:
        # 名前パターンで指定
        acc = find_account_by_name(accounts, args.account_name)
        if acc:
            target_accounts = [acc]
        else:
            logger.error(f"❌ アカウントが見つかりません: {args.account_name}")
            return 1
    
    elif args.account_type:
        # タイプで指定
        target_accounts = get_accounts_by_type(classified, args.account_type)
        if not target_accounts:
            logger.error(f"❌ タイプ '{args.account_type}' のアカウントがありません")
            return 1
        logger.print(f"\n🎯 {args.account_type} タイプ: {len(target_accounts)} アカウント")
    
    else:
        # デフォルト: Live(TOPX) > Express > Combine > Practice の優先順
        if classified['live']:
            target_accounts = [classified['live'][0]]
        elif classified['express']:
            target_accounts = [classified['express'][0]]
        elif classified['combine']:
            target_accounts = [classified['combine'][0]]
        elif classified['practice']:
            target_accounts = [classified['practice'][0]]
        else:
            logger.error("❌ 同期対象のアカウントがありません")
            return 1
    
    # 同期実行
    days = args.days
    total_stats = {"created": 0, "skipped": 0, "errors": 0, "roundtrips": 0}
    
    for acc in target_accounts:
        stats = sync_account(topstepx, notion, acc, days, logger)
        total_stats["created"] += stats["created"]
        total_stats["skipped"] += stats["skipped"]
        total_stats["errors"] += stats["errors"]
        total_stats["roundtrips"] += stats["roundtrips"]
    
    # 結果サマリー
    logger.print("\n" + "=" * 60)
    logger.print("📊 同期完了サマリー")
    logger.print("=" * 60)
    logger.print(f"  対象アカウント: {len(target_accounts)}")
    logger.print(f"  往復トレード: {total_stats['roundtrips']}")
    logger.print(f"  新規作成: {total_stats['created']}")
    logger.print(f"  スキップ: {total_stats['skipped']}")
    if total_stats['errors'] > 0:
        logger.print(f"  エラー: {total_stats['errors']}")
    
    return 0 if total_stats['errors'] == 0 else 1


def run_interactive_mode() -> int:
    """対話モードで実行"""
    print("=" * 60)
    print("TopstepX → Notion 同期（往復トレード版）")
    print("=" * 60)
    
    # 認証情報を読み込み
    try:
        creds = load_credentials("credentials.json")
    except FileNotFoundError:
        print("\n❌ credentials.json が見つかりません")
        print("\n📝 credentials.example.json を参考に作成してください")
        return 1
    
    # TopstepX認証情報を確認
    topstepx_creds = creds.get("topstepx", {})
    if not topstepx_creds.get("username") or not topstepx_creds.get("api_key"):
        print("\n❌ TopstepXの認証情報が設定されていません")
        return 1
    
    # Notion認証情報を確認
    notion_creds = creds.get("notion", {})
    if not notion_creds.get("api_key") or not notion_creds.get("database_id"):
        print("\n❌ Notionの認証情報が設定されていません")
        return 1
    
    # TopstepXクライアントを初期化
    print("\n🔐 TopstepX認証中...")
    try:
        topstepx = TopstepXClient.__new__(TopstepXClient)
        topstepx.username = topstepx_creds["username"]
        topstepx.api_key = topstepx_creds["api_key"]
        topstepx.session_token = None
        topstepx.session = __import__('requests').Session()
        topstepx.BASE_URL = "https://api.topstepx.com/api"
        
        topstepx.authenticate()
        print("   ✅ TopstepX認証成功")
    except Exception as e:
        print(f"\n❌ TopstepX認証エラー: {e}")
        return 1
    
    # Notionクライアントを初期化
    print("\n🔐 Notion接続中...")
    try:
        notion = NotionRoundtripClient(
            api_key=notion_creds["api_key"],
            database_id=notion_creds["database_id"]
        )
        db_info = notion.get_database()
        db_title = db_info.get('title', [{}])[0].get('plain_text', 'Database')
        print(f"   ✅ Notion接続成功: {db_title}")
    except Exception as e:
        print(f"\n❌ Notion接続エラー: {e}")
        print("\n💡 データベースのスキーマを確認してください:")
        print("   python notion_client.py  # スキーマを表示")
        return 1
    
    # アカウント一覧を取得
    print("\n📋 アカウント一覧を取得中...")
    try:
        accounts = topstepx.get_accounts()
        print(f"   {len(accounts)} 個のアカウントが見つかりました")
        
        if not accounts:
            print("\n⚠️ アカウントが見つかりません")
            return 1
        
        account = select_account_interactive(accounts)
        account_id = account.get('id')
        account_name = account.get('name')
        print(f"\n📌 選択: {account_name} (ID: {account_id})")
        
    except Exception as e:
        print(f"\n❌ アカウント取得エラー: {e}")
        return 1
    
    # 期間を選択
    days = select_period_interactive()
    print(f"\n   過去 {days} 日間のトレードを取得します")

    # LIVE口座かどうかを判定
    use_order_api = is_live_account(account_name)

    # トレードを取得
    print("\n📊 トレード履歴を取得中...")
    if use_order_api:
        print("   🔄 LIVE口座検出: Order/search APIを使用")

    try:
        end_date = datetime.now(timezone.utc)
        start_date = end_date - timedelta(days=days)

        if use_order_api:
            # LIVE口座: Order/searchを使用
            orders = topstepx.get_order_history(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date
            )
            print(f"   {len(orders)} 件の約定済みオーダーを取得しました")

            if not orders:
                print("\n⚠️ オーダーがありません")
                return 0

            # Order形式をTrade形式に変換
            trades = convert_orders_to_trades(orders)
            print(f"   {len(trades)} 件の片道トレードに変換しました")
        else:
            # その他の口座: Trade/searchを使用
            trades = topstepx.get_trades(
                account_id=account_id,
                start_date=start_date,
                end_date=end_date
            )
            print(f"   {len(trades)} 件の片道トレードを取得しました")

        if not trades:
            print("\n⚠️ トレードがありません")
            return 0

    except Exception as e:
        print(f"\n❌ トレード取得エラー: {e}")
        return 1
    
    # 往復トレードに変換
    print("\n🔄 往復トレードに変換中...")
    try:
        transformer = RoundtripTransformer()
        roundtrips = transformer.transform(trades)
        stats = transformer.get_statistics()
        
        print(f"   {len(roundtrips)} 件の往復トレードに変換しました")
        
        if not roundtrips:
            print("\n⚠️ 往復トレードがありません（全てオープンポジション？）")
            if transformer.open_positions:
                print(f"   オープンポジション: {len(transformer.open_positions)} 件")
            return 0
        
        # 統計を表示
        print("\n【変換結果】")
        print(f"   勝率: {stats.get('win_rate', 0)}%")
        print(f"   純損益: ${stats.get('total_net_pnl', 0):,.2f}")
        print(f"   プロフィットファクター: {stats.get('profit_factor', 0)}")
        
    except Exception as e:
        print(f"\n❌ 変換エラー: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    # Notionに同期
    print("\n📤 Notionに同期中...")
    try:
        sync_stats = notion.sync_roundtrips(
            roundtrips=roundtrips,
            account_name=account_name,
            skip_existing=True
        )
        
        print(f"\n✅ 同期完了!")
        print(f"   作成: {sync_stats['created']} 件")
        print(f"   スキップ（既存）: {sync_stats['skipped']} 件")
        if sync_stats['errors'] > 0:
            print(f"   エラー: {sync_stats['errors']} 件")
        
    except Exception as e:
        print(f"\n❌ 同期エラー: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    print("\n" + "=" * 60)
    print("完了!")
    print("=" * 60)
    return 0


def main():
    parser = argparse.ArgumentParser(
        description='TopstepX → Notion 同期スクリプト（往復トレード版）',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
使用例:
  対話モード:
    python sync_to_notion.py
  
  自動モード（デフォルト: 最新のライブアカウント、30日間）:
    python sync_to_notion.py --auto
  
  特定のアカウントID:
    python sync_to_notion.py --auto --account 12345678
  
  アカウント名で検索:
    python sync_to_notion.py --auto --account-name "50KTC"
  
  アカウントタイプで指定:
    python sync_to_notion.py --auto --account-type live
    python sync_to_notion.py --auto --account-type express
    python sync_to_notion.py --auto --account-type combine
    python sync_to_notion.py --auto --account-type practice
  
  全アカウント同期:
    python sync_to_notion.py --auto --all-accounts
  
  期間指定:
    python sync_to_notion.py --auto --days 7
    python sync_to_notion.py --auto --days 90
  
  cron用（出力抑制）:
    python sync_to_notion.py --auto --quiet
        """
    )
    
    parser.add_argument(
        '--auto', 
        action='store_true',
        help='自動モードで実行（対話なし）'
    )
    
    parser.add_argument(
        '--account', '-a',
        type=str,
        help='アカウントID または アカウント名'
    )
    
    parser.add_argument(
        '--account-name', '-n',
        type=str,
        help='アカウント名（部分一致）で検索'
    )
    
    parser.add_argument(
        '--account-type', '-t',
        type=str,
        choices=['live', 'express', 'combine', 'practice', 'all'],
        help='アカウントタイプで指定'
    )
    
    parser.add_argument(
        '--all-accounts',
        action='store_true',
        help='全アカウントを同期'
    )
    
    parser.add_argument(
        '--days', '-d',
        type=int,
        default=30,
        help='同期する期間（日数）、デフォルト: 30'
    )
    
    parser.add_argument(
        '--quiet', '-q',
        action='store_true',
        help='出力を抑制（エラーのみ表示）'
    )
    
    args = parser.parse_args()
    
    if args.auto:
        logger = Logger(quiet=args.quiet)
        exit_code = run_auto_mode(args, logger)
        sys.exit(exit_code)
    else:
        exit_code = run_interactive_mode()
        sys.exit(exit_code)


if __name__ == "__main__":
    main()