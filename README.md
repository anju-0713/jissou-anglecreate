# Business Journal 記事整理パイプライン

株式会社アングルクリエイト（Business Journal）の過去記事380本を「探せる・つながる」状態に整えるスクリプトです。
出力は Dify アプリ、AIO対応率チェック、Looker Studio ダッシュボードで使います。

> AI の判定はすべて「提案」列です。人が確認・修正するまで「確定」扱いにしません。

## フォルダ構成

```
.env.example / .gitignore / requirements.txt / README.md
run_pipeline.py          全体実行（--step 1〜6 / --limit 10 / --no-api）
src/
  config.py              パス・定数・閾値
  io_utils.py            文字コード自動判定の読み書き
  step1_load_clean.py    ステップ1 本体
  step1_bodies.py        ステップ1 補助（本文の広告除去・記事との対応付け）
  step1_checks.py        ステップ1 受け入れテスト
  prompts/               プロンプト（フェーズ2以降）
data/raw/                提供CSV・xlsx（Gitに入れない）
data/raw/bodies/         本文txt 12本
data/manual/             人が確認・修正したファイル（*_reviewed.csv）
cache/                   APIの応答キャッシュ
outputs/                 出力
```

## セットアップ（Git Bash）

```bash
# 1. Python 3.11 以上が入っているか確認
python --version

# 2. 仮想環境を作って有効化
python -m venv .venv
source .venv/Scripts/activate

# 3. ライブラリをインストール
pip install -r requirements.txt

# 4. APIキーの設定（.env は Git に入りません）
cp .env.example .env
# .env を VS Code で開いて OPENAI_API_KEY= の後ろにキーを貼る
```

## データの置き場所

| ファイル | 置き場所 |
|---|---|
| biz-journal_article_detail.csv | data/raw/ |
| biz-journal_classified.csv | data/raw/ |
| 業界マスタ・テーママスタ（csv / xlsx） | data/raw/ |
| 本文txt 12本 | data/raw/bodies/ |

## 実行

```bash
# 仮想環境を有効化してから（毎回）
source .venv/Scripts/activate

# ステップ1：読み込みと前処理（APIなし）
python run_pipeline.py --step 1
# 単体でも実行できます
python -m src.step1_load_clean
```

### ステップ1の出力

