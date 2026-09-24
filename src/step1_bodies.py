"""ステップ1の補助：本文txtの広告除去と、記事との対応付け。

本文txtのファイル名は文字化けしているため、ファイル名では結合しません。
本文txtにはタイトル行が含まれないため、「タイトルの2文字の並び（バイグラム）が
本文中に何割現れるか」を類似度とし、一番高い記事を「提案」します。
"""
import re
import unicodedata
from pathlib import Path

import pandas as pd

from src import config, io_utils


def remove_ads(text: str) -> tuple[str, int]:
    """広告コードを除去する。戻り値は (除去後の本文, 除去件数)。"""
    removed = 0
    for pattern in config.AD_PATTERNS:
        text, n = re.subn(pattern, "", text)
        removed += n
    # 除去で空いた3行以上の空行を2行にまとめる
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text, removed


def has_ad_code(text: str) -> bool:
    """広告コード（googletag / adsbygoogle）を含むかどうか。"""
    return any(k in text for k in config.AD_KEYWORDS)


def _nfkc(text: str) -> str:
    """全角・半角などの表記ゆれをそろえる（照合用。出力の値は変えない）。"""
    return unicodedata.normalize("NFKC", text)


def title_similarity(title: str, body: str) -> float:
    """タイトルの2文字の並びのうち、本文中に現れるものの割合（0〜1）。"""
    title, body = _nfkc(title), _nfkc(body)
    grams = [title[i:i + 2] for i in range(len(title) - 1)]
    if not grams:
        return 0.0
    return sum(g in body for g in grams) / len(grams)


def load_bodies() -> pd.DataFrame:
    """本文txtを全部読み、広告を除去した結果を表にして返す。"""
    rows = []
    for path in sorted(config.BODIES_DIR.glob("*.txt")):
        text, enc = io_utils.read_text_auto(path)
        clean, removed = remove_ads(text)
        # 広告が残っていたら処理を止める（正規表現の見直しが必要）
        assert not has_ad_code(clean), f"広告コードが残っています: {path.name}"
        rows.append({
            "ファイル名": path.name,
            "文字コード": enc,
            "広告あり": has_ad_code(text),
            "除去前文字数": len(text),
            "除去後文字数": len(clean),
            "広告除去件数": removed,
            "is_pr": config.PR_MARKER in clean,
            "本文": clean,
        })
    return pd.DataFrame(rows)


def suggest_mapping(bodies: pd.DataFrame, articles: pd.DataFrame) -> pd.DataFrame:
    """本文ごとに類似度の上位候補を出す（人が確認するための提案）。"""
    rows = []
    for _, b in bodies.iterrows():
        scores = articles["title"].apply(lambda t: title_similarity(t, b["本文"]))
        top = scores.sort_values(ascending=False).head(config.BODY_MATCH_TOP_N)
        first, second = top.index[0], top.index[1]
        margin = scores[first] - scores[second]
        reasons = []
        if scores[first] < config.BODY_MATCH_WARN_THRESHOLD:
            reasons.append("類似度が低い")
        if margin < config.BODY_MATCH_WARN_MARGIN:
            reasons.append("次点との差が小さい")
        row = {
            "ファイル名": b["ファイル名"],
            "推定url": articles.at[first, "url"],
            "タイトル": articles.at[first, "title"],
            "類似度": round(scores[first], 3),
            "次点との差": round(margin, 3),
        }
        # 2位以下の候補（人が確認するときの選択肢）
        for rank, idx in enumerate(top.index[1:], start=2):
            row[f"候補{rank}_url"] = articles.at[idx, "url"]
            row[f"候補{rank}_タイトル"] = articles.at[idx, "title"]
            row[f"候補{rank}_類似度"] = round(scores[idx], 3)
        row["要確認"] = "要確認（" + "・".join(reasons) + "）" if reasons else ""
        row["確定url(人が記入)"] = ""
        rows.append(row)
    mapping = pd.DataFrame(rows)
    # 同じ記事に2本以上の本文が割り当たった場合も要確認にする
    dup = mapping["推定url"].duplicated(keep=False)
    mapping.loc[dup, "要確認"] = "要確認（推定urlが重複）"
    return mapping


def resolve_mapping(mapping: pd.DataFrame) -> tuple[dict[str, str], str]:
    """使う対応表を決める。reviewed があれば人の確定値を優先する。

    戻り値は ({ファイル名: url}, 状態)。状態は「確定」か「提案（未確認）」。
    """
    reviewed_path: Path = config.BODY_MAPPING_REVIEWED_CSV
    if reviewed_path.exists():
        reviewed, _ = io_utils.read_csv_auto(reviewed_path)
        col = "確定url(人が記入)"
        reviewed = reviewed[reviewed[col] != ""]
        return dict(zip(reviewed["ファイル名"], reviewed[col])), "確定"
    return dict(zip(mapping["ファイル名"], mapping["推定url"])), "提案（未確認）"
