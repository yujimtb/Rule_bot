## ADDED Requirements

### Requirement: grep_search ツール
MCP Server は Search Bot agent に regex grep を実行する grep_search ツールを提供 SHALL する。

#### Scenario: grep_search によるパターン検索
- **WHEN** agent が grep_search ツールに regex パターンとフィルタを渡して呼び出す
- **THEN** LETHE の Grep API が呼び出され、match 結果が agent に返される

#### Scenario: grep_search の 1回あたりの件数上限
- **WHEN** agent が grep_search を呼び出す
- **THEN** 1回の MCP tool call で返す件数に上限が適用される

### Requirement: get_record ツール
MCP Server は record_id から露出可能な全文または詳細を取得する get_record ツールを提供 SHALL する。

#### Scenario: record_id による詳細取得
- **WHEN** agent が get_record ツールに record_id を渡す
- **THEN** Access Controlled Corpus Projection で露出可能なレコードの全文と詳細が返される

#### Scenario: 非露出レコードの取得拒否
- **WHEN** agent が検索コーパスに露出していない record_id を get_record に渡す
- **THEN** レコードは返されず、アクセス拒否される

### Requirement: get_thread ツール
MCP Server は Slack thread の文脈を取得する get_thread ツールを提供 SHALL する。

#### Scenario: Slack スレッドの文脈取得
- **WHEN** agent が get_thread ツールに parent permalink または thread_ts を渡す
- **THEN** そのスレッド内の露出可能なメッセージ一覧が返される

### Requirement: resolve_link ツール
MCP Server は Slack permalink、Drive URL、Docs URL などを LETHE record に解決する resolve_link ツールを提供 SHALL する。

#### Scenario: Slack permalink の解決
- **WHEN** agent が resolve_link に Slack permalink を渡す
- **THEN** 対応する LETHE record_id が返される

#### Scenario: Google Drive URL の解決
- **WHEN** agent が resolve_link に Google Docs/Sheets/Forms/Slides/Drive の URL を渡す
- **THEN** 対応する LETHE record_id が返される

### Requirement: prior_qa_search ツール
MCP Server は過去の Bot 回答ログを scaffolding として検索する prior_qa_search ツールを提供 SHALL する。

#### Scenario: 過去回答の検索
- **WHEN** agent が prior_qa_search に検索クエリを渡す
- **THEN** 過去の Bot 回答ログから関連する回答と citations が返される

#### Scenario: prior_qa_search の結果は一次ソースでない
- **WHEN** prior_qa_search の結果が返される
- **THEN** 結果に「一次ソースではない」ことが明示され、agent は citations を使って一次ソースへ到達し再検証する必要がある
