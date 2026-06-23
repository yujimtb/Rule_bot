## ADDED Requirements

### Requirement: pull 専用取り込み
データ取り込みは pull 専用と SHALL する。LETHE に Observation が登録されたことを契機に Slack 投稿する trigger を実装しない。

#### Scenario: 取り込みは pull のみ
- **WHEN** データ取り込みが実行される
- **THEN** Slack API への pull (cursor poll) または Drive API への pull (crawl) のみが使用され、push/trigger 型の取り込みは行われない

### Requirement: 人間起点の Bot 起動
Search Bot は人間起点でのみ起動 SHALL する。

#### Scenario: Observation 登録では Bot が起動しない
- **WHEN** LETHE に新しい Observation が登録される
- **THEN** Search Bot は自動起動しない

#### Scenario: 取り込み完了では Bot が起動しない
- **WHEN** Slack メッセージ取り込み完了または Drive crawl 完了が発生する
- **THEN** Search Bot は自動起動しない

#### Scenario: Projection 更新では Bot が起動しない
- **WHEN** Projection の更新が完了する
- **THEN** Search Bot は自動起動しない

### Requirement: Bot 投稿のコーパス除外
Bot 投稿は一次検索コーパスから除外 SHALL する。

#### Scenario: Bot 投稿の再取り込み後の安全性
- **WHEN** Bot の Slack 投稿が LETHE に取り込まれる
- **THEN** その投稿は Access Controlled Corpus Projection から除外され、grep 検索結果に含まれない

### Requirement: LETHE 登録からの Slack 投稿経路の禁止
LETHE 登録イベントから Slack 投稿へ直結する経路を作らない SHALL する。

#### Scenario: tight loop の構造的防止
- **WHEN** Bot が Slack に投稿し、その投稿が LETHE に取り込まれる
- **THEN** 次の Bot 実行は人間の明示呼び出しがあるまで発生しない

#### Scenario: 同一質問の繰り返し時のループ速度制約
- **WHEN** 同じ質問が繰り返し行われる
- **THEN** ループ速度は取り込み間隔と人間起点の呼び出しに制約され、自動増幅しない
