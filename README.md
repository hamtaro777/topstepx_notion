# TopstepX → Notion 往復トレード連携

TopstepXからトレードデータを取得し、往復トレード形式に変換してNotionに登録するアプリケーション

## 📋 目次

- [概要](#概要)
- [セットアップ](#セットアップ)
- [Notionデータベースの作成](#notionデータベースの作成)
- [使い方](#使い方)
- [ファイル構成](#ファイル構成)

## 概要

このプロジェクトは以下の機能を提供します：

1. ✅ TopstepX APIからトレードデータを取得
2. ✅ 片道トレード → 往復トレードに変換
3. ✅ Notionデータベースに自動登録

### 往復トレード変換について

TopstepX APIは片道（ハーフターン）形式でトレードを返します：
- エントリー: `profitAndLoss = null`
- エグジット: `profitAndLoss = 値`

本ツールはこれをFIFOでマッチングし、往復トレード（ラウンドトリップ）に変換します。

## セットアップ

### 1. 依存パッケージのインストール

```bash
pip install requests
```

### 2. 認証情報の設定

`credentials.json` を作成：

```json
{
    "topstepx": {
        "username": "あなたのTopstepXユーザー名",
        "api_key": "あなたのAPIキー"
    },
    "notion": {
        "api_key": "あなたのNotion Integration Token",
        "database_id": "あなたのNotionデータベースID"
    }
}
```

### 3. TopstepX APIキーの取得

1. [ProjectX Dashboard](https://dashboard.projectx.com) にログイン
2. 「Subscriptions」→「ProjectX API Access」を購読
3. 「Settings」→「API」でAPIキーを生成

### 4. Notion Integrationの作成

1. [Notion Integrations](https://www.notion.so/my-integrations) にアクセス
2. 「New integration」をクリック
3. 名前を入力し、ワークスペースを選択
4. 「Submit」→ Internal Integration Token をコピー

## Notionデータベースの作成

### 推奨スキーマ

以下のプロパティを持つデータベースを作成してください：

| プロパティ名     | タイプ   | 説明                           |
|-----------------|---------|-------------------------------|
| Name            | Title   | 自動生成ID (MMDD_MNQ_LONG_WIN) |
| Account         | Select  | アカウント名                    |
| Contract        | Select  | MNQ, MES, MGC, etc.           |
| Direction       | Select  | LONG / SHORT                  |
| Size            | Number  | 枚数                           |
| Entry Time      | Date    | エントリー日時                  |
| Exit Time       | Date    | エグジット日時                  |
| Entry Price     | Number  | エントリー価格                  |
| Exit Price      | Number  | エグジット価格                  |
| P&L             | Number  | 損益（手数料前）                |
| Net P&L         | Number  | 純損益（手数料後）              |
| Total Fees      | Number  | 合計手数料                     |
| Points          | Number  | 獲得ポイント                   |
| Duration        | Text    | 保持時間 (10分24秒)            |
| Result          | Select  | WIN / LOSS / BE               |
| Entry Trade ID  | Number  | エントリーのTrade ID           |
| Exit Trade ID   | Number  | エグジットのTrade ID           |

### Selectオプションの設定

**Contract:**
- MNQ, MES, NQ, ES, MGC, MCL, GC, CL, M2K, MYM, Other

**Direction:**
- LONG, SHORT

**Result:**
- WIN (緑), LOSS (赤), BE (グレー)

### データベースIDの取得

1. Notionでデータベースを開く
2. URLをコピー: `https://www.notion.so/xxxxx?v=yyyyy`
3. `xxxxx` 部分がデータベースID

### Integrationの接続

1. データベースを開く
2. 右上の「...」→「Connections」
3. 作成したIntegrationを追加

## 使い方

### 基本的な同期

```bash
python sync_to_notion.py
```

実行すると：
1. TopstepXに認証
2. アカウントを選択
3. 期間を選択（7/30/90日）
4. トレードを取得
5. 往復トレードに変換
6. Notionに同期

### トレードデータのみ取得

```bash
python fetch_trades.py
```

### 往復トレード変換のみ

```bash
python roundtrip_transformer.py trade_data_raw.json
```

## ファイル構成

```
topstepx_notion/
├── credentials.json          # 認証情報（要作成）
├── topstepx_client.py        # TopstepX APIクライアント
├── notion_client.py          # Notion APIクライアント（往復トレード用）
├── roundtrip_transformer.py  # 片道→往復変換モジュール
├── sync_to_notion.py         # メイン同期スクリプト
├── fetch_trades.py           # トレード取得スクリプト
├── trade_data_raw.json       # 取得した生データ
└── README.md
```

## データ形式

### 入力（TopstepX API）

```json
{
    "id": 1721758654,
    "contractId": "CON.F.US.MNQ.Z25",
    "side": 0,  // 0=BUY, 1=SELL
    "size": 1,
    "price": 25576.0,
    "profitAndLoss": null,  // null=エントリー
    "fees": 0.37
}
```

### 出力（往復トレード）

```json
{
    "roundtrip_id": 1,
    "contract": "MNQ",
    "direction": "LONG",
    "size": 1,
    "entry": {
        "trade_id": 1721706442,
        "timestamp": "2025-12-02T18:02:05+00:00",
        "price": 25532.0,
        "side": "BUY",
        "fees": 0.37
    },
    "exit": {
        "trade_id": 1721758654,
        "timestamp": "2025-12-02T18:07:08+00:00",
        "price": 25576.0,
        "side": "SELL",
        "fees": 0.37
    },
    "pnl": 88.0,
    "net_pnl": 87.26,
    "points": 44.0,
    "duration_formatted": "5分3秒"
}
```

## 統計情報

変換時に以下の統計が計算されます：

- 総トレード数
- 勝率（WIN / LOSS / BE）
- 総損益 / 純損益
- プロフィットファクター
- 平均利益 / 平均損失
- 最大利益 / 最大損失
- 平均保持時間
- 契約別・方向別の集計

## セキュリティ注意事項

⚠️ **重要**: 
- `credentials.json` は絶対にGitにコミットしないでください
- APIキーは定期的にローテーションしてください

## ライセンス

MIT License