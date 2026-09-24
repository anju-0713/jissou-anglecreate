"""ステップ1：読み込みと前処理（APIは使わない）。

実行方法（Git Bash、プロジェクトのルートで）:
    python -m src.step1_load_clean
"""
import re
import time

import pandas as pd

from src import config, io_utils, step1_bodies, step1_checks


def extract_article_id(url: str) -> str:
    """URLの post_数字 から数字部分を取り出す。見つからなければ空欄。"""
    m = re.search(r"post_(\d+)", url)
    return m.group(1) if m else ""


def normalize_date(raw: str, url: str) -> tuple[str, str]:
    """YYYY.MM.DD を YYYY-MM-DD にする。戻り値は (日付, 空欄の理由)。"""
    if raw == "":
        reason = config.DATE_MISSING_REASON_IT if "/it/" in url else config.DATE_MISSING_REASON_OTHER
        return "", reason
    m = re.match(config.DATE_RAW_REGEX, raw)
    if not m:
        # 形式が違う値は推測で直さず、空欄にして元の値を理由に残す
        return "", f"形式不明（元値: {raw}）"
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}", ""


def split_tags(raw: str) -> list[str]:
    """タグを「/」で分けて前後空白を除く（統合はしない）。"""
    return [t.strip() for t in raw.split(config.TAG_SEP) if t.strip()]


def split_categories(raw: str) -> list[str]:
    """業界・テーマを「, 」で分ける。"""
    return [c for c in re.split(config.CATEGORY_SEP_REGEX, raw) if c]


def load_and_merge() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, str]:
    """2つのCSVを読み、結合する。戻り値は (detail, classified, 結合結果, 結合キー)。"""
    detail, _ = io_utils.read_csv_auto(config.ARTICLE_DETAIL_CSV)
    cls, _ = io_utils.read_csv_auto(config.CLASSIFIED_CSV)
    # classified には url 列がないため title で結合する（1対1でなければエラーで止まる）
    key = config.CLASSIFIED_JOIN_KEY
    merged = detail.merge(cls, on=key, how="left", suffixes=("", "_cls"),
                          validate="one_to_one", indicator=True)
    assert len(merged) == len(detail), f"結合後の件数が変わりました: {len(detail)} → {len(merged)}"
    return detail, cls, merged, key


def build_articles(merged: pd.DataFrame) -> pd.DataFrame:
    """結合結果から、きれいに整えた記事一覧を作る。"""
    df = pd.DataFrame()
    df["article_id"] = merged["url"].apply(extract_article_id)
    df["url"] = merged["url"]
    df["title"] = merged["title"]
    df["date_raw"] = merged["date"]
    dates = [normalize_date(d, u) for d, u in zip(merged["date"], merged["url"])]
    df["date"] = [d for d, _ in dates]
    df["date_missing_reason"] = [r for _, r in dates]
    df["tags_raw"] = merged["tags"]
    tag_lists = merged["tags"].apply(split_tags)
    df["tags"] = tag_lists.apply(config.TAG_SEP.join)
    df["tag_count"] = tag_lists.apply(len)
    df["tags_missing_reason"] = [config.TAGS_MISSING_REASON if not t else "" for t in tag_lists]
    df["元_業界"] = merged[config.CLASSIFIED_INDUSTRY_COL]
    df["元_テーマ"] = merged[config.CLASSIFIED_THEME_COL]
    df["業界数"] = df["元_業界"].apply(lambda s: len(split_categories(s)))
    df["テーマ数"] = df["元_テーマ"].apply(lambda s: len(split_categories(s)))
    return df


