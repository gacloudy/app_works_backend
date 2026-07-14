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
| DB接続（本番） | Secret Manager の `DATABASE_URL` + psycopg2 |
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
.venv\Scripts\python batch\sync_stock_master.py       # JPX から上場銘柄を同期
.venv\Scripts\python batch\sync_delisted_prices.py    # 上場廃止銘柄の stock_price フラグを更新
.venv\Scripts\python batch\fetch_stock_prices.py      # 全銘柄の株価を取得・登録
.venv\Scripts\python batch\calc_technical.py          # テクニカル指標を計算
.venv\Scripts\python batch\detect_signals.py          # シグナルを検出・記録
.venv\Scripts\python batch\update_signal_results.py   # シグナル後のリターンを更新
.venv\Scripts\python batch\aggregate_stats.py         # 統計サマリーを集計（週1回推奨）
.venv\Scripts\python batch\sync_holidays.py           # 内閣府CSVから祝日を同期（月1回推奨）
```

各バッチは前段の出力に依存するため、上記の順序を守って実行する（詳細は次節）。

---

## 各バッチの役割

### 1. `sync_stock_master.py` — 銘柄マスタ同期

JPX（日本取引所）の上場銘柄一覧ページから `data_j.xls` の URL を取得してダウンロードし、**プライム（内国株式）** 市場の銘柄のみを抽出して `stock_master` に反映する。

- Excel に載っている銘柄 → 新規なら `INSERT`、既存なら名称・業種・市場区分を `UPDATE`。過去に上場廃止（`isDelisted=true`）だった銘柄が再掲載されていれば「復活」として `isDelisted=false` に戻す。
- Excel に載っていない既存銘柄 → `isDelisted=true` に更新（上場廃止扱い）。
- 後続の全バッチが参照する銘柄一覧の起点となるため、最初に実行する必要がある。

### 2. `sync_delisted_prices.py` — 上場廃止フラグの反映

`stock_master.isDelisted=true` の銘柄コードを集め、対応する `stock_price` レコードの `is_delisted` を一括で `true` に更新する。`sync_stock_master.py` が銘柄の上場廃止を検出した直後に実行し、株価データ側のフラグを追従させる。

### 3. `fetch_stock_prices.py` — 株価取得

`stock_master` の全銘柄について、当日の株価（始値・高値・安値・前日終値・出来高・現在値）を取得し `stock_price` に upsert する。

- 取得元は **野村證券のページを一次**、失敗時は **Yahoo Finance Japan に二次フォールバック**。
- 土日および `holiday_master` に登録された祝日は取得自体をスキップする。
- ページ上の日付が「本日」と一致しない場合や現在値が取得できない場合は登録せず、理由とともに `batch_fetch_log` に記録する（銘柄ごとに `skip` / `error`）。
- 1銘柄ごとに `FETCH_DELAY`（2秒）のウェイトを挟み、サイトへの負荷を抑える。

### 4. `calc_technical.py` — テクニカル指標計算

`stock_price` の終値（`current_price`）と出来高から、銘柄ごとに以下を計算し `technical_indicators` に保存する。

- 移動平均（MA5 / MA25 / MA75）
- MACD（EMA12 − EMA26）・シグナル線（EMA9）・ヒストグラム
- RSI（14日）
- ボリンジャーバンド（20日, ±2σ）
- 出来高20日移動平均・出来高比率

前回計算済みの最終日から `WARMUP_DAYS`（150日）分さかのぼって取得し、MA75 などの計算に必要な助走期間を確保したうえで差分のみ計算・保存する。

### 5. `detect_signals.py` — シグナル検出

`technical_indicators` の前日・当日を比較し、以下7種の売買シグナルを検出して `signal_history` に記録する（`price_at_signal` も同時に記録）。

| シグナル | 条件 |
|---|---|
| `golden_cross` | MA5 が MA25 を上抜け |
| `dead_cross` | MA5 が MA25 を下抜け |
| `rsi_oversold` | RSI14 が 30 以下に突入 |
| `rsi_overbought` | RSI14 が 70 以上に突入 |
| `bb_lower_touch` | 株価がボリンジャー下限に接触 |
| `bb_upper_touch` | 株価がボリンジャー上限に接触 |
| `volume_surge_up` | 出来高が20日平均の2倍超 かつ 上昇 |

前回検出済みの最終シグナル日以降のみを処理し、重複は `(code, signal_date, signal_type)` の一意制約で無視される。

### 6. `update_signal_results.py` — シグナル後のリターン更新

`signal_history` のうち `return_3d` / `return_5d` / `return_10d` / `return_20d` が未確定（NULL）のレコードについて、シグナル発生日から N 取引日後の `stock_price` を参照し、`(N日後の株価 - シグナル時株価) / シグナル時株価 × 100` でリターンを計算・更新する。まだ N 取引日分のデータが蓄積していないシグナルは、その周のみ更新をスキップする。

### 7. `aggregate_stats.py` — 統計サマリー集計

`signal_history` に蓄積されたリターン実績を、シグナル種別 × 業種 × 集計期間（3/5/10/20日）ごとに集計し、勝率・平均リターン・中央値・標準偏差を `signal_stats` に保存する。全業種合計は `industry=""` として別途保存。サンプル数が `MIN_SAMPLES`（10件）未満の組み合わせは信頼性が低いため除外する。日々の増分は小さいため週1回の実行で十分。

### 8. `sync_holidays.py` — 祝日マスタ同期

内閣府が公開する祝日CSVをダウンロードし、`holiday_master` に upsert する。`fetch_stock_prices.py` が祝日をスキップする際に参照する。年1回程度しか更新されないため、月1回の実行で十分。

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
│   ├── database.py           # DB接続（GCP_PROJECT_ID の有無で Secret Manager / .env を自動切替）
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
│   ├── sync_stock_master.py       # 銘柄マスタ同期
│   ├── sync_delisted_prices.py    # 上場廃止フラグ更新
│   ├── fetch_stock_prices.py      # 株価取得
│   ├── calc_technical.py          # テクニカル指標計算
│   ├── detect_signals.py          # シグナル検出
│   ├── update_signal_results.py   # リターン更新
│   ├── aggregate_stats.py         # 統計集計
│   └── sync_holidays.py           # 祝日同期
├── alembic/                  # マイグレーション管理
├── .env                      # 接続情報（Git管理外）
└── requirements.txt
```

