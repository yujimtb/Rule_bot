## ADDED Requirements

### Requirement: 構造化回答ログの保存
Bot は回答ごとに構造化ログを保存 SHALL する。

#### Scenario: 回答ログの記録
- **WHEN** Bot が質問に対して回答を生成する
- **THEN** question, answer, citations (url, record_id, source_type), used_queries, asker (slack_user_id), ts, model, usage (input_tokens, output_tokens), confidence, unknowns を含む構造化ログが保存される

#### Scenario: citations の記録
- **WHEN** 回答に一次ソースが含まれる
- **THEN** 各 citation の url, record_id, source_type がログに記録される

### Requirement: scaffolding としての利用
過去の Bot 回答は回答に早く到達するための scaffolding として利用可能と SHALL する。

#### Scenario: prior_qa_search による scaffolding 参照
- **WHEN** agent が prior_qa_search を使用する
- **THEN** 過去の回答ログから関連する回答と citations が返され、探索の足場として使用できる

### Requirement: Bot 回答の一次ソース禁止
Bot 回答そのものを一次ソースにしない SHALL する。

#### Scenario: 過去回答の再検証必須
- **WHEN** agent が prior_qa_search で過去回答を見つける
- **THEN** その回答の citations をたどって一次ソースに到達し、再度検証してから回答に使用する

#### Scenario: 再検証不能な過去回答の排除
- **WHEN** 過去回答の citations が現在の検索コーパスで再検証できない
- **THEN** その過去回答は最終回答の根拠にしない

### Requirement: Bot 投稿のコーパス除外
author == bot の Slack 投稿は primary grep corpus から除外 SHALL する。

#### Scenario: Bot 自身の投稿の除外
- **WHEN** Bot が Slack に回答を投稿する
- **THEN** その投稿は LETHE に取り込まれても、一次検索コーパス (Access Controlled Corpus Projection) には含まれない

### Requirement: scaffolding 使用の監査
Bot が過去回答を scaffolding として使った場合、その prior answer id をログに残す SHALL する。

#### Scenario: scaffolding 使用のログ記録
- **WHEN** agent が prior_qa_search の結果を探索の足場として使用する
- **THEN** 使用した prior answer id がログに記録される