def attach_bodies(df: pd.DataFrame, bodies: pd.DataFrame,
                  file_to_url: dict[str, str], status: str) -> pd.DataFrame:
    """本文の情報を記事一覧に付け、広告除去後の本文を article_id.txt で保存する。"""
    for col in ["body_file", "body_mapping_status", "除去前文字数", "除去後文字数", "広告除去件数", "is_pr"]:
        # pandas 3 は文字列列に数値を入れられないため object 型で作る（本文なしは空欄）
        df[col] = pd.Series([""] * len(df), index=df.index, dtype=object)
    url_to_row = {u: i for i, u in enumerate(df["url"])}
    for _, b in bodies.iterrows():
        url = file_to_url.get(b["ファイル名"])
        if url not in url_to_row:
            continue
        i = url_to_row[url]
        df.loc[i, "body_file"] = b["ファイル名"]
        df.loc[i, "body_mapping_status"] = status
        df.loc[i, "除去前文字数"] = b["除去前文字数"]
        df.loc[i, "除去後文字数"] = b["除去後文字数"]
        df.loc[i, "広告除去件数"] = b["広告除去件数"]
        df.loc[i, "is_pr"] = b["is_pr"]
        io_utils.write_text(b["本文"], config.OUT_BODIES_CLEAN_DIR / f"{df.at[i, 'article_id']}.txt")
    df["has_body"] = df["body_file"] != ""
    return df


def build_missing_report(df: pd.DataFrame) -> pd.DataFrame:
    """記事ごとに、どの項目が欠けているかの一覧を作る。"""
    report = df[["article_id", "url", "title"]].copy()
    report["日付欠損"] = df["date"] == ""
    report["タグ欠損"] = df["tag_count"] == 0
    report["業界欠損"] = df["元_業界"] == ""
    report["テーマ欠損"] = df["元_テーマ"] == ""
    report["本文なし"] = ~df["has_body"]
    flags = ["日付欠損", "タグ欠損", "業界欠損", "テーマ欠損", "本文なし"]
    report["欠損項目"] = report[flags].apply(
        lambda r: "、".join(f.replace("欠損", "").replace("なし", "") for f in flags if r[f]), axis=1)
    report["欠損数"] = report[flags].sum(axis=1)
    return report


def main(limit: int | None = None, no_api: bool = False) -> dict:
    """ステップ1を実行する。limit / no_api はステップ1では使わない（全件処理する）。"""
    io_utils.setup_console()
    start = time.time()
    print("=== ステップ1：読み込みと前処理 ===")

    detail, cls, merged, key = load_and_merge()
    print(f"結合キー: {key} / 結合できなかった行: {(merged['_merge'] != 'both').sum()}")
    df = build_articles(merged)

    bodies = step1_bodies.load_bodies()
    mapping = step1_bodies.suggest_mapping(bodies, df) if len(bodies) else pd.DataFrame()
    if len(mapping):
        io_utils.write_csv(mapping, config.BODY_MAPPING_CSV)
    file_to_url, status = step1_bodies.resolve_mapping(mapping) if len(mapping) else ({}, "")
    df = attach_bodies(df, bodies, file_to_url, status)

    io_utils.write_csv(df, config.OUT_ARTICLES_CLEAN)
    missing = build_missing_report(df)
    io_utils.write_csv(missing, config.OUT_MISSING_REPORT)

    ctx = {"detail": detail, "cls": cls, "merged": merged, "key": key,
           "articles": df, "bodies": bodies, "mapping": mapping}
    results = step1_checks.run_checks(ctx)
    io_utils.write_csv(results, config.OUT_ACCEPTANCE_TEST)

    elapsed = time.time() - start
    ng = int((results["判定"] == "NG").sum())
    io_utils.append_run_log("step1_load_clean", [
        f"記事数: {len(df)} / 本文: {len(bodies)} 本（対応表: {status or 'なし'}）",
        f"受け入れテスト: {len(results)} 項目中 NG {ng}",
        f"所要時間: {elapsed:.1f} 秒 / API呼び出し: 0 回 / 概算費用: 0 円",
    ])
    print(f"\n出力: {config.OUT_ARTICLES_CLEAN.name}, {config.OUT_MISSING_REPORT.name}, "
          f"{config.BODY_MAPPING_CSV.name}（data/manual/）")
    print(f"所要時間: {elapsed:.1f} 秒")
    return ctx


if __name__ == "__main__":
    main()
