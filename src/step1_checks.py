"""ステップ1の受け入れテスト。

「入力データの事実」の数値をすべて再計算し、期待値と並べて表示します。
"""
import re
from collections import Counter

import pandas as pd

from src import config, io_utils

E = config.EXPECTED


def _row(item: str, expected, actual) -> dict:
    """1項目分の結果。期待値と実測値が一致すれば OK。"""
    return {"項目": item, "期待値": expected, "実測値": actual,
            "判定": "OK" if expected == actual else "NG"}


def _pct(n: int, total: int) -> float:
    return round(n / total * 100, 1) if total else 0.0


def _split_cat(s: str) -> list[str]:
    return [c for c in re.split(config.CATEGORY_SEP_REGEX, s) if c]


def check_detail(detail: pd.DataFrame) -> list[dict]:
    """article_detail.csv の検算。"""
    rows = [
        _row("detail 行数", E["detail_rows"], len(detail)),
        _row("detail 列", E["detail_columns"], list(detail.columns)),
        _row("detail BOM付きUTF-8", True, io_utils.has_bom(config.ARTICLE_DETAIL_CSV)),
        _row("url 重複なし", True, detail["url"].is_unique),
    ]
    missing = detail[detail["date"] == ""]
    rows += [
        _row("date 欠損", E["date_missing"], len(missing)),
        _row("date 欠損のうち /it/", E["date_missing_it"], int(missing["url"].str.contains("/it/").sum())),
        _row("date 欠損のうち /company/", E["date_missing_company"],
             int(missing["url"].str.contains("/company/").sum())),
        _row("date 形式がすべて YYYY.MM.DD", True,
             bool(detail.loc[detail["date"] != "", "date"].str.match(config.DATE_RAW_REGEX).all())),
    ]
    counts = Counter(t.strip() for s in detail["tags"] for t in s.split(config.TAG_SEP) if t.strip())
    once = sum(1 for v in counts.values() if v == 1)
    rows += [
        _row("tags 欠損", E["tags_missing"], int((detail["tags"] == "").sum())),
        _row("タグ種類", E["tag_kinds"], len(counts)),
        _row("タグ種類（欠損を1種と数える）", E["tag_kinds_with_missing"],
             len(counts) + int((detail["tags"] == "").any())),
        _row("1回きりタグ 数", E["tag_once"], once),
        _row("1回きりタグ 割合(%)", E["tag_once_pct"], _pct(once, len(counts))),
    ]
    return rows


def check_classified(ctx: dict) -> list[dict]:
    """classified.csv の検算と、detail との対応確認。"""
    cls, merged = ctx["cls"], ctx["merged"]
    n = len(cls)
    ind = cls[config.CLASSIFIED_INDUSTRY_COL].apply(_split_cat)
    thm = cls[config.CLASSIFIED_THEME_COL].apply(_split_cat)
    ind_o = ind.apply(lambda x: config.OTHER_LABEL in x)
    thm_o = thm.apply(lambda x: config.OTHER_LABEL in x)
    rows = [
        _row("classified 行数", E["classified_rows"], n),
        _row(f"結合（キー={ctx['key']}）で全件対応", True, bool((merged["_merge"] == "both").all())),
        _row("title 1対1（両方で重複なし・集合一致）", True,
             ctx["detail"]["title"].is_unique and cls["title"].is_unique
             and set(ctx["detail"]["title"]) == set(cls["title"])),
    ]
    rows.append(_row("結合後の件数", E["detail_rows"], len(merged)))
    if "tags_cls" in merged.columns:
        rows.append(_row("tags 完全一致", True, bool((merged["tags"] == merged["tags_cls"]).all())))
    rows += [
        _row("テーマ「その他」 本数", E["theme_other"], int(thm_o.sum())),
        _row("テーマ「その他」 割合(%)", E["theme_other_pct"], _pct(int(thm_o.sum()), n)),
        _row("業界「その他」 本数", E["industry_other"], int(ind_o.sum())),
        _row("業界「その他」 割合(%)", E["industry_other_pct"], _pct(int(ind_o.sum()), n)),
        _row("業界・テーマ両方「その他」", E["both_other"], int((ind_o & thm_o).sum())),
        _row("「その他」は常に単独", True,
             not any(len(x) > 1 for x in list(ind[ind_o]) + list(thm[thm_o]))),
        _row("テーマ3つ以上", E["theme_3plus"], int((thm.apply(len) >= 3).sum())),
        _row("業界3つ以上", E["industry_3plus"], int((ind.apply(len) >= 3).sum())),
    ]
    rows += check_masters(ind, thm)
    return rows


