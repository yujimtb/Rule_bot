## ADDED Requirements

### Requirement: Drive フォルダ allowlist に基づくクロール
システムは指定フォルダ allowlist を起点に Google Drive のファイルを巡回 SHALL する。

#### Scenario: allowlist フォルダ配下のファイル取り込み
- **WHEN** Drive Crawler が実行される
- **THEN** 指定フォルダ allowlist 配下の Docs, Sheets, Forms, Slides, および検索可能な Drive file を LETHE Lake に Observation として投入する

#### Scenario: allowlist 外のファイルは無視
- **WHEN** ファイルが allowlist に含まれないフォルダに存在する
- **THEN** そのファイルはクロール対象にならない

### Requirement: Docs 本文取り込み
システムは Google Docs API を使用して Docs の本文、見出し、リンク、メタデータを取り込む SHALL する。

#### Scenario: Docs の本文と構造情報の取得
- **WHEN** allowlist フォルダ配下に Google Docs が存在する
- **THEN** 本文、見出し、リンク、メタデータが Observation として LETHE Lake に投入される

### Requirement: Sheets 取り込み
システムは Google Sheets API を使用して Sheets の行単位の内容、ヘッダ文脈、メタデータを取り込む SHALL する。

#### Scenario: Sheets の行内容取得
- **WHEN** allowlist フォルダ配下に Google Sheets が存在する
- **THEN** 行単位の内容、ヘッダ文脈、メタデータが Observation として LETHE Lake に投入される

### Requirement: Forms 取り込み
システムは Google Forms API を使用して Form 構造、設問、URL、回答した事実を取り込む SHALL する。

#### Scenario: Form の構造情報取得
- **WHEN** allowlist フォルダ配下に Google Forms が存在する
- **THEN** フォーム構造、設問、URL、締切や対象者の記述、回答の事実が Observation として LETHE Lake に投入される

#### Scenario: Form の個別回答内容も Lake に保存
- **WHEN** Form に個別回答が存在する
- **THEN** 個別回答内容も Lake には保存される (ただし検索コーパスへの露出は access-control-projection で制御される)

### Requirement: Slides 取り込み
システムは既存の Slides adapter を横展開して Slides の本文を取り込む SHALL する。

#### Scenario: Slides の本文取得
- **WHEN** allowlist フォルダ配下に Google Slides が存在する
- **THEN** slide または text block 単位の内容が Observation として LETHE Lake に投入される

### Requirement: revision ベース差分投入
システムは Drive file の revision 情報を見て、変更がある場合のみ新しい Observation を生成 SHALL する。

#### Scenario: 未変更ファイルのスキップ
- **WHEN** 前回クロール以降にファイルの revision が変わっていない
- **THEN** 新しい Observation は生成されない

#### Scenario: 変更済みファイルの再取り込み
- **WHEN** 前回クロール以降にファイルの revision が変わっている
- **THEN** 新しい Observation が生成される

### Requirement: Drive クロール間隔
システムのDrive 既定クロール間隔は日次と SHALL する。Slack と同様にイベント準備期間などに手動または設定変更で短縮できるようにする。

#### Scenario: 日次クロールの実行
- **WHEN** 既定設定でクロールが実行される
- **THEN** 日次の間隔でクロールが実行される

#### Scenario: クロール間隔の手動短縮
- **WHEN** 管理者がクロール間隔を短縮する設定変更を行う
- **THEN** 変更後の間隔でクロールが実行される

### Requirement: workspace-object-snapshot schema の横展開
システムは既存の Slides adapter が使っている schema:workspace-object-snapshot 相当の形を Docs, Sheets, Forms, Drive file に適用 SHALL する。

#### Scenario: 統一スキーマでの Observation 生成
- **WHEN** 各種 Google Workspace ファイルが取り込まれる
- **THEN** workspace-object-snapshot 相当の統一スキーマで Observation が生成される
