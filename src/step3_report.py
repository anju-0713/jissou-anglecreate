"""ステップ3の補助：試し実行のレポート（Markdown）とコンソール表示。"""
from datetime import datetime
from pathlib import Path

import pandas as pd

from src import io_utils


def _cell(text) -> str:
    """Markdownの表に入れられるように「|」と改行を置き換える。"""
    return str(text).replace("|", "／").replace("\n", " ")


def write_trial_report(df: pd.DataFrame, path: Path) -> None:
    """元の分類と提案の比較表を Markdown で保存する。"""
    lines = [
        "# ステップ3 試し実行（10本）：元の分類と提案の比較",
        "",
        f"作成：{datetime.now():%Y-%m-%d %H:%M}　※提案はすべてAIによるもので未確認です。確信度はAIの自己申告です。",
        "",
        "| # | article_id | タイトル | 元_業界 | 提案_業界 | 元_テーマ | 提案_テーマ | 確信度 | 要確認理由 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for i, (_, r) in enumerate(df.iterrows(), start=1):
        lines.append("| " + " | ".join(_cell(x) for x in [
            i, r["article_id"], r["title"][:40], r["元_業界"], r["提案_業界"] or "（なし）",
            r["元_テーマ"], r["提案_テーマ"] or "（なし）", r["確信度(AI自己申告)"], r["要確認理由"] or "－"]) + " |")
    lines += ["", "## 記事ごとの根拠", ""]
    for i, (_, r) in enumerate(df.iterrows(), start=1):
        lines += [
            f"### {i}. {r['title']}",
            f"- URL：{r['url']}（入力：{r['入力_本文']}）",
            f"- 元：業界「{r['元_業界']}」／テーマ「{r['元_テーマ']}」",
            f"- 提案：業界「{r['提案_業界'] or 'なし'}」／テーマ「{r['提案_テーマ'] or 'なし'}」（{r['変更有無']}）",
            f"- 新カテゴリ候補：{r['新カテゴリ候補'] or 'なし'}",
            f"- 根拠：{r['根拠']}",
            f"- 根拠語：{r['根拠語']}",
            f"- 要確認：{r['要確認理由'] or 'なし'}",
            "",
        ]
    io_utils.write_text("\n".join(lines), path)
    print(f"試し実行レポート: {path.name}")


def print_summary(df: pd.DataFrame) -> None:
    """件数のまとめを表示する。"""
    n = len(df)
    print(f"\n出力: 03_reclassification.csv（{n} 行）")
    print(f"  変更あり {(df['変更有無'] == '変更あり').sum()} / 要確認 {(df['要確認フラグ'] == '要確認').sum()}"
          f" / 新カテゴリ候補あり {(df['新カテゴリ候補'] != '').sum()}")
    reasons = df["要確認理由"].str.split(" / ").explode()
    # 語の一覧や理由の本文は件数集計では落とす
    reasons = (reasons[reasons != ""].str.replace(r"^(根拠語が入力にない)：.*$", r"\1", regex=True)
               .str.replace(r"^(根拠に推測表現のため提案を除外)（.*$", r"\1", regex=True))
    if len(reasons):
        print("  要確認の内訳:")
        for k, v in reasons.value_counts().items():
            print(f"    {k}: {v}")