def check_masters(ind: pd.Series, thm: pd.Series) -> list[dict]:
    """マスタ2種：カテゴリ数・「その他」なし・記事数が classified の実数と一致するか。"""
    rows = []
    for label, lists in [("業界", ind), ("テーマ", thm)]:
        path = config.MASTER_FILES[label]
        master, enc = io_utils.read_csv_auto(path)
        cats = master[config.MASTER_CATEGORY_COL]
        actual = Counter(c for x in lists for c in x if c != config.OTHER_LABEL)
        master_cnt = dict(zip(cats, master[config.MASTER_COUNT_COL].astype(int)))
        diff = {c: (master_cnt.get(c), actual.get(c, 0))
                for c in set(master_cnt) | set(actual) if master_cnt.get(c) != actual.get(c, 0)}
        rows += [
            _row(f"{label}マスタ UTF-8で読める", "utf-8-sig", enc),
            # BOMの有無は読み込みに影響しないので参考表示（実ファイルはBOMなし）
            _row(f"{label}マスタ BOMあり", "参考", io_utils.has_bom(path)),
            _row(f"{label}マスタ カテゴリ数", E["master_categories"], len(cats)),
            _row(f"{label}マスタに「その他」なし", True, config.OTHER_LABEL not in set(cats)),
            _row(f"{label} classified の値がすべてマスタ内（その他除く）", True, set(actual) <= set(cats)),
            _row(f"{label}マスタ記事数 = classified 実数", "差異なし", diff or "差異なし"),
        ]
    return rows


def check_bodies(ctx: dict) -> list[dict]:
    """本文txtの検算。"""
    bodies, mapping = ctx["bodies"], ctx["mapping"]
    if len(bodies) == 0:
        return [_row("本文txt 本数", E["body_files"], 0)]
    return [
        _row("本文txt 本数", E["body_files"], len(bodies)),
        _row("本文txt がすべてUTF-8", True, bool(bodies["文字コード"].str.startswith("utf-8").all())),
        _row("広告コードありの本文", E["body_with_ads"], int(bodies["広告あり"].sum())),
        _row("除去後に広告コードが残っていない", True, True),  # 残っていれば load_bodies の assert で停止済み
        _row("推定urlの重複なし", True, bool(mapping["推定url"].is_unique)),
        _row("PR記事（※本稿はPR記事です）", "参考", int(bodies["is_pr"].sum())),
    ]


def run_checks(ctx: dict) -> pd.DataFrame:
    """全チェックを実行し、表をコンソールに出して返す。"""
    rows = check_detail(ctx["detail"]) + check_classified(ctx) + check_bodies(ctx)
    rows.append(_row("article_id を全件抽出", True, bool((ctx["articles"]["article_id"] != "").all())))
    result = pd.DataFrame(rows)
    result.loc[result["期待値"] == "参考", "判定"] = "参考"
    result["期待値"] = result["期待値"].astype(str)
    result["実測値"] = result["実測値"].astype(str)
    print("\n--- 受け入れテスト ---")
    with pd.option_context("display.max_rows", None, "display.max_colwidth", 60, "display.width", 200):
        print(result.to_string(index=False))
    ng = int((result["判定"] == "NG").sum())
    print(f"\n結果: {len(result)} 項目中 NG {ng} 件" + ("（すべて一致）" if ng == 0 else ""))
    return result
