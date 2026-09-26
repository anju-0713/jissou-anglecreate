"""ステップ5：Before/After 指標（APIなし）。

Before   ＝元データ
After(a) ＝AI提案ベース（未確認）。カテゴリはステップ3の提案、タグは表記方針表とルールの統合だけ
After(b) ＝人の確認後。reviewed ファイルがあるときだけ出す
  - タグ：data/manual/tag_dictionary_reviewed.csv
  - カテゴリ：data/manual/reclassification_reviewed.csv（確認済みの軸は確定値、未確認の軸は提案のまま）

実行方法（Git Bash、プロジェクトのルートで）:
    python -m src.step5_metrics
"""
import time
from collections import Counter

import pandas as pd

from src import config, io_utils, step2_report, step2_tag_dictionary as s2, step5_summary, tag_policy
from src.step5_category import COL_A, COL_B, COL_V, NA, NO_REVIEW, category_metrics, pct as _pct, row as _row

STEP = "step5_metrics"


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
