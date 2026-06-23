## ADDED Requirements

### Requirement: 共通コーパス方針
MVP の検索コーパスは共通コーパスと SHALL する。質問者ごとの可視範囲分離は行わない。

#### Scenario: 全ユーザーが同一コーパスを検索
- **WHEN** 異なるユーザーが同じ検索クエリを実行する
- **THEN** 両者は同一の検索結果を受け取る

### Requirement: Projection による事前フィルタリング
アクセス制御は検索前に Projection で実施 SHALL する。Bot 側で機密レコードを受け取ってから捨てる設計にはしない。

#### Scenario: 機密レコードの除外
- **WHEN** Access Controlled Corpus Projection が生成される
- **THEN** 検索コーパスに露出すべきでないレコードは Projection の段階で除外され、Bot に渡らない

### Requirement: Slack チャンネルルール
Slack メッセージは以下の条件をすべて満たす場合のみ検索コーパスに露出 SHALL する: is_public_channel == true AND channel_name matches ^\d{3}_ AND author is not bot AND author is not opted_out_person。

#### Scenario: 公開チャンネルかつ命名規則一致のメッセージ
- **WHEN** public channel で channel 名が `123_event` のようにに数字三桁と `_` で始まるメッセージがある
- **THEN** そのメッセージは検索コーパスに露出する

#### Scenario: 命名規則不一致のチャンネル除外
- **WHEN** public channel で channel 名が `general` のように `^\d{3}_` に一致しない
- **THEN** そのチャンネルのメッセージは検索コーパスに露出しない

#### Scenario: 個人チャンネルの原則除外
- **WHEN** 個人が立てたチャンネルで opt-in がされていない
- **THEN** そのチャンネルは検索対象に含まれない

#### Scenario: Bot 投稿の除外
- **WHEN** メッセージの author が bot である
- **THEN** そのメッセージは一次検索コーパスから除外される

#### Scenario: opt-out 人物の投稿除外
- **WHEN** メッセージの author が opt-out 登録されている
- **THEN** そのメッセージは検索コーパスから除外される

### Requirement: Drive ファイルルール
Drive file は以下の条件をすべて満たす場合のみ検索コーパスに露出 SHALL する: file is under allowed_folder AND file sharing level satisfies broad_visibility_threshold AND owner/author is not opted_out_person AND file is not explicitly excluded。

#### Scenario: allowlist フォルダ配下かつ共有閾値を満たすファイル
- **WHEN** ファイルが allowlist フォルダ配下にあり、共有レベルが broad_visibility_threshold を満たす
- **THEN** そのファイルは検索コーパスに露出する

#### Scenario: allowlist 配下だが共有閾値を満たさないファイル
- **WHEN** ファイルが allowlist フォルダ配下にあるが、共有レベルが broad_visibility_threshold を満たさない
- **THEN** そのファイルは検索コーパスに露出しない (個人ファイルの誤配置に対する二重防御)

#### Scenario: opt-out 人物の Drive ファイル除外
- **WHEN** ファイルの owner/author が opt-out 登録されている
- **THEN** そのファイルは検索コーパスから除外される

### Requirement: Form 回答の扱い
Form の個別回答内容は検索コーパスに露出しない SHALL とする。ただし誰がいつ回答したかという事実は露出する。

#### Scenario: Form 構造と回答事実の露出
- **WHEN** Form が検索コーパスに含まれる
- **THEN** タイトル、説明、設問、URL、締切や対象者の記述、誰が回答したか、いつ回答したかが露出する

#### Scenario: Form 個別回答内容の非露出
- **WHEN** Form の個別回答が Lake に存在する
- **THEN** その回答内容は検索コーパスに露出しない

#### Scenario: Form 回答連携 Sheet の除外
- **WHEN** Form 回答が連携先 Sheet に保存されている
- **THEN** その回答 Sheet は明示的に検索コーパスから除外される
