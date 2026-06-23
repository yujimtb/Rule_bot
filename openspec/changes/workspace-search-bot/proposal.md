## Why

Slack と Google Workspace 内の情報を、チャットボットから grep ベースで検索できるようにする。現状、ワークスペース内の情報検索は手動で各サービスを横断する必要があり、特にイベント準備や業務確認の際に非効率である。LETHE をデータ基盤として活用し、RAG ではなく grep + ReAct/tool-use による反復探索で、根拠 URL 付きの回答を返す Bot を構築する。

## What Changes

- Slack の履歴 export と増分 poll を LETHE Lake に取り込む Ingestor を新規実装する
- Google Workspace (Docs, Sheets, Forms, Slides, Drive) を巡回して LETHE Lake に投入する Crawler を新規実装する
- アクセス制御された検索コーパスを生成する Projection を LETHE 側に追加する
- 正規表現 grep API を LETHE 側に実装する
- MCP Server を新規実装し、grep_search 等のツールを Search Bot に提供する
- Slack 上で人間起点の質問を受け、エージェントが grep + ReAct で探索し、回答本文とソース URL を返す Search Bot を新規実装する
- Bot の過去回答を scaffolding として利用するための Answer Log を実装する
- Form 個別回答内容の非露出、Bot 投稿の一次ソース除外など、プライバシーとループ防止の仕組みを組み込む

## Capabilities

### New Capabilities
- `slack-ingestion`: Slack の履歴 export と cursor poll による増分取り込み
- `drive-crawl`: Google Workspace (Docs, Sheets, Forms, Slides, Drive) のクロールと LETHE Lake への投入
- `access-control-projection`: アクセス制御 Projection による検索コーパス生成 (Slack channel ルール、Drive 共有閾値、Form 回答非露出、opt-out)
- `grep-api`: NFKC 正規化済み正規表現 grep API (cursor pagination、trigram 高速化)
- `mcp-tools`: grep_search, get_record, get_thread, resolve_link, prior_qa_search を提供する MCP Server
- `search-agent`: 人間起点で起動し、grep + ReAct で反復探索するエージェント動作仕様
- `user-output`: 回答本文とソース URL のみをユーザーに表示する出力仕様
- `answer-log`: 構造化回答ログと scaffolding ルール
- `loop-prevention`: Bot 自動投稿の無限ループ防止
- `security-privacy`: Lake 直接読み取り禁止、サービストークン、opt-out、Form 回答保護

### Modified Capabilities

(既存 spec なし)

## Impact

- LETHE リポジトリに Access Controlled Corpus Projection と Grep API を追加
- 新規リポジトリで Search Bot、MCP Server、Slack Ingestor、Drive Crawler を実装
- Slack API (export, Web API cursor pagination) への依存
- Google Drive API, Docs API, Sheets API, Forms API への依存
- MCP (Model Context Protocol) による agent-tool 接続
- LLM API (agent の推論エンジン) への依存
