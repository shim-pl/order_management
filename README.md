# アンビテック TLC向け受注管理

射出成形製品の受注管理Webアプリ（社内LAN用）

## 機能

- 受注の登録・編集・削除
- 納品スケジュール（回答納期）管理
- 納品実績の記録
- 変更履歴の自動記録
- 製品マスタ・色材マスタ管理（CSV一括インポート対応）
- CSVエクスポート（フィルター機能付き）
- ログイン認証（Flask-Login）

## 起動方法

```bash
# 依存ライブラリのインストール
pip install -r requirements.txt

# サーバー起動
python app.py
```

起動後、ブラウザで `http://localhost:5000` にアクセスしてください。

### 初期ログイン情報

| 項目 | 値 |
|------|-----|
| ユーザー名 | admin |
| パスワード | changeme123 |

ログイン後、マスタ管理画面からパスワードを変更してください。

### 環境変数（任意）

`.env` ファイルを作成することで初期管理者アカウントを変更できます。

```
INITIAL_ADMIN_USERNAME=your_username
INITIAL_ADMIN_PASSWORD=your_password
```

## 技術スタック

- Python / Flask
- SQLite
- HTML / CSS / JavaScript（バニラ）
