"""パス・定数・閾値を1か所に集約する設定ファイル。

値を変えたいときは、基本的にこのファイルだけを編集すれば済むようにしています。
"""
from pathlib import Path

# ---------------------------------------------------------------
# フォルダ
# ---------------------------------------------------------------
# プロジェクトのルート（このファイル src/config.py の1つ上のフォルダ）
ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"            # 提供された元データ
BODIES_DIR = RAW_DIR / "bodies"       # 本文txt
MANUAL_DIR = DATA_DIR / "manual"      # 人が確認・修正したファイル
CACHE_DIR = ROOT_DIR / "cache"        # APIの応答キャッシュ
OUTPUTS_DIR = ROOT_DIR / "outputs"    # 出力
PROMPTS_DIR = ROOT_DIR / "src" / "prompts"

# ---------------------------------------------------------------
# 入力ファイル
# ---------------------------------------------------------------
ARTICLE_DETAIL_CSV = RAW_DIR / "biz-journal_article_detail.csv"
CLASSIFIED_CSV = RAW_DIR / "biz-journal_classified.csv"

# classified.csv（列: title,tags,業界,テーマ。url列はないので title で結合する）
CLASSIFIED_JOIN_KEY = "title"
CLASSIFIED_INDUSTRY_COL = "業界"
CLASSIFIED_THEME_COL = "テーマ"

# マスタ（列: カテゴリID,カテゴリ名,説明,主要キーワード,記事数）
MASTER_FILES = {
    "業界": RAW_DIR / "industry_master.csv",
    "テーマ": RAW_DIR / "theme_master.csv",
}
MASTER_CATEGORY_COL = "カテゴリ名"
MASTER_COUNT_COL = "記事数"

# ---------------------------------------------------------------
# 文字コード・区切り
# ---------------------------------------------------------------
READ_ENCODINGS = ["utf-8-sig", "cp932"]  # 読み込み時に試す順番
WRITE_ENCODING = "utf-8-sig"            # 出力はBOM付きUTF-8（Excelで文字化けしない）

TAG_SEP = "/"                  # タグの区切り
CATEGORY_SEP_REGEX = r"\s*,\s*"  # 業界・テーマの区切り（「, 」）
OTHER_LABEL = "その他"

# ---------------------------------------------------------------
# 日付
# ---------------------------------------------------------------
DATE_RAW_REGEX = r"^(\d{4})\.(\d{2})\.(\d{2})$"  # 元データの形式 YYYY.MM.DD
DATE_MISSING_REASON_IT = "元データ欠損（/it/記事）"
DATE_MISSING_REASON_OTHER = "元データ欠損"
TAGS_MISSING_REASON = "元データ欠損"

# ---------------------------------------------------------------
# 本文
# ---------------------------------------------------------------
# 本文とタイトルの照合（本文txtにタイトル行は含まれないため、
# 「タイトルの2文字の並びが本文中に何割現れるか」で測る）
BODY_MATCH_TOP_N = 3                 # body_mapping.csv に出す候補数
BODY_MATCH_WARN_THRESHOLD = 0.5      # 1位の類似度がこれ未満なら要確認
BODY_MATCH_WARN_MARGIN = 0.1         # 1位と2位の差がこれ未満なら要確認

PR_MARKER = "※本稿はPR記事です"

# 広告コード除去の正規表現（上から順に適用）
AD_PATTERNS = [
    r"window\.googletag[\s\S]*?\}\);",      # window.googletag 〜 }); のブロック
    r"googletag\.cmd\.push\([\s\S]*?\}\);",  # 単独の googletag.cmd.push(...) ブロック
    r"\(adsbygoogle[^\n]*?\.push\(\{\}\);?",  # (adsbygoogle = ...).push({});
]
# 除去後に残っていてはいけない語
AD_KEYWORDS = ["googletag", "adsbygoogle"]

