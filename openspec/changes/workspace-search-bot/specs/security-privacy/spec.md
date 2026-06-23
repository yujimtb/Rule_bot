## ADDED Requirements

### Requirement: Lake 直接読み取り禁止
Bot, agent, MCP tools は LETHE Lake を直接読んではならない SHALL とする。読み取りは LETHE の Projection/API 経由に限定する。

#### Scenario: Bot からの Lake 直接アクセス拒否
- **WHEN** Bot または agent が情報を取得する
- **THEN** Access Controlled Corpus Projection と Grep API のみを経由し、Lake に直接アクセスしない

#### Scenario: MCP ツールからの Lake 直接アクセス拒否
- **WHEN** MCP Server のツールが LETHE にアクセスする
- **THEN** LETHE の HTTP API (Projection/Grep API) のみを使用し、Lake ストレージに直接アクセスしない

### Requirement: サービストークンによるアクセス
Bot は LETHE に対してサービストークンでアクセス SHALL する。MVP では共通コーパスのため、質問者ごとの ACL 分離はしない。

#### Scenario: サービストークン認証
- **WHEN** Bot が LETHE API を呼び出す
- **THEN** 環境変数 (LETHE_SERVICE_TOKEN) から取得したサービストークンで認証する

#### Scenario: slack_user_id の付与
- **WHEN** Bot が LETHE API を呼び出す
- **THEN** 質問者の slack_user_id をログ記録、quota、自分が回答したかどうかの補助、将来の per-user ACL 拡張のために渡してよい

### Requirement: opt-out
opt-out 人物に関する Slack 投稿や Drive author 情報はアクセス制御 Projection で除外 SHALL する。

#### Scenario: opt-out 人物の Slack 投稿除外
- **WHEN** opt-out 登録された人物が Slack に投稿している
- **THEN** その人物の投稿はアクセス制御 Projection により検索コーパスから除外される

#### Scenario: opt-out 人物の Drive ファイル除外
- **WHEN** opt-out 登録された人物が owner/author の Drive ファイルがある
- **THEN** そのファイルはアクセス制御 Projection により検索コーパスから除外される

### Requirement: Form 個別回答の保護
個人の Form 回答内容は検索コーパスに露出しない SHALL する。誰がいつ回答したかという事実は露出する。

#### Scenario: 回答内容の非露出
- **WHEN** grep 検索が実行される
- **THEN** Form の個別回答内容は grep 結果に含まれない

#### Scenario: 回答事実の露出
- **WHEN** 「誰がフォームに回答したか」という質問に対して検索が実行される
- **THEN** 誰がいつ回答したかという事実は検索結果に含まれる

### Requirement: 監査ログ
実行した grep pattern、参照した record_id と URL、ユーザーに表示しなかった内部メタデータをログに残す SHALL する。

#### Scenario: grep pattern のログ記録
- **WHEN** grep 検索が実行される
- **THEN** 実行した grep pattern がログに記録される

#### Scenario: 参照レコードのログ記録
- **WHEN** agent がレコードを参照する
- **THEN** 参照した record_id と URL がログに記録される

#### Scenario: 非表示メタデータのログ記録
- **WHEN** 回答が生成される
- **THEN** ユーザーに表示しなかった confidence, unknowns, snippet がログに記録される
