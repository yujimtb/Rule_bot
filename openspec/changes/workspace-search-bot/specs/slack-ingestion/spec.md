## ADDED Requirements

### Requirement: Slack 履歴取り込み
システムは Slack の履歴 export データをワンタイムで LETHE Lake に投入する機能を提供 SHALL する。

#### Scenario: 履歴 export の初回取り込み
- **WHEN** 6年分の Slack export データが入力として与えられる
- **THEN** システムは全メッセージを LETHE Lake に Observation として投入する

#### Scenario: 履歴 export の再投入で重複しない
- **WHEN** 同一の Slack export データが再度投入される
- **THEN** 重複 Observation は生成されない (channel, ts, thread_ts, message id 相当の値から idempotency key を生成する)

### Requirement: Slack 増分取り込み
システムは Slack API の cursor poll を使って増分メッセージを取り込む機能を提供 SHALL する。Slack の cursor pagination は Slack Web API pagination documentation に従う。

#### Scenario: 新規メッセージの増分取り込み
- **WHEN** 前回取り込み以降に新しいメッセージが public channel に投稿されている
- **THEN** システムは cursor poll により新規メッセージを LETHE Lake に投入する

#### Scenario: 増分取り込みは pull 専用
- **WHEN** 増分取り込みが実行される
- **THEN** システムは Slack API への pull (cursor poll) のみを使用し、Slack Events API などの push/trigger 型取り込みは使用しない

### Requirement: 取り込み間隔の設定
システムは取り込み間隔を可変に設定できる機能を提供 SHALL する。

#### Scenario: グローバル既定間隔の設定
- **WHEN** 管理者がグローバルな取り込み間隔を設定する
- **THEN** すべての channel に対してその間隔で取り込みが実行される

#### Scenario: channel 単位の間隔 override
- **WHEN** 特定の channel に対して取り込み間隔の override が設定されている
- **THEN** その channel はグローバル既定ではなく override された間隔で取り込まれる

#### Scenario: イベント準備期間の短縮
- **WHEN** イベント準備期間に管理者が取り込み間隔を短縮する
- **THEN** 設定変更が反映され、より短い間隔で取り込みが実行される

### Requirement: 取り込み状態の観測
システムは取り込み状態を観測可能にする機能を SHALL 提供する。

#### Scenario: 取り込み状態の確認
- **WHEN** 管理者が取り込み状態を確認する
- **THEN** 最終取り込み時刻、次回取り込み予定、失敗回数が表示される
