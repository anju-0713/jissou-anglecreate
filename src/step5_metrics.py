"""ステップ5：Before/After 指標（APIなし）。

Before   ＝元データ
After(a) ＝AI提案ベース（未確認）。カテゴリはステップ3の提案、タグは表記方針表とルールの統合だけ
After(b) ＝人の確認後。reviewed ファイルがあるときだけ出す
  - タグ：data/manual/tag_dictionary_reviewed.csv
  - カテゴリ：data/manual/reclassification_reviewed.csv（確認済みの軸は確定値、未確認の軸は提案のまま）

実行方法（Git Bash、プロジェクトのルートで）:
    python -m src.step5_metrics
"""
import re
import time
from collections import Counter

import pandas as pd

from src import config, io_utils, step2_report, step2_tag_dictionary as s2, step5_summary, tag_policy

STEP = "step5_metrics"
NA = "－"
NO_REVIEW = "（reviewedなし）"
COL_B, COL_A, COL_V = "Before(元データ)", "After(a)AI提案ベース(未確認)", "After(b)人の確認後"


def _cats(raw: str) -> list[str]:
    return [c for c in re.split(config.CATEGORY_SEP_REGEX, raw) if c]


def _row(kind: str, name: str, before, a, b, note: str) -> dict:
    return {"区分": kind, "指標": name, COL_B: before, COL_A: a, COL_V: b, "計算方法・注記": note}


def _pct(n: int, total: int) -> float:
    return round(n / total * 100, 1)


def _reviewed_no_main(rec: pd.DataFrame) -> tuple[dict | None, int]:
    """After(b)：軸ごとの「その他／主なし」の真偽列と、確認済み記事数。reviewed がなければ (None, 0)。"""
    if not config.CATEGORY_REVIEWED_CSV.exists():
        return None, 0
    rv, _ = io_utils.read_csv_auto(config.CATEGORY_REVIEWED_CSV)
    m = rec[["url", "提案_業界_主", "提案_テーマ_主"]].merge(
        rv[["url", "確定_業界", "確定_テーマ"]], on="url", how="left").fillna("")
    out = {}
    for label in ["業界", "テーマ"]:
        # 確定が記入された軸は確定値（「その他」なら該当）、未記入の軸は提案のまま（主なしなら該当）
        out[label] = pd.Series([(f == config.OTHER_LABEL) if f != "" else p == ""
                                for f, p in zip(m[f"確定_{label}"], m[f"提案_{label}_主"])])
    out["両方"] = out["業界"] & out["テーマ"]
    return out, int(((m["確定_業界"] != "") | (m["確定_テーマ"] != "")).sum())


def category_metrics(art: pd.DataFrame, rec: pd.DataFrame) -> list[dict]:
    """「その他」比率など、業界・テーマの指標。"""
    n = len(art)
    ind_b, thm_b = art["元_業界"].apply(_cats), art["元_テーマ"].apply(_cats)
    before = {"業界": ind_b.apply(lambda x: config.OTHER_LABEL in x),
              "テーマ": thm_b.apply(lambda x: config.OTHER_LABEL in x)}
    before["両方"] = before["業界"] & before["テーマ"]
    after = {"業界": rec["提案_業界_主"] == "", "テーマ": rec["提案_テーマ_主"] == ""}   # 主カテゴリなし
    after["両方"] = after["業界"] & after["テーマ"]
    ov, confirmed = _reviewed_no_main(rec)
    no_v = NO_REVIEW if ov is None else NA

    rows = []
    for key, name in [("業界", "業界「その他」／主なし"), ("テーマ", "テーマ「その他」／主なし"),
                      ("両方", "業界・テーマ両方「その他」／主なし")]:
        b_n, a_n = int(before[key].sum()), int(after[key].sum())
        v_n = int(ov[key].sum()) if ov else NO_REVIEW
        rows += [
            _row("カテゴリ", f"{name} 本数", b_n, a_n, v_n,
                 "Before＝元データが「その他」の記事。After＝AIが主カテゴリを選べなかった記事（新カテゴリ候補あり・該当なし）"),
            _row("カテゴリ", f"{name} 比率(%)", _pct(b_n, n), _pct(a_n, n), _pct(v_n, n) if ov else NO_REVIEW,
                 f"本数 ÷ 全{n}本"),
        ]
    ind_a = rec[["提案_業界_主", "提案_業界_副"]].ne("").sum(axis=1)
    thm_a = rec[["提案_テーマ_主", "提案_テーマ_副"]].ne("").sum(axis=1)
    rows += [
        _row("カテゴリ", "テーマ3つ以上の記事数", int((thm_b.apply(len) >= 3).sum()), int((thm_a >= 3).sum()), no_v,
             "After は「主1つ＋副は最大1つ」の設計上、最大2つ"),
        _row("カテゴリ", "業界3つ以上の記事数", int((ind_b.apply(len) >= 3).sum()), int((ind_a >= 3).sum()), no_v, "同上"),
        _row("カテゴリ", "新カテゴリ候補あり記事数", NA, int((rec["新カテゴリ候補"] != "").sum()), no_v,
             "AIが新カテゴリ案を出した記事"),
        _row("カテゴリ", "要確認件数", NA, int((rec["要確認フラグ"] == "要確認").sum()), no_v,
             "確信度<0.7／新カテゴリ候補あり／元と主カテゴリが異なる／照合語がマスタにない／根拠語が入力にない／推測表現 など"),
        _row("カテゴリ", "確認済み記事数(人が確定を記入)", NA, 0, confirmed if ov else NO_REVIEW,
             "reclassification_reviewed.csv の確定_業界・確定_テーマが記入された記事"),
    ]
    return rows


