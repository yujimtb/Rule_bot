# WSLでの起動手順

このプロジェクトはWSL上で動かす前提です。Windows PowerShellから操作する場合も、実行コマンドは`wsl sh -lc '...'`経由にしてください。

## 前提確認

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && python3 --version && docker --version && docker compose version'
```

## テスト

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && sh scripts/test.sh'
```

## Slackトークン設定

WSL側で`.env`を作成します。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && cp .env.example .env'
```

`.env`に以下を設定してください。

```env
SLACK_BOT_TOKEN=replace-with-slack-bot-token
SLACK_APP_TOKEN=replace-with-slack-app-token
```

## Slack CLI認証

このリポジトリにはSlack CLI用のmanifestとhookを含めています。WSL側でSlack CLIを使う場合は、まず認証します。

```powershell
wsl sh -lc 'export PATH="$HOME/.local/bin:$PATH"; slack login'
```

ターミナルに表示された`/slackauthticket ...`をSlackの任意のDMまたはチャンネルへ投稿し、Slack上のモーダルで承認してください。表示されたchallenge codeをターミナルへ入力すると認証が完了します。

認証後、manifestを検証します。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && export PATH="$HOME/.local/bin:$PATH"; slack manifest validate --skip-update'
```

新しいSlack Appを作成または既存Appをリンクしてインストールする場合は、認証後に以下を実行します。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && export PATH="$HOME/.local/bin:$PATH"; slack app install --skip-update'
```

Slack CLIから発行された`SLACK_BOT_TOKEN`と`SLACK_APP_TOKEN`を`.env`へ保存する場合は、インストール後に以下を実行します。値はターミナルへ表示しません。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && export PATH="$HOME/.local/bin:$PATH"; slack run --skip-update'
```

## Compose確認

Slack Botまで起動する場合は、`.env`設定後に実行します。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && COMPOSE_PROFILES=slack sh scripts/check-compose.sh'
```

## 起動

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose --profile slack up -d --build'
```

## 動作確認

```powershell
wsl sh -lc 'curl -s http://127.0.0.1:8080/health'
```

Slackのテストワークスペースで`@bot 食器を割ったらどうする？`を投稿し、根拠付き回答が返ることを確認してください。

生成中メッセージの文言は`config/slack_messages.json`で変更できます。変更後はSlack Botを再起動してください。

検索インデックスは初回回答時または`docs/`更新時に自動生成されます。状態を確認する場合:

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && ls -lh index/search_index.json'
```

強制的に再生成したい場合は、停止中または質問が来ていないタイミングで`index/search_index.json`を削除してください。次回の質問時に再作成されます。

## Codex CLI確認

回答コンテナにはCodex CLIを同梱しています。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex --version'
```

デフォルトモデルは`gpt-5.4-mini`です。設定はDocker volume上の`$CODEX_HOME/config.toml`に保存されます。
回答生成時のreasoning effortは標準で`medium`、検索語生成は`low`です。変更する場合は`.env`で`CODEX_REASONING_EFFORT`や`CODEX_QUERY_PLANNER_REASONING_EFFORT`を設定してください。

Codexを回答バックエンドに使う設定が標準です。Codexが検索語を生成し、ローカル検索インデックスで取得した根拠候補だけを使って回答します。検索抜粋だけに戻す場合は、`.env`で`ANSWER_BACKEND=local`にしてください。

候補数を調整する場合は`.env`で以下を変更します。

```env
RETRIEVAL_CANDIDATE_TOP_K=30
ANSWER_CONTEXT_TOP_K=8
```

`RETRIEVAL_CANDIDATE_TOP_K`はローカル検索で広めに拾う候補数、`ANSWER_CONTEXT_TOP_K`はCodexへ渡す最終候補数です。

## Codexへテストログイン

あなたのアカウントでログインする場合は、以下を実行して表示される案内に従ってください。認証情報やブラウザ承認はユーザー本人が扱います。
Slack Botが未設定でも実行できます。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex login'
```

Slackに「回答エンジンの認証が切れています」と表示された場合は、Codexの認証情報を更新してください。`refresh_token_reused`などの内部エラー詳細はSlackには表示せず、`answer-service`ログに記録されます。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex logout'
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex login'
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose --profile slack restart answer-service slack-bot'
```

ログイン状態はDocker volumeの`codex-home`に保存されます。テスト後に消す場合:

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex logout'
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker volume rm rule_bot_codex-home'
```

## 停止

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose down'
```
