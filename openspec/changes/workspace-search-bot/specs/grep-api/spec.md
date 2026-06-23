## ADDED Requirements

### Requirement: 正規表現 grep 検索
LETHE は Access Controlled Corpus Projection の上に正規表現 grep API を提供 SHALL する。検索は ranking search ではなく、正規表現に一致するレコードをページング可能な全件結果として返す。

#### Scenario: regex パターンによる検索
- **WHEN** `落とし物|忘れ物|遺失物` のような正規表現パターンで検索が実行される
- **THEN** パターンに一致するすべてのレコードが match 結果として返される (ranking ではない)

#### Scenario: OR 表現による検索
- **WHEN** 正規表現の OR 演算子 `|` を使った検索が実行される
- **THEN** いずれかのパターンに一致するレコードがすべて返される

### Requirement: NFKC 正規化
Grep API は NFKC 正規化済みテキストに対して検索 SHALL する。原文は引用や表示用に保持する。

#### Scenario: 全角半角差の吸収
- **WHEN** 検索対象テキストに全角文字が含まれ、半角で検索する
- **THEN** NFKC 正規化により全角半角差が吸収され、一致結果が返される

#### Scenario: 原文の保持
- **WHEN** NFKC 正規化されたテキストに対して検索がヒットする
- **THEN** 検索結果の引用や表示には正規化前の原文が使用される

### Requirement: 線形時間の正規表現エンジン
Grep API は線形時間で動作する正規表現エンジンを使用 SHALL する。backreference、look-around など ReDoS につながる機能は許可しない。これは SHOULD レベルの推奨であり、実装上の制約により代替エンジンを使用してよい。

#### Scenario: ReDoS パターンの拒否
- **WHEN** backreference や look-around を含む正規表現が入力される
- **THEN** そのパターンは拒否されるか、非線形評価を行わない形で処理される

### Requirement: Cursor pagination
Grep API は cursor pagination によりすべての match 結果を取得可能に SHALL する。

#### Scenario: 結果が limit を超える場合のページング
- **WHEN** grep 結果が指定 limit (既定 100) を超える
- **THEN** next_cursor が返され、次のページの結果を取得できる

#### Scenario: 全件の走破
- **WHEN** cursor を使って繰り返しページングする
- **THEN** complete: true になるまですべての match 結果を取得できる

### Requirement: 検索結果の既定順序
Grep API の既定の表示順は日付降順と SHALL する。

#### Scenario: 日付降順での返却
- **WHEN** order パラメータを指定せずに検索する
- **THEN** 結果は date_desc (新しい順) で返される

### Requirement: Trigram index による高速化
実装上の高速化として trigram index を持ってよい SHALL する。ただし trigram index は候補絞り込みにのみ使用し、最終判定は regex の意味論とする。

#### Scenario: index による match 漏れの禁止
- **WHEN** trigram index で候補絞り込みが行われる
- **THEN** regex による最終判定で一致するすべてのレコードが返され、index によって match が欠落しない

### Requirement: Grep API のフィルタ
Grep API はソース種別、日時範囲、チャンネル、コンテナによるフィルタを受け付ける SHALL する。

#### Scenario: ソース種別でのフィルタ
- **WHEN** types フィルタに `["slack", "doc"]` が指定される
- **THEN** Slack メッセージと Google Docs のみが検索対象になる

#### Scenario: 日時範囲でのフィルタ
- **WHEN** from と to が指定される
- **THEN** その日時範囲内のレコードのみが検索対象になる

### Requirement: Grep API のレスポンス形状
Grep API のレスポンスは record_id, source_type, anchor_url, source_title, source_location, timestamp, snippet, matched_ranges, metadata, next_cursor, complete, projection_watermark を含む SHALL する。

#### Scenario: レスポンスに必要フィールドが含まれる
- **WHEN** grep 検索が実行され結果が返される
- **THEN** 各 match に record_id, source_type, anchor_url, timestamp, snippet, matched_ranges が含まれる

### Requirement: regex 実行時間の上限
Grep API は regex 実行時間に上限を設ける SHALL する。

#### Scenario: タイムアウトによる打ち切り
- **WHEN** regex の実行が設定されたタイムアウト (既定 500ms) を超える
- **THEN** 実行が打ち切られ、エラーまたは部分結果が返される
