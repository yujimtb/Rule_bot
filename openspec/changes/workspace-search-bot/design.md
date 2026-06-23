## Context

Slack と Google Workspace に散在する情報を、チャットボットから一元検索できるようにする。データ基盤として LETHE (yujimtb/LETHE) を使用し、Search Bot は別リポジトリに新規実装する。既存の Rule_bot (yujimtb/Rule_bot) は実装パターンの参考に留め、deprecated な char-ngram RAG 実装は使わない。

システムは以下のレイヤで構成される:

```
Slack export/API       Google Drive crawl
      │                       │
      ▼                       ▼
                LETHE Lake
                    │
                    ▼
        Access Controlled Corpus Projection
                    │
                    ▼
              Grep Index/API
                    │
                    ▼
                MCP Server
                    │
                    ▼
          Search Bot Agent App
                    │
                    ▼
                  Slack
```

LETHE 側が Lake, Observation, Projection, アクセス制御, Grep API を提供し、Search Bot 側が MCP Server 経由でこれらを利用する。

## Goals / Non-Goals

**Goals:**
- Slack と Google Workspace (Docs, Sheets, Forms, Slides, Drive) の情報を grep + ReAct/tool-use で検索可能にする
- 回答には必ず一次ソース URL を付与する
- MVP で tier A (locate) と tier B (extract/filter/aggregate) を保証する
- Form 個別回答の非露出、Bot 投稿の一次ソース除外、opt-out など、プライバシーとループ防止を組み込む
- 取り込み間隔を可変にし、イベント準備期間などに短縮可能にする

**Non-Goals:**
- embedding 類似検索、RAG retriever、ランキング型検索
- per-user の Slack channel membership ベース ACL
- private channel, DM, group DM の検索
- Slack Events API によるリアルタイム取り込み
- Bot による write-back
- Event, Announcement などの業務特化 Projection
- 判断生成や優先順位づけ (tier F)

## Decisions

### D1: 検索方式は grep + ReAct (RAG ではない)
**選択:** 正規表現 grep と ReAct/tool-use による反復探索
**理由:** 検索結果が ranking ではなく match であるため、根拠の透明性が高い。embedding の品質に依存せず、regex の OR 表現で表記ゆれを吸収できる。
**代替案:** embedding 類似検索 → ranking の不透明性、チューニングコスト、hallucination リスクから不採用。

### D2: LETHE を共有データ基盤として利用
**選択:** LETHE の Lake/Projection/Grep API をデータサービスとして利用し、Search Bot は別リポジトリ
**理由:** データ保存と検索ロジックの責務を分離する。LETHE の append-only Lake と Projection の仕組みをそのまま活用できる。
**代替案:** Search Bot 内にデータストアを持つ → LETHE との重複、アクセス制御の一貫性確保が困難。

### D3: MCP による agent-tool 接続
**選択:** MCP (Model Context Protocol) Server を介して Search Bot agent と LETHE API を接続
**理由:** ツールを外部プロセスとして提供する標準的な接続方式であり、agent フレームワークとの互換性が高い。
**代替案:** 直接 HTTP クライアント → agent のツール呼び出しと統合しにくい。

### D4: NFKC 正規化
**選択:** 検索テキストに NFKC 正規化を適用
**理由:** 日本語環境で頻出する全角半角差を吸収する。原文は引用用に保持する。
**代替案:** NFC のみ → 全角半角差を吸収できない。

### D5: Trigram index による高速化
**選択:** regex の意味論を最終判定としつつ、trigram index で候補絞り込み
**理由:** grep の全文走査はコーパス増加に伴い遅くなる。trigram index は候補絞り込みに使い、match の欠落を起こさない。
**代替案:** 全文走査のみ → スケーラビリティの問題。inverted index → regex の柔軟性を損なう。

### D6: 過去回答の scaffolding 利用
**選択:** Answer Log を scaffolding として使い、一次ソースとしては使わない
**理由:** 過去の探索パスを再利用して効率化しつつ、hallucination の連鎖を防ぐ。再検証できない過去回答は根拠にしない。
**代替案:** 過去回答を一次ソースとして許可 → Bot 回答の引用連鎖による品質劣化のリスク。

### D7: Projection によるアクセス制御
**選択:** 検索前に Projection でフィルタリング (Bot 側での事後フィルタではない)
**理由:** 機密レコードが Bot に渡らないため、漏洩リスクを構造的に排除する。
**代替案:** Bot 側でフィルタ → Bot のバグや LLM の挙動で機密情報が露出するリスク。

### D8: 検索レコード粒度
**選択:** ソース種別ごとに自然な引用単位 (Slack: 1メッセージ, Docs: 見出しセクション, Sheets: 1行, Forms: 構造1件+提出イベント1件, Slides: slide/text block)
**理由:** 各ソースの自然な参照単位に合わせることで、anchor URL が意味のある粒度になる。

### D9: 設定ファイルによる運用管理
**選択:** YAML 設定ファイルで取り込み間隔、channel allowlist、Drive folder allowlist、agent 上限等を管理
**理由:** 運用パラメータの変更にコード変更を不要にする。

## Risks / Trade-offs

**[grep の表記ゆれ網羅性]** → agent が適切な OR パターンを生成できるかに依存する。SHOULD として prior_qa_search を先に参照し、過去の成功パターンを再利用する。

**[Trigram index と regex の整合性]** → index による候補絞り込みで match が欠落するリスク。MUST として regex 意味論を最終判定とし、index は候補絞り込みにのみ使う。

**[Form 回答 Sheet の除外漏れ]** → Form 回答が連携先 Sheet に保存される場合、その Sheet を明示的に除外し忘れると個別回答が露出する。exclude_form_response_sheets フラグで設定レベルで防御する。

**[opt-out の管理]** → opt-out の登録 UI と保存形式は未決。MVP では設定ファイルベースで管理し、運用しながら最適な方式を決定する。

**[agent の回答品質]** → max_tool_calls, max_wall_clock_seconds, max_records_loaded の初期値は仮。実運用で回答品質と応答時間のバランスを見て調整する。

**[Drive 共有閾値の定義]** → domain-wide, anyone-with-link, 特定 group 共有のどこまでを broad_visibility_threshold とみなすか未決。MVP では保守的に domain-wide 以上を既定とする。

## Open Questions

- Slack UX: スレッド返信にするか、チャンネル直下に返すか、進捗表示を出すか
- quota とコスト上限: ユーザーごとの回数制限、月次 token 予算、失敗時の打ち切り方
- agent loop の具体値: max_tool_calls, max_wall_clock_seconds, max_records_loaded の最適値
- Drive の共有閾値: broad_visibility_threshold の具体的な定義
- opt-out/opt-in の管理 UI: 設定ファイル、Google Sheet、管理画面、Slack command のどれ
- PDF/画像 OCR: Drive file のうち PDF や画像を OCR するか
- archived Slack channel: `^\d{3}_` に一致する archived channel を検索対象に含めるか
- 評価データセット: tier A/B の代表質問、期待 URL、正答判定方法
