"""AIO対応率チェック（簡易版）。

フェーズ①〜③の出力ファイルだけを使い、OpenAI API は使いません。
「探せる・つながる」状態に整える前（Before）と、整えた後（After）を記事ごとに点検します。

前後どちらも出せる3項目（業界・テーマが「その他」以外／2回以上使われるタグがある）で
対応率を計算します。要約の有無・要確認フラグの2項目は、整理前には無かった項目なので
「後のみの参考値」として別の列に出し、対応率の合計には含めません。

実行方法（Git Bash、プロジェクトのルートで）:
    python -m src.aio_check
"""
import re
import time
from collections import Counter

import pandas as pd

from src import config, io_utils

STEP = "aio_check"
# 前後比較に使う3項目（この3つすべて満たす記事を「基本対応済み」とする）
CORE_ITEMS = ["業界その他以外", "テーマその他以外", "一般タグあり"]
# 後のみの参考項目（整理前には無かった項目。対応率の合計には含めない）
REF_ITEMS = ["要約あり", "要確認なし"]


def cats(raw: str) -> list[str]:
    """「、」区切りのカテゴリを分ける（部分一致を避けるため、完全一致の判定に使う）。"""
    return [c for c in re.split(config.CATEGORY_SEP_REGEX, raw) if c]


def not_other(raw: str) -> bool:
    """「その他」が（完全一致で）含まれていないか。「その他サービス」等は含まれない扱い。"""
    return config.OTHER_LABEL not in cats(raw)


def load_inputs() -> pd.DataFrame:
    """①〜③の出力を url で結合した表を1つ作る。"""
    needed = [config.OUT_ARTICLES_CLEAN, config.OUT_TAGS_NORMALIZED, config.OUT_RECLASSIFICATION, config.OUT_DIFY_CSV]
    missing = [p.name for p in needed if not p.exists()]
    if missing:
        raise SystemExit(f"先に必要なステップを実行してください（見つからないファイル: {', '.join(missing)}）")
    art, _ = io_utils.read_csv_auto(config.OUT_ARTICLES_CLEAN)
    tags, _ = io_utils.read_csv_auto(config.OUT_TAGS_NORMALIZED)
    rec, _ = io_utils.read_csv_auto(config.OUT_RECLASSIFICATION)
    dify, _ = io_utils.read_csv_auto(config.OUT_DIFY_CSV)
    dify = dify.rename(columns={"URL": "url", "要約": "要約(後)"})[["url", "要約(後)"]]
    df = (art[["article_id", "url", "title", "tags", "元_業界", "元_テーマ"]]
             .merge(tags[["url", "正規化タグ"]], on="url", how="left", validate="one_to_one")
             .merge(rec[["url", "提案_業界_主", "提案_テーマ_主", "確定_業界", "確定_テーマ", "要確認フラグ"]],
                    on="url", how="left", validate="one_to_one")
             .merge(dify, on="url", how="left", validate="one_to_one"))
    return df.fillna("")


def other_after(row: pd.Series, axis: str) -> bool:
    """After：確定があれば確定値、なければ提案の主カテゴリの有無で判定（AIは「その他」を選ばない設計）。"""
    if row[f"確定_{axis}"]:
        return not_other(row[f"確定_{axis}"])
    return row[f"提案_{axis}_主"] != ""