# ---------------------------------------------------------------
# 出力ファイル
# ---------------------------------------------------------------
OUT_ARTICLES_CLEAN = OUTPUTS_DIR / "01_articles_clean.csv"
OUT_MISSING_REPORT = OUTPUTS_DIR / "01_missing_report.csv"
OUT_ACCEPTANCE_TEST = OUTPUTS_DIR / "01_acceptance_test.csv"
OUT_BODIES_CLEAN_DIR = OUTPUTS_DIR / "01_bodies_clean"  # 広告除去後の本文（article_id.txt）
BODY_MAPPING_CSV = MANUAL_DIR / "body_mapping.csv"                   # 本文⇔記事の対応（提案）
BODY_MAPPING_REVIEWED_CSV = MANUAL_DIR / "body_mapping_reviewed.csv"  # 人が確認した版
RUN_LOG = OUTPUTS_DIR / "run_log.txt"

# ---------------------------------------------------------------
# 受け入れテストの期待値（入力データの事実）
# ---------------------------------------------------------------
EXPECTED = {
    "detail_rows": 380,
    "detail_columns": ["url", "title", "date", "tags"],
    "date_missing": 12,
    "date_missing_it": 12,
    "date_missing_company": 0,
    "tags_missing": 29,
    "tag_kinds": 824,
    "tag_kinds_with_missing": 825,
    "tag_once": 666,
    "tag_once_pct": 80.8,
    "classified_rows": 380,
    "theme_other": 84,
    "theme_other_pct": 22.1,
    "industry_other": 73,
    "industry_other_pct": 19.2,
    "both_other": 24,
    "theme_3plus": 38,
    "industry_3plus": 29,
    "master_categories": 20,
    "body_files": 12,
    "body_with_ads": 10,
}

# ---------------------------------------------------------------
# OpenAI（llm_client.py）
# ---------------------------------------------------------------
DEFAULT_MODEL = "gpt-4o-mini"   # .env の OPENAI_MODEL が優先
LLM_TEMPERATURE = 0
LLM_MAX_RETRIES = 3             # 失敗時の再試行回数
LLM_RETRY_WAIT_SEC = 5          # 再試行までの待ち時間（回数に比例して延ばす）
LLM_WORKERS = 5                 # 同時に送る件数（並列実行）
LLM_RATE_LIMIT_MAX_RETRIES = 6  # レート制限（429）のときの再試行回数（通常の3回とは別に数える）
LLM_RATE_LIMIT_WAIT_SEC = 10    # レート制限のときの待ち時間（回数に比例して延ばす）
# 料金（米ドル / 100万トークン）。モデルを変えたらここも更新する
MODEL_PRICES_USD = {
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
}
USD_JPY = 150                   # 概算費用の円換算レート
# 概算トークン数：日本語混じりの文は「1文字≒1トークン」で多めに見積もる
EST_TOKENS_PER_CHAR = 1.0
OUT_ERRORS = OUTPUTS_DIR / "errors.csv"

# ---------------------------------------------------------------
# ステップ2：タグ辞書
# ---------------------------------------------------------------
# ルールで同一とみなす違い（NFKC・大文字小文字のほかに）
TAG_RULE_REMOVE_CHARS = r"[\s・･·]"           # 空白と「・」は無視して比べる
TAG_RULE_HYPHENS = "‐‑‒–—―−－"                # ハイフンの字形違いは「-」にそろえて比べる
# 部首用の文字などの特殊文字 → 通常の文字（NFKCでも直らないもの）。見つかったら追加する
TAG_CHAR_FIX = {
    "⻄": "西",  # 部首用の「⻄」（CJK RADICAL WEST TWO）→ 通常の「西」（見た目が同じなのでコードで書く）
}
TAG_AI_OUTPUT_TOKENS = 300                    # 1回の応答トークン数の見込み（費用見積もり用）
TAG_AI_MIN_CONFIDENCE = 0.0                   # これ未満のAI提案は捨てる（0なら全部残す）

