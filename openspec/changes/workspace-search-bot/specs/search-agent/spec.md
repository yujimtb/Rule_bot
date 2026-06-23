## ADDED Requirements

### Requirement: 人間起点の起動
Search Bot は人間起点でのみ起動 SHALL する。

#### Scenario: Slack mention による起動
- **WHEN** ユーザーが Slack 上で Bot を mention する
- **THEN** Search Bot が起動し、質問に対するエージェント処理が開始される

#### Scenario: slash command による起動
- **WHEN** ユーザーが Slack の slash command を実行する
- **THEN** Search Bot が起動する

#### Scenario: LETHE 登録イベントでは起動しない
- **WHEN** LETHE に新しい Observation が登録される
- **THEN** Search Bot は自動起動しない

#### Scenario: 取り込み完了では起動しない
- **WHEN** Slack メッセージ取り込みまたは Drive crawl が完了する
- **THEN** Search Bot は自動起動しない

### Requirement: RAG 不使用
Agent は RAG retriever および embedding 類似検索を使用しない SHALL する。検索は grep と ReAct/tool-use による反復探索とする。

#### Scenario: grep ベースの検索実行
- **WHEN** agent が情報を探索する
- **THEN** grep_search ツールを使用し、embedding 類似検索やランキング型 retriever は使用しない

### Requirement: 一次ソース URL の付与
Agent は最終回答に一次ソース URL を付ける SHALL する。

#### Scenario: 根拠つき回答の生成
- **WHEN** agent が質問に対する回答を生成する
- **THEN** 回答には一次ソース (Slack の人間投稿、Google Workspace ドキュメント等) の URL が含まれる

#### Scenario: 根拠なしの場合の明示
- **WHEN** 一次ソースが見つからない
- **THEN** agent は根拠が確認できない旨を回答する

### Requirement: 過去回答の一次ソース禁止
Agent は Bot の過去回答を一次ソースとして使用しない SHALL する。

#### Scenario: 過去回答を scaffolding として使用
- **WHEN** agent が prior_qa_search で過去回答を見つける
- **THEN** その回答内の citations をたどって一次ソースに到達し、再度 grep_search, get_record, resolve_link で検証してから回答する

#### Scenario: 再検証できない過去回答の排除
- **WHEN** 過去回答の citations が再検証できない
- **THEN** その過去回答は最終回答の根拠にしない

### Requirement: scaffolding 優先の探索方針
Agent は prior_qa_search を最初に使い、過去回答の citations を探索の足場にする探索方針を SHALL サポートする。

#### Scenario: 探索開始時の scaffolding 参照
- **WHEN** agent が新しい質問の探索を開始する
- **THEN** まず prior_qa_search で類似の過去回答を探し、見つかった citations を足場にして grep 探索を効率化する

### Requirement: 表記ゆれの吸収
Agent は表記ゆれを regex の OR と複数 grep で吸収する機能を SHALL 備える。

#### Scenario: 表記ゆれ対応の検索
- **WHEN** 質問に含まれるキーワードに表記ゆれの可能性がある
- **THEN** agent は `落とし物|忘れ物|遺失物` のような OR パターンや、複数回の grep で表記ゆれを吸収する

### Requirement: ツール呼び出し上限
Agent のツール呼び出し数と実行時間に上限を設ける SHALL する。

#### Scenario: max_tool_calls の適用
- **WHEN** agent のツール呼び出しが max_tool_calls (初期案: 30) に達する
- **THEN** 探索は打ち切られ、それまでの結果で回答が生成される

#### Scenario: max_wall_clock_seconds の適用
- **WHEN** agent の実行時間が max_wall_clock_seconds (初期案: 120秒) に達する
- **THEN** 探索は打ち切られ、それまでの結果で回答が生成される

#### Scenario: max_grep_pages_per_query の適用
- **WHEN** 1つの grep クエリのページング回数が max_grep_pages_per_query (初期案: 10) に達する
- **THEN** そのクエリの追加ページングは行わない

#### Scenario: max_records_loaded の適用
- **WHEN** agent がロードしたレコード数が max_records_loaded (初期案: 200) に達する
- **THEN** 追加のレコードロードは行わない

### Requirement: 探索ログの記録
Agent は used queries、ヒット件数、参照 record をログに残す機能を SHALL 備える。

#### Scenario: 探索ログの出力
- **WHEN** agent が探索を完了する
- **THEN** 実行した grep pattern、各クエリのヒット件数、参照した record_id がログに記録される
