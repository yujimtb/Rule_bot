## 1. LETHE 側: Access Controlled Corpus Projection

- [x] 1.1 Slack メッセージ向けの Projection ルールを実装する (is_public_channel, channel_name regex, bot 除外, opt-out 除外)
- [x] 1.2 Drive ファイル向けの Projection ルールを実装する (allowed_folder, sharing 閾値, opt-out 除外, 除外ファイル)
- [x] 1.3 Form 個別回答内容の非露出ルールを実装する (構造・回答事実は露出、回答内容は非露出)
- [x] 1.4 Form 回答連携 Sheet の明示的除外ルールを実装する
- [x] 1.5 Projection ルールのユニットテストを作成する

## 2. Slack 取り込み

- [x] 2.1 Slack 履歴 export を LETHE Lake に投入するワンタイムツールを実装する
- [x] 2.2 idempotency key (channel, ts, thread_ts, message id) による重複防止を実装する
- [x] 2.3 Slack 履歴取り込みの冪等性テストを作成する
- [x] 2.4 Slack cursor poll による増分取り込みを実装する
- [x] 2.5 グローバル既定間隔と channel 単位 override の設定機能を実装する
- [x] 2.6 最終取り込み時刻・次回予定・失敗回数の観測機能を実装する

## 3. Drive Crawler

- [x] 3.1 Google Docs adapter を実装する (本文、見出し、リンク、メタデータの取り込み)
- [x] 3.2 Google Sheets adapter を実装する (行単位の内容、ヘッダ文脈、メタデータの取り込み)
- [x] 3.3 Google Forms adapter を実装する (構造、設問、URL、回答事実、個別回答の取り込み)
- [x] 3.4 Google Slides adapter を横展開する (既存 adapter のスキーマ流用)
- [x] 3.5 Drive ファイル一般の adapter を実装する (allowlist フォルダ配下の検索可能ファイル)
- [x] 3.6 workspace-object-snapshot schema を Docs, Sheets, Forms, Drive file に適用する
- [x] 3.7 revision ベースの差分投入を実装する (sourceRevisionId による変更検出)
- [x] 3.8 日次クロールと間隔変更設定を実装する

## 4. Grep API

- [x] 4.1 NFKC 正規化済みテキストに対する正規表現検索を実装する
- [x] 4.2 原文の保持と検索用正規化テキストの分離を実装する
- [x] 4.3 cursor pagination を実装する
- [x] 4.4 ソース種別、日時範囲、チャンネル、コンテナのフィルタを実装する
- [x] 4.5 regex 実行時間の上限 (既定 500ms) を実装する
- [x] 4.6 POST /api/projections/{projection_id}/grep のエンドポイントを実装する
- [x] 4.7 Trigram index による候補絞り込みを実装する (match 欠落なしの保証つき)
- [x] 4.8 Grep API のインテグレーションテストを作成する

## 5. MCP Server

- [x] 5.1 MCP Server のプロジェクト構成とフレームワーク選定を行う
- [x] 5.2 grep_search ツールを実装する (LETHE Grep API への接続)
- [x] 5.3 get_record ツールを実装する (record_id からの全文取得)
- [x] 5.4 get_thread ツールを実装する (Slack thread 文脈取得)
- [x] 5.5 resolve_link ツールを実装する (URL から LETHE record への解決)
- [x] 5.6 prior_qa_search ツールを実装する (Answer Log 検索)
- [x] 5.7 MCP ツールのインテグレーションテストを作成する

## 6. Search Bot Agent

- [x] 6.1 Slack Bot アプリの設定と Slack API 接続を実装する
- [x] 6.2 人間起点の起動条件 (mention, slash command) を実装する
- [x] 6.3 ReAct/tool-use による反復探索ループを実装する
- [x] 6.4 prior_qa_search を最初に使う scaffolding 探索方針を実装する
- [x] 6.5 表記ゆれの regex OR 生成を実装する
- [x] 6.6 一次ソース URL の付与と根拠なし時のメッセージを実装する
- [x] 6.7 max_tool_calls, max_wall_clock_seconds, max_grep_pages_per_query, max_records_loaded の上限制御を実装する

## 7. ユーザー出力と回答ログ

- [x] 7.1 Slack への回答出力 (回答本文 + ソース URL のみ) を実装する
- [x] 7.2 構造化エンベロープ (confidence, snippet, used_queries 等) の内部保存を実装する
- [x] 7.3 Answer Log の構造化ログ保存を実装する (question, answer, citations, used_queries, asker, ts, model, usage, confidence, unknowns)
- [x] 7.4 scaffolding 使用時の prior answer id ログ記録を実装する

## 8. ループ防止とセキュリティ

- [x] 8.1 Bot 投稿の一次検索コーパス除外が正しく動作することを検証するテストを作成する
- [x] 8.2 LETHE 登録イベントから Bot 自動投稿への経路がないことを検証するテストを作成する
- [x] 8.3 Lake 直接読み取り禁止の enforcement を検証するテストを作成する
- [x] 8.4 Form 個別回答内容が grep 結果に出ないことを検証するテストを作成する
- [x] 8.5 サービストークン認証と slack_user_id 付与を実装する

## 9. 設定と運用

- [x] 9.1 YAML 設定ファイル (workspace_search) のスキーマと読み込みを実装する
- [x] 9.2 channel_allow_regex, channel_opt_in, exclude_bot_authors の設定を実装する
- [x] 9.3 Drive allowed_folder_ids, sharing 閾値, exclude_form_response_sheets の設定を実装する
- [x] 9.4 agent の上限パラメータ設定を実装する

## 10. 受け入れテストと調整

- [x] 10.1 tier A (locate) の代表質問で回答品質を評価する
- [x] 10.2 tier B (extract/filter/aggregate) の代表質問で回答品質を評価する
- [x] 10.3 取り込み間隔、tool call 上限、grep limit の値を運用結果に基づいて調整する
