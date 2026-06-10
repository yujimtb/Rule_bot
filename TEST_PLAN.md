# 実装後テスト計画

## 1. ローカル単体テスト

目的: SlackやDockerに依存しない中核ロジックを確認する。

```powershell
$env:PYTHONPATH="src"
python -m unittest discover -s tests
```

合格基準:

- Markdown/CSVを読み込める。
- `docs/`更新時に検索インデックスが自動再構築される。
- Codexへ渡す文脈が全文ではなく上位根拠候補に制限される。
- 既知質問に対して根拠付き回答を返す。
- 未記載質問では推測せず「現行ドキュメントでは確認できません」と返す。
- Slack表示用テキストに`回答`、`根拠`、`不明な点`が含まれる。

## 2. 回答サービス単体テスト

目的: HTTP APIとして回答できることを確認する。

```powershell
$env:PYTHONPATH="src"
$env:DOCS_DIR="docs"
$env:TOP_K="3"
$env:MIN_SCORE="0.08"
$env:ANSWER_BACKEND="local"
$env:PORT="8080"
python -m rulebot.answer_service
```

別ターミナルで確認する。

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8080/answer" `
  -Method Post `
  -Body (@{ question = "食器を割ったらどうする？" } | ConvertTo-Json) `
  -ContentType "application/json; charset=utf-8"
```

合格基準:

- HTTP 200でJSONが返る。
- `answer`、`citations`、`unknowns`、`slack_text`が含まれる。
- `citations`に参照したMarkdown/CSVのファイル名が含まれる。
- `index/search_index.json`が生成され、次回以降はdocs未変更なら再利用される。

スケーラブル検索の確認:

```powershell
Invoke-RestMethod `
  -Uri "http://127.0.0.1:8080/answer" `
  -Method Post `
  -Body (@{ question = "キーをなくした場合の費用はいくらですか？" } | ConvertTo-Json) `
  -ContentType "application/json; charset=utf-8"
```

合格基準:

- 質問文に`鍵`が含まれなくても、Codexの検索語生成とローカル検索により「鍵について」を根拠に回答する。
- Codexへ渡す根拠候補は`ANSWER_CONTEXT_TOP_K`件以下に制限される。

## 3. コンテナ隔離テスト

目的: 回答用途の処理がコンテナ内に閉じていることを確認する。

```bash
docker compose up -d --build answer-service
docker compose exec answer-service sh -lc 'id && ls -la /data/docs && touch /data/docs/write-test'
docker compose run --rm answer-service codex --version
```

合格基準:

- `answer-service`は非rootユーザーで動作する。
- `/data/docs/write-test`の作成は失敗する。
- `codex --version`が回答コンテナ内で成功する。
- テストログインする場合、`codex login`後に認証情報が`codex-home` volumeにのみ保存される。
- Compose設定にDocker socket、SSH鍵、ホスト全体のマウントがない。
- `http://127.0.0.1:8080/health`が`{"ok": true}`を返す。

## 4. テストSlack結合テスト

目的: テストSlackワークスペースでメンション型Botとして動くことを確認する。

事前条件:

- Slack CLIでワークスペース認証が完了している。
- Slack AppでSocket Modeを有効化する。
- Bot Token Scopesに`app_mentions:read`と`chat:write`を付与する。
- `.env`に`SLACK_BOT_TOKEN`と`SLACK_APP_TOKEN`を設定する。

Slack CLI manifest確認:

```bash
slack manifest info --source local --skip-update
slack manifest validate --skip-update
```

Slack CLIでトークンを`.env`へ保存する場合:

```bash
slack app install --skip-update
slack run --skip-update
```

テスト項目:

- `@bot 高校生の外泊ルールを教えて`の直後に、`config/slack_messages.json`の生成中メッセージが表示される。
- 回答完了後、生成中メッセージと同じ投稿が回答本文へ更新される。
- `@bot 食器を割ったらどうする？`で根拠付き回答が返る。
- `@bot キーをなくした場合の費用はいくらですか？`で、検索語の完全一致がなくても「鍵について」を根拠に回答する。
- `@bot Wi-Fiのパスワードは？`のような未記載質問で推測回答しない。
- Botメンションなしの通常投稿には反応しない。
- 同じスレッド内で質問した場合、スレッドに返信される。
- 連続で5件程度質問しても応答が詰まらない。
- `config/slack_messages.json`の文言を変えて再起動すると、生成中メッセージが変わる。

## 5. VPSデプロイ後テスト

目的: 少額VPS上で継続稼働できることを確認する。

```bash
docker compose --profile slack up -d --build
docker compose ps
docker compose logs --tail=100 answer-service
docker compose logs --tail=100 slack-bot
```

合格基準:

- `answer-service`と`slack-bot`が`Up`になる。
- コンテナ再起動後もSlack接続が復帰する。
- `.env`未設定時は起動失敗し、原因がログから分かる。
- 回答サービス障害時、Slackには簡潔な失敗メッセージが返る。
- `docs/`差し替え後、次回質問時に検索インデックスが更新される。
- `index/`を削除しても、次回質問時に再生成される。

## 6. 大きな文書セットでの確認

目的: 文書量が増えても全文投入に戻らず、候補制限が効くことを確認する。

テスト項目:

- 大きめのMarkdownを複数追加しても、回答がタイムアウトしない。
- `RETRIEVAL_CANDIDATE_TOP_K`と`ANSWER_CONTEXT_TOP_K`を変更すると、検索候補数とCodexへ渡す候補数の挙動が変わる。
- 未記載質問で無関係な大文書を根拠に推測回答しない。
