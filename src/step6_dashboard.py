"""ステップ6の補助：ダッシュボード用CSV（Googleスプレッドシート・Looker Studio で読める形）。

- dashboard_articles.csv：1行1記事
- dashboard_category_long.csv：1行＝記事×カテゴリ（Before/After 列つき）
  Before＝元データ、After(AI提案・未確認)＝AIの提案、After(人の確認後)＝確定が記入された軸だけ
"""
import re

import pandas as pd

from src import config

AXES = ["業界", "テーマ"]
NO_MAIN = "（主なし）"   # After で主カテゴリが空の記事（元データの「その他」と比べるための行）


def _cats(raw: str) -> list[str]:
    return [c for c in re.split(config.CATEGORY_SEP_REGEX, raw) if c]


def build_articles(df: pd.DataFrame) -> pd.DataFrame:
    """1行1記事。"""
    out = pd.DataFrame({
        "article_id": df["article_id"], "url": df["url"], "title": df["title"],
        "公開日": df["date"], "公開年月": df["date"].str[:7], "公開日欠損の理由": df["date_missing_reason"],
        "元タグ": df["tags"], "正規化タグ": df["正規化タグ"],
        "正規化タグ数": df["正規化タグ"].apply(lambda s: len([t for t in s.split(config.TAG_SEP) if t])),
        "元_業界": df["元_業界"], "元_テーマ": df["元_テーマ"],
        "提案_業界": df["提案_業界"], "提案_テーマ": df["提案_テーマ"],
        "確定_業界": df["確定_業界"], "確定_テーマ": df["確定_テーマ"],
        "新カテゴリ候補": df["新カテゴリ候補"], "確信度(AI自己申告)": df["確信度(AI自己申告)"],
        "要確認フラグ": df["要確認フラグ"],
        "本文あり": df["has_body"].map({"True": "はい"}).fillna("いいえ"),
        "PR記事": df["is_pr"].map({"True": "はい"}).fillna(""),
    })
    return out


def build_long(df: pd.DataFrame) -> pd.DataFrame:
    """1行＝記事×カテゴリ。"""
    rows = []
    for _, r in df.iterrows():
        base = {"article_id": r["article_id"], "url": r["url"], "title": r["title"],
                "公開日": r["date"], "要確認フラグ": r["要確認フラグ"]}
        for axis in AXES:
            for c in _cats(r[f"元_{axis}"]):
                rows.append({**base, "軸": axis, "カテゴリ": c, "種別": "元", "Before/After": "Before"})
            main, sub = r[f"提案_{axis}_主"], r[f"提案_{axis}_副"]
            rows.append({**base, "軸": axis, "カテゴリ": main or NO_MAIN, "種別": "主", "Before/After": "After(AI提案・未確認)"})
            if sub:
                rows.append({**base, "軸": axis, "カテゴリ": sub, "種別": "副", "Before/After": "After(AI提案・未確認)"})
            if r[f"確定_{axis}"]:
                for kind, c in zip(["主", "副"], _cats(r[f"確定_{axis}"])):
                    rows.append({**base, "軸": axis, "カテゴリ": c, "種別": kind, "Before/After": "After(人の確認後)"})
    return pd.DataFrame(rows)