TAG_DICT_SUGGESTED_CSV = OUTPUTS_DIR / "02_tag_dictionary_suggested.csv"
TAG_DICT_REVIEWED_CSV = MANUAL_DIR / "tag_dictionary_reviewed.csv"
OUT_TAGS_NORMALIZED = OUTPUTS_DIR / "02_articles_tags_normalized.csv"

# 表記方針表（統合後の表記を人が決める表。統合のときはこの表を最優先する）
TAG_POLICY_CSV = MANUAL_DIR / "tag_canonical_policy.csv"
TAG_POLICY_CANON_COL = "統合後タグ"
TAG_POLICY_ALIAS_COL = "別名（/区切り）"
TAG_POLICY_REASON_COL = "方針の理由"

# AIに渡す統合先の候補は、出現回数がこの回数以上のタグだけ（統合元は全タグ）
TAG_AI_CANDIDATE_MIN_COUNT = 2
# AIの理由にこれらの推測表現があれば、その提案は捨てる
TAG_AI_SPECULATION_REGEX = r"可能性|かもしれ|思われ|考えられ|ことがある|ことが多い|推測|おそらく|示唆"

# AIに選ばせる関係の種類（プロンプト src/prompts/tag_merge.txt と同じ並び）。
# このうち TAG_AI_KEEP_KIND だけを同義の候補として辞書に残す
TAG_AI_RELATION_KINDS = ["製品と会社", "法人の違い", "部分と全体・シリーズと回", "上位下位",
                         "似た概念", "別表記", "その他"]
TAG_AI_KEEP_KIND = "別表記"
OUT_TAG_AI_JUDGMENTS = OUTPUTS_DIR / "02_tag_ai_judgments.csv"  # AIの判定をすべて残す（確認用）

# ---------------------------------------------------------------
# ステップ3：業界・テーマの再分類
# ---------------------------------------------------------------
RECLASSIFY_BODY_CHARS = 1500          # 本文がある記事は冒頭この文字数だけAIに渡す
RECLASSIFY_CONFIDENCE_MIN = 0.7       # 確信度（AIの自己申告）がこれ未満なら要確認
RECLASSIFY_OUTPUT_TOKENS = 250        # 1回の応答トークン数の見込み（費用見積もり用）
# --limit 10 の試し実行で必ず含める記事（J-Moshi・ベビーカー・はま寿司・VPP）
TRIAL_REQUIRED_IDS = ["390973", "391258", "390369", "389541"]
# 推測表現のフィルタはステップ2と同じものを使う（config.TAG_AI_SPECULATION_REGEX）

OUT_RECLASSIFICATION = OUTPUTS_DIR / "03_reclassification.csv"
OUT_TRIAL10_REPORT = OUTPUTS_DIR / "03_trial10_report.md"

# ---------------------------------------------------------------
# ステップ4：時点表現の検出（APIなし・正規表現）
# ---------------------------------------------------------------
# 分類 → (level, 対象語)。語はここに足せば検出対象になる
TIME_EXPRESSIONS = {
    "相対年": ("要チェック", ["今年", "今年度", "年内", "昨年", "去年", "来年", "来期", "今期"]),
    "予定・告知": ("要チェック", ["開催予定", "開催決定", "開催される", "予定だ", "予定です"]),
    "状態": ("参考", ["現在", "今後", "近年", "最近"]),  # 件数が多いので参考扱い
}
TIME_CONTEXT_CHARS = 30               # 前後に何文字の文脈を付けるか
FISCAL_YEAR_START_MONTH = 4           # 「今年度」の解釈に使う年度の始まり（仮定。注記に明記する）
OUT_TIME_EXPRESSIONS = OUTPUTS_DIR / "04_time_expressions.csv"
# 受け入れテスト：相対年を含む本文（はま寿司・IVSシード・エンデバー・観光業・J-Moshi）と、
# 「開催される」を含めた場合に増える本文（AI ON LIVE）
EXPECTED_RELATIVE_YEAR_IDS = ["390369", "389538", "389692", "392011", "390973"]
EXPECTED_WITH_KAISAI_EXTRA_IDS = ["390567"]