def _normalized(articles: pd.DataFrame, mapping: dict, policy) -> tuple[pd.Series, dict]:
    """記事ごとの正規化タグと、実際に変わったタグの {元: 統合後}。"""
    norm = articles["tags"].apply(lambda s: config.TAG_SEP.join(dict.fromkeys(
        s2.final_tag(t, mapping, policy) for t in s.split(config.TAG_SEP) if t)))
    used = {t for s in articles["tags"] for t in s.split(config.TAG_SEP) if t}
    changed = {t: s2.final_tag(t, mapping, policy) for t in used if s2.final_tag(t, mapping, policy) != t}
    return norm, changed


def tag_metrics(art: pd.DataFrame, dic: pd.DataFrame, policy) -> list[dict]:
    """タグ種類数・1回きり・表記ゆれ解消の組数。"""
    cases = {"a": (dic, False)}
    if config.TAG_DICT_REVIEWED_CSV.exists():
        cases["b"] = (io_utils.read_csv_auto(config.TAG_DICT_REVIEWED_CSV)[0], True)
    res = {}
    for key, (table, reviewed) in cases.items():
        norm, changed = _normalized(art, s2.merge_map(table, reviewed), policy)
        rel = dict(zip(table["元タグ"], table["relation_type"]))
        kinds, once = step2_report.tag_stats(norm)
        fixes = sum(1 for t in changed if rel.get(t) == "表記修正")
        merged = {t: v for t, v in changed.items() if rel.get(t) != "表記修正"}
        res[key] = {"kinds": kinds, "once": once, "pct": _pct(once, kinds),
                    "pairs": len(merged), "groups": len(set(merged.values())), "fixes": fixes}

    def v(key, field):
        return res[key][field] if key in res else NO_REVIEW

    k0, o0 = step2_report.tag_stats(art["tags"])
    return [
        _row("タグ", "タグ種類数", k0, v("a", "kinds"), v("b", "kinds"), "タグを「/」で分けて重複を除いた種類数"),
        _row("タグ", "1回きりタグ 数", o0, v("a", "once"), v("b", "once"), "全記事で1回しか出ないタグの種類数"),
        _row("タグ", "1回きりタグ 割合(%)", _pct(o0, k0), v("a", "pct"), v("b", "pct"),
             "1回きり数 ÷ タグ種類数。1記事にしか出ない固有名詞のタグが大半のため、統合しても下がらない"),
        _row("タグ", "表記ゆれを解消した組数", NA, v("a", "pairs"), v("b", "pairs"),
             "元タグ→統合後タグの組のうち、データに出現し実際に統合されたもの（同義）。方針表・ルール・確認済みAI行の合計"),
        _row("タグ", "統合後タグの数(グループ数)", NA, v("a", "groups"), v("b", "groups"), "統合先になったタグの種類数"),
        _row("タグ", "表記修正した組数", NA, v("a", "fixes"), v("b", "fixes"),
             "特殊文字を通常の文字に直したもの（タグ種類数は減らない）"),
    ]


def main(limit: int | None = None, no_api: bool = False) -> None:
    """limit / no_api は使わない（APIなし・全件）。"""
    io_utils.setup_console()
    start = time.time()
    print("=== ステップ5：Before/After 指標 ===")
    for p in [config.OUT_ARTICLES_CLEAN, config.OUT_RECLASSIFICATION, config.TAG_DICT_SUGGESTED_CSV]:
        if not p.exists():
            raise SystemExit(f"先にステップ1〜3を実行してください（{p.name} がありません）")
    art, _ = io_utils.read_csv_auto(config.OUT_ARTICLES_CLEAN)
    rec, _ = io_utils.read_csv_auto(config.OUT_RECLASSIFICATION)
    dic, _ = io_utils.read_csv_auto(config.TAG_DICT_SUGGESTED_CSV)
    if len(rec) != len(art):
        raise SystemExit(f"03_reclassification.csv が {len(rec)} 行です"
                         f"（全 {len(art)} 行が必要です。ステップ3を全件で実行してください）")
    rec = art[["url"]].merge(rec, on="url", how="left", validate="one_to_one").fillna("")
    policy = tag_policy.load_policy()

    # 整数が「1.0」にならないよう object 型で作る（数値と「－」が混在するため）
    metrics = pd.DataFrame(category_metrics(art, rec) + tag_metrics(art, dic, policy), dtype=object)
    io_utils.write_csv(metrics, config.OUT_METRICS_CSV)
    step5_summary.write_summary(metrics, rec, len(art), config.OUT_METRICS_MD)
    with pd.option_context("display.max_rows", None, "display.max_colwidth", 34, "display.width", 250):
        print(metrics.drop(columns="計算方法・注記").to_string(index=False))
    io_utils.append_run_log(STEP, [
        f"指標 {len(metrics)} 行 / After(b) タグ: {'あり' if config.TAG_DICT_REVIEWED_CSV.exists() else 'なし'}"
        f" / カテゴリ: {'あり' if config.CATEGORY_REVIEWED_CSV.exists() else 'なし'}",
        f"所要時間: {time.time() - start:.1f} 秒 / API呼び出し: 0 回 / 概算費用: 0 円"])


if __name__ == "__main__":
    main()