---

## 検討中の機能（未実装・メモ）

### 個別銘柄チャット応答（`02_03_selected.txt`）に含めるべき情報

ユーザーが特定銘柄について質問した際（`category="Selected"`）の回答に含めたい情報として、以下4項目を検討した。現状のDB設計での実現可否は以下の通り。

| 項目 | 実現可否 | 根拠 |
|---|---|---|
| ①業界 | ○ 即対応可 | `stock_master.industry` |
| ②株価の値動き | ○ 対応可 | `stock_price`（日次OHLC・出来高・現在値の履歴）、`technical_indicators`（MA5/25/75・MACD・RSI14・ボリンジャーバンド・出来高比率） |
| ③買い時・売り時 | △ 部分的に対応可 | `technical_indicators`（現在のシグナル状態）＋ `signal_history`（この銘柄固有の過去シグナル実績）＋ `signal_stats`（シグナル種別×業種×期間の勝率・平均/中央値リターン）を組み合わせれば、**統計的根拠つきの参考情報**は出せる。ただし断定的な投資助言（「今買うべき」）にはせず、「過去の統計参考値」という体裁に留めるべき |
| ④株価に影響を与えそうな情報（材料） | × 現状は対応不可 | ニュース・決算カレンダー・アナリストレーティング等のテーブルが存在しない。`kb_chunk` はアプリ自体の使い方・シグナル定義用のRAGであり無関係。④に類する質問には「その情報は今のところ持っていません」と正直に案内する方針 |

追加提案:
- ③を出す場合は「あくまで過去データの参考値であり、投資判断は自己責任で」という免責の一文を末尾に添える
- ②は「直近5営業日の騰落率」「25日移動平均線からの乖離率」など定量化すると説得力が増す

### 個別銘柄ニュースRAGの検討（④の実現案）

「特定銘柄に影響を与えそうな情報を日次バッチで収集し、RAGとして蓄積する」案を検討した。技術的には可能だが、既存の `kb_chunk`（静的・小規模な用語集RAG、全件ブルートフォース類似度検索）とは前提が異なる設計になる。

**アーキテクチャ案**
- 新テーブル `news_chunk`（`trader_schema`）: `id, code, title, content, content_hash, embedding, source, published_at, fetched_at, created_at`
- 検索時は `WHERE code = '9984'` のように**銘柄コードで先に絞り込んでから**コサイン類似度計算（`kb_chunk` のような全件ブルートフォースは銘柄横断では成立しない）
- キャッシュの置き場所は**バックエンドDB（Postgres）**。`selected_stock`（フロントエンド・ブラウザ単位・非共有の会話状態）とは異なり、ニュースは客観的事実で全ユーザー共通のため、DBに銘柄コード単位でユーザー横断・共有キャッシュとして持たせるのが自然
- 情報源は一般ニュースサイトのスクレイピングだと著作権・利用規約の懸念があるため、**TDnet（東証適時開示情報閲覧サービス）** が無料・公式・銘柄コード紐付き済みで相性が良い（ただし「なぜ株価が動いたか」の解説性は一般ニュースより弱く、④のカバー範囲は限定的）

**トークンコストの内訳（要注意ポイント）**
- チャット回答生成時のコストは**ほぼ増えない**: RAGはtop-k（例: 上位3件）だけを取得してプロンプトに入れる方式のため、蓄積量が増えても1回の質問応答で使うトークン数は一定
- コストが跳ねるのは**バッチ取り込み側**: 生ニュースは長文・ノイズが多いため、Claudeで要点抽出・要約してから埋め込む設計にしたくなるが、この要約ステップが「銘柄数×記事数×日次」で効いてくる。現在アクティブな銘柄数は**1,559件**（`stock_master`, `isDelisted=false`）。全銘柄を毎日ブランケットで回すと、誰も質問しない銘柄の分もコストを払い続けることになる

**その他のリスク**
- 鮮度管理: `kb_chunk` は「内容が変わったら更新」の静的な冪等設計（content_hash）だが、ニュースは「時間が経ったら陳腐化する」ため保持期間（例: 直近30日のみ）を切る失効ロジックが別途必要
- 要約段階でのハルシネーション: LLMに要約させてから格納すると、要約時点の誤りがそのまま「事実」としてグラウンディングされるリスクがある
- 投資助言色: ④は「材料の要約」であり「推奨」ではない、という一線をプロンプト側で明確に引く必要がある（③の統計参考値と同様の方針）

**コストを抑える代替案**: 全銘柄を毎日バッチで回すのではなく、**「実際にユーザーが選択した銘柄だけ、初回質問時にオンデマンド取得してTTL付きでキャッシュ」**する方式なら、コストは「実際に会話で使われた銘柄数」に比例するだけで済み、現実的。既存の `selected_stock` キャッシュ機構と相性が良い。
