# Slackルール回答Bot プロトタイプ

館内規則・生活ルールのMarkdown/CSVをVPS上に置き、Slackで`@bot 質問`された内容に根拠付きで回答するプロトタイプです。

このリポジトリはWSL上での実行を前提にしています。詳しい手順は[WSL.md](WSL.md)を参照してください。

## 構成

- `slack-bot`: Slack Socket Modeで`app_mention`だけを受け取り、回答サービスへ問い合わせます。
- `answer-service`: `docs/`内のMarkdown/CSVを根拠として、Agent CLIまたはローカル検索で回答します。
- `docs/`: 手動配置するルール文書です。コンテナからは読み取り専用で参照します。
- `index/`: 自動生成される検索インデックスです。削除しても再生成できます。

標準の回答フローは以下です。

1. Slackメンションから質問を受け取る。
2. Agent CLIが質問から検索語・関連語をJSONで生成する。
3. `index/`のローカル検索インデックスから関連チャンクを取得する。
4. 上位候補だけをAgent CLIに渡し、根拠付き回答を生成する。

全文を毎回Agent CLIへ渡さないため、文書量が増えても回答に使うコンテキスト量は`ANSWER_CONTEXT_TOP_K`で制御できます。

## 起動

`.env`を作成し、Slack Appのトークンを設定します。

```env
SLACK_BOT_TOKEN=replace-with-slack-bot-token
SLACK_APP_TOKEN=replace-with-slack-app-token
```

起動します。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose --profile slack up -d --build'
```

Slack App側ではSocket Modeを有効化し、Bot Token Scopesに少なくとも`app_mentions:read`と`chat:write`を付与してください。

## ドキュメント更新

初期版では`docs/`へMarkdown/CSVを手動配置します。更新後は、まず以下で回答サービスの動作を確認してください。

```powershell
wsl sh -lc 'curl -s http://127.0.0.1:8080/health'
```

`answer-service`はリクエスト時に`docs/`の更新を検知し、必要な場合だけ`index/`の検索インデックスを再構築します。プロトタイプ段階では再起動なしで内容更新を反映できます。

インデックスを作り直したい場合は、`index/search_index.json`を削除してください。次回の質問時に自動生成されます。

## 回答形式

Slackへの返答は必ず以下の形にします。

- `回答`
- `根拠`
- `不明な点`

文書に見つからない質問は推測せず、「現行ドキュメントでは確認できません」と返します。

## Slackの生成中メッセージ

質問を受け取ると、Slack Botはすぐに生成中メッセージを投稿し、回答完了後に同じ投稿を回答へ更新します。
文言は[config/slack_messages.json](config/slack_messages.json)で変更できます。

回答本文がSlack APIの上限を超える場合は、自動的に短くして再送します。`chat.update`が`msg_too_long`を返した場合も段階的に短い本文で再試行し、内部エラーの長いログをSlackへ表示しません。

## Slack CLI

Slack Appのmanifestは[.slack/manifest.json](.slack/manifest.json)で管理します。Slack CLIは`.slack/hooks.json`からmanifestを読み込みます。

WSL側でSlack CLIを認証します。

```powershell
wsl sh -lc 'export PATH="$HOME/.local/bin:$PATH"; slack login'
```

認証後にmanifestを検証します。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && export PATH="$HOME/.local/bin:$PATH"; slack manifest validate --skip-update'
```

Slack Appをインストールします。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && export PATH="$HOME/.local/bin:$PATH"; slack app install --skip-update'
```

Slack CLIが発行した`SLACK_BOT_TOKEN`と`SLACK_APP_TOKEN`を`.env`へ保存する場合は、以下を実行します。値はターミナルへ表示しません。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && export PATH="$HOME/.local/bin:$PATH"; slack run --skip-update'
```

## OpenSpec

このリポジトリはOpenSpecで変更提案・仕様・実装タスクを管理できます。OpenSpec本体はdevDependencyとして固定しています。

```powershell
npm install
npm run openspec -- list
npm run openspec:validate
```

Codex向けのOpenSpecスキルは[.codex/skills](.codex/skills)に生成済みです。新しい変更を始める場合は、まず以下のように依頼してください。

```text
/opsx:propose "追加したい変更内容"
```

OpenSpecの変更提案は`openspec/changes/`、確定済み仕様は`openspec/specs/`に配置します。

## Agentバックエンド

標準は`ANSWER_BACKEND=agent`です。`AGENT_CLI_PROVIDER`で`codex`、`codex_app_server`、`claude`を選び、Agent CLIで日本語回答を生成します。現在の既定はDockerイメージに同梱したCodex CLIです。`codex`/`claude`では、Agent CLIが質問から検索語・関連語を作り、ローカル検索インデックスで根拠候補を取得してから、上位候補だけをAgent CLIに渡して回答します。

`AGENT_COMMAND`はJSONを標準入力で受け取り、以下のJSONを標準出力に返す固定コマンドにしてください。

```json
{
  "answer": "回答本文",
  "citations": ["docs/example.md: 見出し"],
  "unknowns": []
}
```

AgentにはDocker socket、SSH鍵、ホスト全体のディレクトリを渡さないでください。

Agent CLIの主な設定:

