## ADDED Requirements

### Requirement: ユーザー表示は回答本文とソース URL のみ
ユーザーに表示する内容は回答本文とソース URL のみと SHALL する。

#### Scenario: 正常な回答表示
- **WHEN** agent が回答を生成し Slack に投稿する
- **THEN** 回答本文とソース URL のみが表示され、confidence, snippet, used queries, author, timestamp, unknowns, token usage, internal reasoning は表示されない

#### Scenario: 出力フォーマットの例
- **WHEN** フォームの提出期限についての質問に回答する
- **THEN** 回答は以下の形式で表示される: 回答本文、空行、"Sources:" の後にソース URL のリスト

### Requirement: 内部構造化エンベロープの保持
内部的には構造化エンベロープ (confidence, snippet, used_queries, unknowns 等) を保持 SHALL する。

#### Scenario: 内部メタデータの保存
- **WHEN** agent が回答を生成する
- **THEN** confidence, snippet, used_queries, author, timestamp, unknowns, token usage が構造化エンベロープとしてログに保存される

#### Scenario: ユーザーへの非表示
- **WHEN** 構造化エンベロープが保存される
- **THEN** show_internal_metadata_to_user が false のため、Slack 上のユーザーにはこれらのメタデータは表示されない
