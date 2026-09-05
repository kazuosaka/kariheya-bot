# 仮部屋（kariheya-bot）

Discord で一時的なボイスチャンネルと、同じ名前のテキストチャンネルを自動作成するボットです。

人数制限ごとの「＋ 仮部屋を作る」ボイスに入ると部屋ができ、全員が退出するとボイスとテキストの両方が削除されます。1人1部屋です。

## 必要なもの

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Windows / Mac）
- Discord のボットトークン（[Discord Developer Portal](https://discord.com/developers/applications)）

## セットアップ

### 1. このリポジトリを入手する

GitHub の **Code → Download ZIP** でダウンロードして展開するか:

```
git clone https://github.com/kazuosaka/kariheya-bot.git
cd kariheya-bot
```

### 2. Discord ボットを作る

1. [Discord Developer Portal](https://discord.com/developers/applications) で New Application
2. Bot からボットを追加し、トークンをコピーする
3. Privileged Gateway Intents は、いまのところ追加不要です（デフォルトの Intents）
4. OAuth2 → URL Generator で `bot` と `applications.commands` を選び、権限は少なくとも次を付ける
   - チャンネルの管理
   - ロールの管理
   - メッセージを送信
   - チャンネルを見る
   - 接続
   - メンバーを移動
5. 生成した URL でサーバーへ招待する
6. サーバーのロール一覧で、ボットのロールを一般メンバーより上にする

### 3. 設定ファイルを置く

```
copy .env.example .env
```

`.env` を開き、`DISCORD_TOKEN=` の右にトークンを貼ります。

`GUILD_ID` は任意です。入れるとスラッシュコマンドがそのサーバーへすぐ同期されます。空のままだと、反映に数分かかることがあります。

`.env` は **絶対に GitHub へ上げないでください。**

### 4. 起動する

```
docker compose up --build -d
docker compose logs --tail 30
```

`logged in as ...` が出れば起動できています。

### 5. サーバー側の設定

ボットに「チャンネルの管理」があるアカウントで、次を実行します。

1. `/setup category` … 一時部屋を作るカテゴリ
2. `/setup role` … 部屋を作れるロールを追加
3. `/setup hubs` … 初期の作成専用ボイスを用意（まだ無いときだけ作る）

カテゴリの権限で、ボットに「チャンネルを見る」「チャンネルの管理」「権限の管理」を許可してください。

## 日常の使い方

- `＋ 仮部屋を作る（4人）` などに入る → `仮音声通話_n` が作られ、自動で移動する
- 同じ名前のテキストも同時に作られる（カテゴリを見られるロールなら閲覧・投稿できる）
- 全員がボイスを出ると、約20秒後にボイスとテキストが削除される
- すでに部屋を持っている人が別の作成ボイスに入ると、新しい部屋は作らず既存の部屋へ戻る

## コマンド

| コマンド | できること |
|---|---|
| `/setup category` | 作成先カテゴリを指定 |
| `/setup role` | 作成できるロールの追加・削除 |
| `/setup show` | いまの設定を表示 |
| `/setup hubs` | ハブの一覧。未作成なら初期5本を作る |
| `/setup hub` | ハブを1つ追加・変更・削除 |
| `/setup debug` | ボットから見た権限を表示 |
| `/room create` | コマンドから部屋を作る（1人1部屋） |
| `/room panel` | ボタンパネルを置く |

`/setup hub` の例:

- 追加: action=`追加` limit=`3` → 3人用の作成ボイスを作る
- 変更: action=`変更` limit=`4` new_limit=`6`
- 削除: action=`削除` limit=`10`
- limit `0` は制限なし

## 止める・更新する

```
docker compose down
docker compose up --build -d
```

## ライセンス

MIT License. 依存ライブラリ（discord.py, aiosqlite, python-dotenv）もそれぞれ MIT です。