```env
AGENT_CLI_PROVIDER=codex_app_server
AGENT_COMMAND=python -m rulebot.agent_worker
AGENT_WORKDIR=/app
AGENT_QUERY_TIMEOUT_SECONDS=45
AGENT_ANSWER_TIMEOUT_SECONDS=180
CODEX_APP_SERVER_REMOTE_COMPACTION_V2=1
CODEX_APP_SERVER_SEED_TIMEOUT_SECONDS=300
CODEX_APP_SERVER_ANSWER_TIMEOUT_SECONDS=300
CODEX_APP_SERVER_USAGE_DRAIN_SECONDS=2
```

`codex_app_server`では、`answer-service`プロセス内でCodex app-serverを常駐起動し、館内規則を読み込んだcompact済みseed thread上で回答してから`thread/rollback numTurns=1`で回答ターンだけ削除します。seedを新規作成した直後の初回回答は月間quotaへ加算しません。app-server方式が失敗した場合は、既存CLI方式へ切り替えず短いエラーメッセージを返します。

Codexの認証切れ、利用上限、タイムアウトなどのAgentエラーは短い利用者向けメッセージに変換します。`refresh_token_reused`やスタックトレースなどの内部ログはSlackへ返さず、`answer-service`のログにだけ記録します。認証エラーが出た場合は、以下の再ログインを実行してください。

Codexを使う場合のインストール確認:

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex --version'
```

Codexのデフォルトモデルは`gpt-5.4-mini`です。初回起動時に`$CODEX_HOME/config.toml`へ永続保存されます。
回答生成時のreasoning effortは標準で`medium`、検索語生成は`low`です。

Claude Codeへ切り替える場合は、コンテナ内で`claude`コマンドを利用可能にしてから以下を設定します。Claude Codeは`claude -p --output-format json`で実行します。

```env
AGENT_CLI_PROVIDER=claude
CLAUDE_MODEL=
CLAUDE_PERMISSION_MODE=plan
CLAUDE_EXTRA_ARGS=
```

`RETRIEVAL_CANDIDATE_TOP_K`で検索候補数、`ANSWER_CONTEXT_TOP_K`でAgent CLIへ渡す候補数を調整できます。

主な設定:

```env
AGENT_QUERY_TIMEOUT_SECONDS=45
AGENT_ANSWER_TIMEOUT_SECONDS=180
CODEX_QUERY_PLANNER_REASONING_EFFORT=low
CODEX_REASONING_EFFORT=low
RETRIEVAL_CANDIDATE_TOP_K=30
ANSWER_CONTEXT_TOP_K=8
```

精度を上げたい場合は、まず`RETRIEVAL_CANDIDATE_TOP_K`を増やし、次に`ANSWER_CONTEXT_TOP_K`を少し増やしてください。reasoning effortを上げるのは応答時間が許容できる場合だけにしてください。

## 月次トークン割当

Slack Botは`@bot 質問`のメンションにだけ応答し、回答末尾に今回のAgent CLI使用量、今月の使用量、残り割当量を表示します。

```env
AGENT_MONTHLY_TOKEN_LIMIT=1000000
AGENT_MONTHLY_QUOTA_USERS=10
TOKEN_QUOTA_TIMEZONE=Asia/Tokyo
```

一人当たりの月次上限は`AGENT_MONTHLY_TOKEN_LIMIT / AGENT_MONTHLY_QUOTA_USERS`で計算します。使用量はAgent CLIのJSON出力から取得し、`total_tokens - cached_input_tokens`の実質使用量を加算します。seedを新規作成した直後の初回回答など、`usage_chargeable=false`として返った回答は月間quotaに加算しません。

全ユーザー合計の月次使用量が`AGENT_MONTHLY_TOKEN_LIMIT`に達した場合も、回答生成前に停止します。この場合はBot全体の月間上限に達した旨だけをSlackへ通知します。

使用量DBはSlack Botコンテナ内の`/data/usage/agent_usage.sqlite3`に保存します。このvolumeは`answer-service`にはマウントしないため、Agent CLIがプロンプト経由で使用量DBを読んだり書いたりすることはできません。

Codexへテストログインする場合:

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex login'
```

認証をやり直す場合:

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex logout'
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex login'
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose --profile slack restart answer-service slack-bot'
```

認証情報はDocker volumeの`codex-home`にだけ保存されます。テスト後に消す場合:

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker compose run --rm answer-service codex logout'
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && docker volume rm rule_bot_codex-home'
```

Codex回答を使わず、検索抜粋だけに戻す場合は`.env`で`ANSWER_BACKEND=local`にしてください。

## テスト

ローカルでは依存関係なしで中核テストを実行できます。

```powershell
wsl sh -lc 'cd /mnt/d/userdata/docs/work/HLAB/Rule_bot && PYTHONPATH=src python3 -m unittest discover -s tests'
```

WSLのシェル内で直接実行する場合:

```bash
PYTHONPATH=src python -m unittest discover -s tests
```

実装後の受け入れ確認:

- テストSlackで`@bot 食器を割ったらどうする？`に根拠付きで返ること。
- 通常投稿には反応せず、メンション時のみ応答すること。
- 文書にない質問では推測回答しないこと。
- 回答コンテナから`docs/`へ書き込めないこと。
- Docker socket、SSH鍵、ホストの不要なファイルを回答コンテナへマウントしていないこと。
