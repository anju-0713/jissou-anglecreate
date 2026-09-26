"""ステップ5の補助：業界・テーマの指標。

AIには「その他」を選ばせないため、After の「その他」比率は出しません。
代わりに、元が「その他」の記事が、何に振り分けられたかを数えます。
"""
import re

import pandas as pd

from src import config, io_utils

NA = "－"
NO_REVIEW = "（reviewedなし）"
COL_B, COL_A, COL_V = "Before(元データ)", "After(a)AI提案ベース(未確認)", "After(b)人の確認後"
AXES = ["業界", "テーマ"]


def cats(raw: str) -> list[str]:
    return [c for c in re.split(config.CATEGORY_SEP_REGEX, raw) if c]


def row(kind: str, name: str, before, a, b, note: str) -> dict:
    return {"区分": kind, "指標": name, COL_B: before, COL_A: a, COL_V: b, "計算方法・注記": note}


def pct(n: int, total: int) -> float:
    return round(n / total * 100, 1)


def _load_reviewed(rec: pd.DataFrame) -> pd.DataFrame | None:
    """人が確定を記入したファイルがあれば、rec と同じ並びの表（確定_業界・確定_テーマ）にして返す。"""
    if not config.CATEGORY_REVIEWED_CSV.exists():
        return None
    rv, _ = io_utils.read_csv_auto(config.CATEGORY_REVIEWED_CSV)
    return rec[["url"]].merge(rv[["url", "確定_業界", "確定_テーマ"]], on="url", how="left").fillna("")


def _needs_check(reasons: str, axis: str) -> bool:
    """要確認の理由のうち、この軸に関係するもの（軸の指定がある理由は同じ軸のものだけ）があるか。"""
    others = {a for a in AXES if a != axis}
    return any(not any(r.startswith(f"{o}：") for o in others) for r in reasons.split(" / ") if r)


def reassignment(art: pd.DataFrame, rec: pd.DataFrame, axis: str, rv) -> list[dict]:
    """元が「その他」の記事の振り分け（マスタのカテゴリ／新カテゴリ候補／どちらもなし／うち要確認）。"""
    was_other = art[f"元_{axis}"].apply(lambda x: config.OTHER_LABEL in cats(x))
    master = rec[f"提案_{axis}_主"] != ""
    has_cand = rec["新カテゴリ候補"].apply(lambda s: any(x.startswith(f"{axis}：") for x in s.split("; ")))
    n = int(was_other.sum())
    a = int((was_other & master).sum())
    b = int((was_other & ~master & has_cand).sum())
    d = int((was_other & ~master & ~has_cand).sum())
    c = int((was_other & rec["要確認理由"].apply(lambda s: _needs_check(s, axis))).sum())
    sentence = (f"元の「その他」{n}本を、マスタのカテゴリ{a}本・新カテゴリ候補{b}本に振り分けた（うち要確認{c}本）"
                f"。振り分けなし（主カテゴリなし・候補なし）{d}本")
    if rv is None:
        review = NO_REVIEW
    else:
        fixed = rv[f"確定_{axis}"][was_other]
        done, kept = int((fixed != "").sum()), int((fixed == config.OTHER_LABEL).sum())
        review = f"確認済み{done}本（「その他」のまま{kept}本・それ以外へ{done - kept}本）／未確認{n - done}本"
    kind = "カテゴリ"
    note = "「要確認」は、その軸に関係する理由（軸の指定がない理由を含む）が付いた記事。元が「その他」の記事には「元と主カテゴリが異なる」は付けない"
    return [
        row(kind, f"{axis}：元「その他」の記事数", n, NA, NA, "元データで「その他」が付いた記事"),
        row(kind, f"{axis}：→ マスタのカテゴリに振り分け", NA, a, NO_REVIEW if rv is None else NA, "AIが主カテゴリを選んだ記事"),
        row(kind, f"{axis}：→ 新カテゴリ候補", NA, b, NO_REVIEW if rv is None else NA, "主カテゴリなしで、AIが新カテゴリ案を出した記事"),
        row(kind, f"{axis}：→ 振り分けなし", NA, d, NO_REVIEW if rv is None else NA, "主カテゴリなし・新カテゴリ候補もなし"),
        row(kind, f"{axis}：→ うち要確認", NA, c, NO_REVIEW if rv is None else NA, note),
        row(kind, f"{axis}：振り分けの文章", NA, sentence, review, "提案書用の文章。After(b)は確定の記入状況"),
    ]


def category_metrics(art: pd.DataFrame, rec: pd.DataFrame) -> list[dict]:
    """元の「その他」の振り分けと、その他の指標。"""
    n = len(art)
    rv = _load_reviewed(rec)
    no_v = NO_REVIEW if rv is None else NA
    ind_b, thm_b = art["元_業界"].apply(cats), art["元_テーマ"].apply(cats)
    ob = {"業界": ind_b.apply(lambda x: config.OTHER_LABEL in x), "テーマ": thm_b.apply(lambda x: config.OTHER_LABEL in x)}
    note = "AIには「その他」を選ばせない設計のため、After の「その他」比率は出さない（下の振り分けを参照）"
    rows = [
        row("カテゴリ", "元データの「その他」比率 業界(%)", pct(int(ob["業界"].sum()), n), NA, NA, note),
        row("カテゴリ", "元データの「その他」比率 テーマ(%)", pct(int(ob["テーマ"].sum()), n), NA, NA, note),
        row("カテゴリ", "元データの「その他」 両方(本)", int((ob["業界"] & ob["テーマ"]).sum()), NA, NA, "業界・テーマの両方が「その他」"),
    ]
    for axis in AXES:
        rows += reassignment(art, rec, axis, rv)
    ind_a = rec[["提案_業界_主", "提案_業界_副"]].ne("").sum(axis=1)
    thm_a = rec[["提案_テーマ_主", "提案_テーマ_副"]].ne("").sum(axis=1)
    confirmed = 0 if rv is None else int(((rv["確定_業界"] != "") | (rv["確定_テーマ"] != "")).sum())
    rows += [
        row("カテゴリ", "テーマ3つ以上の記事数", int((thm_b.apply(len) >= 3).sum()), int((thm_a >= 3).sum()), no_v,
            "After は「主1つ＋副は最大1つ」の設計上、最大2つ"),
        row("カテゴリ", "業界3つ以上の記事数", int((ind_b.apply(len) >= 3).sum()), int((ind_a >= 3).sum()), no_v, "同上"),
        row("カテゴリ", "新カテゴリ候補あり記事数", NA, int((rec["新カテゴリ候補"] != "").sum()), no_v, "AIが新カテゴリ案を出した記事"),
        row("カテゴリ", "要確認件数", NA, int((rec["要確認フラグ"] == "要確認").sum()), no_v,
            "確信度<0.7／新カテゴリ候補あり／元が「その他」以外で主カテゴリが異なる／照合語がマスタにない／根拠語が入力にない／推測表現 など"),
        row("カテゴリ", "確認済み記事数(人が確定を記入)", NA, 0, confirmed if rv is not None else NO_REVIEW,
            "reclassification_reviewed.csv の確定_業界・確定_テーマが記入された記事"),
    ]
    return rows
