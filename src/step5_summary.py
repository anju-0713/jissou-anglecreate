"""ステップ5の補助：提案書P13用のまとめ（Markdown）を書く。"""
from datetime import datetime
from pathlib import Path

import pandas as pd

from src import io_utils


def _table(df: pd.DataFrame) -> list[str]:
    cols = [c for c in df.columns if c != "区分"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for _, r in df.iterrows():
        lines.append("| " + " | ".join(str(r[c]).replace("|", "／") for c in cols) + " |")
    return lines


def write_summary(metrics: pd.DataFrame, rec: pd.DataFrame, n: int, path: Path) -> None:
    """指標表・計算方法・注記・新カテゴリ候補の一覧を書く。"""
    cand = rec[rec["新カテゴリ候補"] != ""][["article_id", "title", "新カテゴリ候補"]]
    lines = [
        "# Before/After 指標（提案書P13用）", "",
        f"作成：{datetime.now():%Y-%m-%d %H:%M}　対象：全{n}本", "",
        "## 注記（先に読んでください）", "",
        "- **After(a)はAIの提案を確認していない状態の数値です。** 人が確認するまで「確定」ではありません。",
        "- **After(b)は、人が確認したファイルがある場合だけ出します。** 「（reviewedなし）」は、まだ確認ファイルがないことを示します。",
        "- **カテゴリの After「主なし」は、元データの「その他」と同じ意味ではありません。** "
        "AIには「その他」を選ばせず、当てはまるマスタのカテゴリがないときは主カテゴリを空にして新カテゴリ候補を出させています。",
        "- **タグ整理の成果は「1回きりの割合」ではなく「表記ゆれを解消した組数」で見てください。** "
        "1回きりタグの大半は表記ゆれではなく、1記事にしか出ない固有名詞のタグです。統合でタグ種類（分母）が減るため、割合はむしろ少し上がります。",
        "- 「要確認」は、AIの提案に人が目を通す対象です。件数が多いのは、元データが「その他」の記事は主カテゴリが必ず元と異なる扱いになるためなど、"
        "判定を厳しめにしているためです。", "",
        "## 指標一覧", "", *_table(metrics), "",
        "## 計算方法", "",
        "- **Before**：`biz-journal_classified.csv` の業界・テーマ、`biz-journal_article_detail.csv` のタグ（元データそのまま）",
        "- **After(a) カテゴリ**：`03_reclassification.csv` のAI提案（主カテゴリ）。主カテゴリが空の記事を「主なし」として数える",
        "- **After(a) タグ**：表記方針表とルールの統合だけを反映（AIの同義候補は、人が採用したものだけ After(b) に入る）",
        "- **After(b) タグ**：`tag_dictionary_reviewed.csv` の「採用=Y」の行を反映",
        "- **表記ゆれを解消した組数**：元タグ→統合後タグの組のうち、実際にデータに出現し統合されたもの。特殊文字の表記修正は別に数える",
        "- **1回きりタグの割合**：1回きりタグの種類数 ÷ タグ種類数", "",
        f"## 新カテゴリ候補（{len(cand)}本）", "",
    ]
    if len(cand):
        lines += ["| article_id | タイトル | 新カテゴリ候補 |", "|---|---|---|"]
        lines += [f"| {r['article_id']} | {r['title'][:40]} | {r['新カテゴリ候補']} |" for _, r in cand.iterrows()]
    else:
        lines.append("なし")
    io_utils.write_text("\n".join(lines) + "\n", path)
