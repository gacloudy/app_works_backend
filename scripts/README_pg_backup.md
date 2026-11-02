# PostgreSQL 日次バックアップ（pg_backup.sh）

CentOS移行後、GCPのマネージドバックアップが使えなくなったため、
`pg_dump` + cron による自前のテーブルデータバックアップに置き換える。

対象: `trader` DB のテーブルデータのみ（`--data-only`、スキーマは含めない）。
保持期間: 直近7日分をローカルディスクにローテーション保存。

## セットアップ手順

### 1. スクリプト配置

パスワードを平文で埋め込んでいるため、配置後に必ず権限を絞る。

```bash
scp app_works_backend/scripts/pg_backup.sh centos-host:/usr/local/bin/pg_backup.sh
chmod 700 /usr/local/bin/pg_backup.sh
chown <実行ユーザー>:<実行ユーザー> /usr/local/bin/pg_backup.sh
```

> **注意**: このスクリプトはDBパスワード（`idcjapan99`）を直書きしています。
> - Gitには絶対にコミットしない（`app_works_backend/.gitignore` に `scripts/pg_backup.sh` を追加済み）
> - サーバー上でも所有者以外読めないパーミッションを維持する

### 2. バックアップ用ディレクトリ作成

```bash
sudo mkdir -p /backup/pg
sudo chown <実行ユーザー>:<実行ユーザー> /backup/pg
```

DBデータと同じディスク/パーティションに置かない（ディスク逼迫時の共倒れを防ぐため）。

### 3. 動作確認（手動実行）

```bash
/usr/local/bin/pg_backup.sh
ls -lh /backup/pg
```

`trader_data_YYYY-MM-DD_HHMMSS.dump` が生成されていればOK。

### 4. cron登録

実行ユーザーの `crontab -e`:

```
0 2 * * * /usr/local/bin/pg_backup.sh >> /var/log/pg_backup.log 2>&1
```

毎日AM2時に実行し、ログを `/var/log/pg_backup.log` に出力。

## 設定の上書き（環境変数）

| 変数 | デフォルト | 用途 |
|---|---|---|
| `PGBACKUP_DB_NAME` | `trader` | 対象DB名 |
| `PGBACKUP_DB_USER` | `trader_user` | 接続ユーザー |
| `PGBACKUP_DB_HOST` | `localhost` | 接続ホスト |
| `PGBACKUP_DB_PORT` | `5432` | 接続ポート |
| `PGBACKUP_DB_PASSWORD` | `idcjapan99` | 接続パスワード（スクリプト内に直書き） |
| `PGBACKUP_DIR` | `/backup/pg` | バックアップ保存先 |
| `PGBACKUP_RETENTION_DAYS` | `7` | ローカル保持日数 |

cron行での上書き例:

```
0 2 * * * PGBACKUP_DIR=/mnt/backup/pg PGBACKUP_RETENTION_DAYS=7 /usr/local/bin/pg_backup.sh >> /var/log/pg_backup.log 2>&1
```

## リストア確認（月1回程度推奨）

バックアップが壊れていないかの検証:

```bash
pg_restore --list /backup/pg/trader_data_2026-07-15_020000.dump
```

試験用DBへの実リストア:

```bash
pg_restore --data-only -h localhost -U trader_user -d <試験用DB> /backup/pg/trader_data_2026-07-15_020000.dump
```

## 動作の仕組み（pg_backup.sh）

- `flock` で多重実行を防止（前回の実行が長引いても二重にダンプが走らない）
- `pg_dump` が失敗、またはダンプファイルが空の場合は7日削除処理をスキップして異常終了（`exit 1`）
  - 古いバックアップを守るため、当日分の取得に失敗しても既存のバックアップは消さない
- 削除は当日分の取得が成功した後にのみ実行される

## 今後の検討事項

- 失敗時にSlack通知やメール通知（`crontab` の `MAILTO=`）を入れるか
- ローカルディスク以外への保管（別サーバー/NASなど）を追加するか
