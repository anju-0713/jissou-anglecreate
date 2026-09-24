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
