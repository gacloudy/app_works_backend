# app_works_backend

FastAPI + PostgreSQL による株価データ収集・分析バックエンド。

---

## 技術スタック

| 項目 | 内容 |
|------|------|
| フレームワーク | FastAPI + Uvicorn |
| DB | PostgreSQL（スキーマ: `trader_schema`） |
| ORM | SQLAlchemy 2.0 |
| マイグレーション | Alembic |
| デプロイ | Google Cloud Run |
| DB接続（本番） | Cloud SQL Connector (pg8000) |
| DB接続（ローカル） | psycopg2 + .env |

---

## 起動方法

```bash
cd app_works_backend
.venv\Scripts\python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

---

## バッチ実行順序（毎日）

```bash
# cd app_works_backend で実行
.venv\Scripts\python batch\00_sync_stock_master.py      # JPX から上場銘柄を同期
.venv\Scripts\python batch\01_sync_delisted_prices.py   # 上場廃止銘柄の stock_price フラグを更新
.venv\Scripts\python batch\02_fetch_stock_prices.py     # 全銘柄の株価を取得・登録
.venv\Scripts\python batch\03_calc_technical.py         # テクニカル指標を計算
.venv\Scripts\python batch\04_detect_signals.py         # シグナルを検出・記録
.venv\Scripts\python batch\05_update_signal_results.py  # シグナル後のリターンを更新
.venv\Scripts\python batch\06_aggregate_stats.py        # 統計サマリーを集計（週1回推奨）
.venv\Scripts\python batch\07_sync_holidays.py          # 内閣府CSVから祝日を同期（月1回推奨）
```

---

## テーブル定義

### `stock_master` — 銘柄マスタ

JPX 上場銘柄（プライム市場）の基本情報。

| カラム | 型 | 説明 |
|-------|----|------|
| id | INTEGER PK | 自動採番 |
| code | VARCHAR(10) UNIQUE | 証券コード（例: "7203"） |
| name | VARCHAR(200) | 銘柄名（例: "トヨタ自動車"） |
| industry | VARCHAR(100) | 33業種区分（例: "輸送用機器"） |
| market | VARCHAR(50) | 市場区分（例: "プライム（内国株式）"） |
| isDelisted | BOOLEAN | 上場廃止フラグ（true = 廃止済み） |
| createdAt | TIMESTAMP | 登録日時 |
| updatedAt | TIMESTAMP | 更新日時 |

---

### `stock_price` — 株価データ

銘柄ごとの日次株価。取得元は野村證券（一次）/ Yahoo Finance Japan（二次）。

| カラム | 型 | 説明 |
|-------|----|------|
| id | INTEGER PK | 自動採番 |
| code | VARCHAR(10) | 証券コード |
| trade_date | DATE | 取引日 |
| open_price | NUMERIC(12,1) | 始値 |
| high_price | NUMERIC(12,1) | 高値 |
| low_price | NUMERIC(12,1) | 安値 |
| prev_close | NUMERIC(12,1) | 前日終値 |
| volume | BIGINT | 出来高（株数） |
| current_price | NUMERIC(12,1) | 現在値（終値相当） |
| source | VARCHAR(20) | 取得元（"nomura" / "yahoo"） |
| is_delisted | BOOLEAN | 上場廃止フラグ |
| created_at | TIMESTAMP | 登録日時 |
| updated_at | TIMESTAMP | 更新日時 |

---

### `batch_fetch_log` — 株価取得ログ

`fetch_stock_prices` バッチでスキップ・エラーになった銘柄の記録。

| カラム | 型 | 説明 |
|-------|----|------|
| id | INTEGER PK | 自動採番 |
| run_id | VARCHAR(20) | バッチ実行ID（"YYYYMMDD_HHMMSS"） |
| code | VARCHAR(10) | 証券コード |
| status | VARCHAR(10) | 結果（"skip" / "error"） |
| reason | VARCHAR(100) | スキップ・エラーの理由 |
| source | VARCHAR(20) | 取得元（"nomura" / "yahoo" / NULL） |
| created_at | TIMESTAMP | 登録日時 |

---

### `holiday_master` — 祝日マスタ

内閣府公開CSVから取得した日本の祝日一覧。`fetch_stock_prices` が祝日をスキップするために参照する。

| カラム | 型 | 説明 |
|-------|----|------|
| date | DATE PK | 祝日の日付 |
| name | VARCHAR(50) | 祝日名（例: "元日"） |
| created_at | TIMESTAMP | 登録日時 |

---

### `technical_indicators` — テクニカル指標

`calc_technical` バッチが毎日計算する各銘柄のテクニカル指標。

| カラム | 型 | 説明 |
|-------|----|------|
| id | INTEGER PK | 自動採番 |
| code | VARCHAR(10) | 証券コード |
| trade_date | DATE | 計算基準日 |
| ma5 | NUMERIC(12,2) | 5日移動平均 |
| ma25 | NUMERIC(12,2) | 25日移動平均 |
| ma75 | NUMERIC(12,2) | 75日移動平均 |
| macd | NUMERIC(12,4) | MACD値（EMA12 − EMA26） |
| macd_signal | NUMERIC(12,4) | MACDシグナル線（EMA9） |
| macd_hist | NUMERIC(12,4) | MACDヒストグラム（MACD − Signal） |
| rsi14 | NUMERIC(6,2) | RSI（14日） |
| bb_upper | NUMERIC(12,2) | ボリンジャーバンド 上限（+2σ） |
| bb_middle | NUMERIC(12,2) | ボリンジャーバンド 中心（MA20） |
| bb_lower | NUMERIC(12,2) | ボリンジャーバンド 下限（−2σ） |
| volume_ma20 | NUMERIC(20,2) | 出来高 20日移動平均 |
| volume_ratio | NUMERIC(8,4) | 出来高比率（当日 ÷ volume_ma20） |
| created_at | TIMESTAMP | 登録日時 |

**ユニーク制約**: `(code, trade_date)`

---

### `signal_history` — シグナル履歴

`detect_signals` バッチが検出した売買シグナルと、その後のリターン実績。

| カラム | 型 | 説明 |
|-------|----|------|
| id | INTEGER PK | 自動採番 |
| code | VARCHAR(10) | 証券コード |
| signal_date | DATE | シグナル発生日 |
| signal_type | VARCHAR(50) | シグナル種別（下表参照） |
| detail | TEXT | 補足情報（JSON文字列） |
| price_at_signal | NUMERIC(12,1) | シグナル発生時の株価 |
| return_3d | NUMERIC(8,4) | 3取引日後のリターン（%） |
| return_5d | NUMERIC(8,4) | 5取引日後のリターン（%） |
| return_10d | NUMERIC(8,4) | 10取引日後のリターン（%） |
| return_20d | NUMERIC(8,4) | 20取引日後のリターン（%） |
| created_at | TIMESTAMP | 登録日時 |

**ユニーク制約**: `(code, signal_date, signal_type)`

**signal_type 一覧**:

| 値 | 意味 |
|----|------|
| `golden_cross` | MA5 が MA25 を上抜け（買いシグナル） |
| `dead_cross` | MA5 が MA25 を下抜け（売りシグナル） |
| `rsi_oversold` | RSI14 が 30 以下に突入（売られすぎ） |
| `rsi_overbought` | RSI14 が 70 以上に突入（買われすぎ） |
| `bb_lower_touch` | 株価がボリンジャー下限に触れた |
| `bb_upper_touch` | 株価がボリンジャー上限に触れた |
| `volume_surge_up` | 出来高が20日平均の2倍超 かつ 上昇 |

---

### `signal_stats` — シグナル統計サマリー

`aggregate_stats` バッチが集計するシグナル別・業種別の勝率・リターン統計。AIチャット機能が参照する。

| カラム | 型 | 説明 |
|-------|----|------|
| id | INTEGER PK | 自動採番 |
| signal_type | VARCHAR(50) | シグナル種別 |
| industry | VARCHAR(100) | 業種（""= 全業種合計） |
| period | INTEGER | 集計期間（3 / 5 / 10 / 20 日） |
| sample_count | INTEGER | サンプル数 |
| win_rate | NUMERIC(6,2) | 勝率（%）|
| avg_return | NUMERIC(8,4) | 平均リターン（%） |
| median_return | NUMERIC(8,4) | 中央値リターン（%） |
| std_return | NUMERIC(8,4) | 標準偏差（%） |
| updated_at | TIMESTAMP | 最終更新日時 |

**ユニーク制約**: `(signal_type, industry, period)`

---

## ディレクトリ構成

```
app_works_backend/
├── app/
│   ├── main.py               # FastAPI エントリポイント
│   ├── database.py           # DB接続（Cloud SQL Connector / psycopg2 自動切替）
│   ├── models/
│   │   ├── stock_master.py
│   │   ├── stock_price.py
│   │   ├── batch_fetch_log.py
│   │   ├── holiday_master.py
│   │   ├── technical_indicator.py
│   │   ├── signal_history.py
│   │   └── signal_stats.py
│   └── routers/              # APIエンドポイント
├── batch/
│   ├── 00_sync_stock_master.py      # 銘柄マスタ同期
│   ├── 01_sync_delisted_prices.py   # 上場廃止フラグ更新
│   ├── 02_fetch_stock_prices.py     # 株価取得
│   ├── 03_calc_technical.py         # テクニカル指標計算
│   ├── 04_detect_signals.py         # シグナル検出
│   ├── 05_update_signal_results.py  # リターン更新
│   ├── 06_aggregate_stats.py        # 統計集計
│   └── 07_sync_holidays.py          # 祝日同期
├── alembic/                  # マイグレーション管理
├── .env                      # 接続情報（Git管理外）
└── requirements.txt
```
