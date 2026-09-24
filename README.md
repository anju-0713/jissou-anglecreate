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