| ファイル | 内容 |
|---|---|
| outputs/01_articles_clean.csv | 記事一覧（日付正規化・タグ分割・本文の有無・PR判定） |
| outputs/01_missing_report.csv | 記事ごとの欠損項目一覧 |
| outputs/01_acceptance_test.csv | 受け入れテストの結果（コンソールにも表示） |
| outputs/01_bodies_clean/*.txt | 広告コード除去後の本文（ファイル名は article_id） |
| data/manual/body_mapping.csv | 本文txt⇔記事の対応（**提案**。タイトルの2文字の並びが本文に何割現れるかで推定、上位3候補つき） |

### 本文と記事の対応を確認する手順

1. `data/manual/body_mapping.csv` を開き、推定url・タイトル・類似度を確認する（「要確認」の行は特に候補2・3も見る）
2. 正しい url を「確定url(人が記入)」列に書く
3. `data/manual/body_mapping_reviewed.csv` という名前で保存する
4. ステップ1を再実行すると、確認済みの対応が使われる（`body_mapping_status=確定`）

## ステップ2：タグ辞書

```bash
python run_pipeline.py --step 2 --no-api     # 表記方針表とルールだけ（APIなし）
python run_pipeline.py --step 2 --limit 10   # AIは出現回数の上位10タグだけ試す
python run_pipeline.py --step 2              # AIを全タグで実行
```

AIを使うときは、実行前に概算費用が表示され、`y` を入力したときだけ実行します。
応答は `cache/` に保存され、同じ入力なら再実行しても課金されません。

### 統合の優先順位

1. **表記方針表** `data/manual/tag_canonical_policy.csv`（人が決める。Gitで管理）
   - 列：`統合後タグ, 別名（/区切り）, 方針の理由`
   - 例：`Google, グーグル` → グーグルは Google に統合
2. **ルール**（提案元=rule）：特殊文字の表記修正、NFKC・大文字小文字・ハイフンの字形・空白・「・」の違い
3. **AI**（提案元=ai）：同義だけ。統合先の候補は出現2回以上のタグ

### 出力と確認の手順

| ファイル | 内容 |
|---|---|
| outputs/02_tag_dictionary_suggested.csv | 統合候補（提案） |
| outputs/02_articles_tags_normalized.csv | 記事ごとの正規化タグ |

1. `02_tag_dictionary_suggested.csv` の「採用(Y/N・人が記入)」に Y か N を書く（統合後を変えたいときは「修正後タグ(人が記入)」に書く）
2. `data/manual/tag_dictionary_reviewed.csv` として保存して再実行する
3. reviewed がない間は「提案ベース（未確認）」として、表記方針表と rule の行だけを当てはめる（AIの行は当てはめない）

## ステップ3：業界・テーマの再分類（API）

```bash
python run_pipeline.py --step 3 --limit 10   # 試し実行（J-Moshi・ベビーカー・はま寿司・VPPを含む10本）
python run_pipeline.py --step 3              # 全件
```

- AIの選択肢はマスタのカテゴリ名に固定（「その他」はなし）。業界・テーマとも主1つ＋副は最大1つ
- 当てはまらない場合だけ主を空にし、新カテゴリ候補を出す
- 根拠語がタイトル・タグ・本文冒頭にあるかをコードで照合。推測表現の根拠は提案ごと除外
- 出力：`outputs/03_reclassification.csv`（確定_業界・確定_テーマは人が記入）、試し実行は `outputs/03_trial10_report.md`

## ステップ4：時点表現の検出（APIなし）

```bash
python run_pipeline.py --step 4
```

- 対象語は `src/config.py` の `TIME_EXPRESSIONS` に追加できる（相対年・予定/告知は要チェック、状態の語は参考）
- 解釈案は公開日がある場合だけ（例：年内 → 2025年内）。「今年度」は4月始まりと仮定、「今期・来期」は決算期が不明なので空欄
- 公開日がない記事（J-Moshi など）は解釈案を空欄にし、「★公開日欠損のため解釈不可」として先頭に並べる
- 出力：`outputs/04_time_expressions.csv`（要更新は人が記入）

## ステップ5：Before/After 指標（APIなし）

```bash
python run_pipeline.py --step 5
```

- Before＝元データ、After(a)＝AI提案ベース（未確認）、After(b)＝人の確認後（reviewed がある場合のみ）
- After(b) のカテゴリは `data/manual/reclassification_reviewed.csv`（列：`url, 確定_業界, 確定_テーマ`）があるときだけ出る
- タグ整理の成果は「1回きりの割合」ではなく「表記ゆれを解消した組数」で見る
- 出力：`outputs/05_metrics_before_after.csv`、`outputs/05_metrics_summary.md`（提案書P13用、計算方法と注記つき）

## ステップ6：エクスポート

```bash
python run_pipeline.py --step 6            # 本文のある記事の要約をAIで作って出力
python run_pipeline.py --step 6 --no-api   # 要約は保存済み（06_summaries.csv）を使う
```

| ファイル | 用途 |
|---|---|
| outputs/dify_knowledge_articles.csv | **Difyのナレッジに入れる**（1行1記事） |
| outputs/dify_knowledge_articles.md | **Difyのナレッジに入れる**（1記事1ブロックのMarkdown。CSVと同じ内容） |
| outputs/dashboard_articles.csv | Looker Studio 用（1行1記事） |
| outputs/dashboard_category_long.csv | Looker Studio 用（1行＝記事×カテゴリ。Before/After 列つき） |
| outputs/06_summaries.csv | 要約の確認用（要確認の理由つき） |

- 要約は本文がある記事だけ。ない記事は要約を空欄にして「本文未取得」と記す（タイトルから要約は作らない）
- 別名があるタグは「Google（グーグル）」の形で出す（表記方針表による）
- 要約12本を目で確認するための一覧：`outputs/06_summaries_for_review.csv`（記事名・要約・要確認の理由・確認の記入欄）
- 業界・テーマは、人の確定 → AI提案（未確認）→ 元データ の順で使い、「分類の状態」列に書く
- 要約はAIの下書き（未確認）。数字・英字が本文にあるかはコードで確認するが、意味の取り違えは人が確認する