def build_articles(df: pd.DataFrame) -> pd.DataFrame:
    """記事ごとの点検結果。"""
    raw_counts = Counter(t for s in df["tags"] for t in s.split(config.TAG_SEP) if t)
    norm_counts = Counter(t for s in df["正規化タグ"] for t in s.split(config.TAG_SEP) if t)

    def has_common(tags_str: str, counts: Counter) -> bool:
        return any(counts[t] >= config.AIO_TAG_MIN_COUNT for t in tags_str.split(config.TAG_SEP) if t)

    out = pd.DataFrame({"article_id": df["article_id"], "url": df["url"], "title": df["title"]})
    out["業界その他以外_前"] = df["元_業界"].apply(not_other).astype(int)
    out["業界その他以外_後"] = df.apply(lambda r: other_after(r, "業界"), axis=1).astype(int)
    out["テーマその他以外_前"] = df["元_テーマ"].apply(not_other).astype(int)
    out["テーマその他以外_後"] = df.apply(lambda r: other_after(r, "テーマ"), axis=1).astype(int)
    out["一般タグあり_前"] = df["tags"].apply(lambda s: has_common(s, raw_counts)).astype(int)
    out["一般タグあり_後"] = df["正規化タグ"].apply(lambda s: has_common(s, norm_counts)).astype(int)

    core_b = [f"{i}_前" for i in CORE_ITEMS]
    core_a = [f"{i}_後" for i in CORE_ITEMS]
    out["対応項目数_前"] = out[core_b].sum(axis=1)
    out["対応項目数_後"] = out[core_a].sum(axis=1)
    out["対応率_前(%)"] = (out["対応項目数_前"] / len(CORE_ITEMS) * 100).round(1)
    out["対応率_後(%)"] = (out["対応項目数_後"] / len(CORE_ITEMS) * 100).round(1)
    out["基本対応済み_前"] = (out["対応項目数_前"] == len(CORE_ITEMS)).astype(int)
    out["基本対応済み_後"] = (out["対応項目数_後"] == len(CORE_ITEMS)).astype(int)

    # 参考値（後のみ。対応項目数・対応率には含めない）
    out["要約あり_後_参考"] = (df["要約(後)"] != "").astype(int)
    out["要確認なし_後_参考"] = (df["要確認フラグ"] != "要確認").astype(int)
    return out


def build_summary(art: pd.DataFrame, n: int) -> pd.DataFrame:
    """項目ごとの対応率（前・後）。"""
    rows = []

    def add(name, before_col, after_col, note):
        b = "" if before_col is None else int(art[before_col].sum())
        a = int(art[after_col].sum())
        bp = "" if before_col is None else round(b / n * 100, 1)
        ap = round(a / n * 100, 1)
        diff = "" if before_col is None else round(ap - bp, 1)
        rows.append({"項目": name, "前_該当数": b, "前_対応率(%)": bp,
                     "後_該当数": a, "後_対応率(%)": ap, "前後差(pt)": diff, "注記": note})

    add("業界が「その他」以外", "業界その他以外_前", "業界その他以外_後",
        "後はAI提案・未確認を含む（03_reclassification.csv の提案_業界_主。確定_業界は未記入）")
    add("テーマが「その他」以外", "テーマその他以外_前", "テーマその他以外_後",
        "後はAI提案・未確認を含む（03_reclassification.csv の提案_テーマ_主。確定_テーマは未記入）")
    add(f"2回以上使われるタグが1つ以上（{config.AIO_TAG_MIN_COUNT}回以上）", "一般タグあり_前", "一般タグあり_後",
        "正規化タグは人が確認済み（tag_dictionary_reviewed.csv を反映）")
    add("基本対応済み（上の3項目すべて）", "基本対応済み_前", "基本対応済み_後",
        "3項目の対応率(%)は基本対応済みの本数÷全記事数")
    add("【参考・後のみ】要約がある", None, "要約あり_後_参考",
        "整理前には無かった項目（合計には含めない）。本文がある12本のみ対象。要約は人が確認済み（summary_reviewed.csv）")
    add("【参考・後のみ】要確認フラグが立っていない", None, "要確認なし_後_参考",
        "整理前には無かった項目（合計には含めない）。要確認フラグ自体がAI提案・未確認の分類に基づく判定")
    return pd.DataFrame(rows)


def main(limit: int | None = None, no_api: bool = False) -> None:
    io_utils.setup_console()
    start = time.time()
    print("=== AIO対応率チェック（簡易版・APIなし） ===")
    df = load_inputs()
    art = build_articles(df)
    io_utils.write_csv(art, config.OUT_AIO_ARTICLES)
    summary = build_summary(art, len(art))
    io_utils.write_csv(summary, config.OUT_AIO_SUMMARY)

    with pd.option_context("display.max_colwidth", 60, "display.width", 220):
        print(summary.drop(columns="注記").to_string(index=False))
    print(f"\n出力: {config.OUT_AIO_ARTICLES.name}（{len(art)} 行）, {config.OUT_AIO_SUMMARY.name}（{len(summary)} 行）")
    io_utils.append_run_log(STEP, [
        f"対象 {len(art)} 本 / 基本対応済み 前{int(art['基本対応済み_前'].sum())}本→後{int(art['基本対応済み_後'].sum())}本",
        f"所要時間: {time.time() - start:.1f} 秒 / API呼び出し: 0 回 / 概算費用: 0 円",
    ])


if __name__ == "__main__":
    main()
