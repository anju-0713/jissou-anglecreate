"""ステップ2の補助：結果をコンソールに表示する。"""
from collections import Counter

import pandas as pd

from src import config


def tag_stats(tag_series: pd.Series) -> tuple[int, int]:
    """(タグ種類数, 1回きりタグ数)。"""
    c = Counter(t for s in tag_series for t in s.split(config.TAG_SEP) if t)
    return len(c), sum(1 for v in c.values() if v == 1)


def _show(df: pd.DataFrame, cols: list[str]) -> None:
    with pd.option_context("display.max_rows", None, "display.max_colwidth", 50, "display.width", 250):
        print(df[cols].to_string(index=False))


def print_report(dictionary: pd.DataFrame, rejected: list[str], articles: pd.DataFrame,
                 normalized: pd.DataFrame, status: str) -> None:
    """候補の件数・中身と、正規化前後のタグ数を表示する。"""
    print(f"\n出力: {config.TAG_DICT_SUGGESTED_CSV.name}（{len(dictionary)} 行）")
    for (src, rel), n in dictionary.groupby(["提案元", "relation_type"]).size().items():
        print(f"  {src} / {rel}: {n} 行")

    for src, title in [("policy", "表記方針表による統合"), ("rule", "ルールによる候補")]:
        part = dictionary[dictionary["提案元"] == src]
        if len(part):
            print(f"\n--- {title} ---")
            _show(part, ["元タグ", "出現回数", "提案_統合後タグ", "relation_type", "理由"])

    ai = dictionary[dictionary["提案元"] == "ai"]
    if len(ai):
        print("\n--- AIによる候補 ---")
        _show(ai, ["元タグ", "出現回数", "提案_統合後タグ", "確信度", "理由"])
    if rejected:
        print("\n--- 捨てたAI提案 ---")
        for r in rejected:
            print("  " + r)

    before, after = tag_stats(articles["tags"]), tag_stats(normalized["正規化タグ"])
    print(f"\n正規化タグ（{status}）: {config.OUT_TAGS_NORMALIZED.name}")
    print(f"  タグ種類 {before[0]} → {after[0]} / 1回きり {before[1]} → {after[1]}")
