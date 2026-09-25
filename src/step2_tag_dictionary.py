"""ステップ2：タグ辞書（統合候補の提案と、正規化タグの作成）。

実行方法（Git Bash、プロジェクトのルートで）:
    python -m src.step2_tag_dictionary             # ルール＋AI（全タグ）
    python -m src.step2_tag_dictionary --no-api    # 表記方針表とルールだけ
    python -m src.step2_tag_dictionary --limit 10  # AIは出現回数の上位10タグだけ試す
"""
import argparse
import time
from collections import Counter

import pandas as pd

from src import (config, io_utils, llm_client, step2_report, step2_tag_ai, step2_tag_rules,
                 tag_policy)

STEP = "step2_tag_dictionary"
ADOPT_COL = "採用(Y/N・人が記入)"
FIX_COL = "修正後タグ(人が記入)"
STATUS_REVIEWED = "確認済み（tag_dictionary_reviewed.csv）"
STATUS_SUGGESTED = "提案ベース（未確認）"


def load_articles() -> tuple[pd.DataFrame, Counter]:
    """ステップ1の出力を読み、タグの出現回数を数える。"""
    if not config.OUT_ARTICLES_CLEAN.exists():
        raise SystemExit("先にステップ1を実行してください（outputs/01_articles_clean.csv がありません）")
    articles, _ = io_utils.read_csv_auto(config.OUT_ARTICLES_CLEAN)
    counts = Counter(t for s in articles["tags"] for t in s.split(config.TAG_SEP) if t)
    return articles, counts


def run_ai(counts: Counter, limit: int | None, policy) -> tuple[list[dict], list[str], list[str]]:
    """AI候補を作る。費用を表示して y の入力を待つ。戻り値は (行, 捨てた提案, ログ)。"""
    all_tags = step2_tag_rules.representatives(counts, policy)
    targets = all_tags[:limit] if limit else all_tags          # 統合元：全タグ（limit なら上位だけ）
    tag_list = step2_tag_ai.candidate_list(all_tags, counts)   # 統合先の候補：2回以上のタグ
    client = llm_client.LLMClient(STEP)
    system = step2_tag_ai.build_system_prompt(tag_list)
    todo = [t for t in targets
            if not client.is_cached(t, system, step2_tag_ai.user_prompt(t), step2_tag_ai.SCHEMA)]

    print(f"\nAI候補（同義のみ）：対象 {len(targets)} タグ（うちキャッシュなし {len(todo)} タグ）"
          f" / 統合先の候補 {len(tag_list)} タグ")
    if limit:
        print("  対象: " + " / ".join(targets))
    if todo:
        tin, tout, usd = step2_tag_ai.estimate(todo, system, client.model)
        print(f"  モデル: {client.model}")
        print(f"  概算トークン: 入力 約{tin:,} / 出力 約{tout:,}（多めの見積もり）")
        print(f"  概算費用: {llm_client.format_cost(usd)}")
        if not llm_client.confirm("AIを実行しますか？"):
            return [], [], ["AI候補: 未実行（y が入力されなかったため）"]
    rows, rejected = step2_tag_ai.ai_candidates(client, targets, tag_list, counts, policy)
    return rows, rejected, client.summary_lines()


def build_dictionary(rows: list[dict]) -> pd.DataFrame:
    """候補の行を表にし、人が記入する列を足す。同じ元タグは policy → rule → ai の順で1行だけ残す。"""
    cols = ["元タグ", "出現回数", "提案_統合後タグ", "関連先タグ", "提案元", "理由",
            "確信度", "relation_type"]
    df = pd.DataFrame(rows, columns=cols)
    df[ADOPT_COL] = ""
    df[FIX_COL] = ""
    df["_順"] = df["提案元"].map({"policy": 0, "rule": 1, "ai": 2})
    df = df.sort_values(["_順", "relation_type", "出現回数"], ascending=[True, True, False])
    df = df.drop_duplicates("元タグ")
    return df.drop(columns="_順").reset_index(drop=True)


def merge_map(dictionary: pd.DataFrame, reviewed: bool) -> dict[str, str]:
    """{元タグ: 統合後タグ}。

    reviewed（人の確認済み）なら 採用=Y の行だけ。未確認なら policy と rule の行だけ（AIの行は使わない）。
    """
    df = dictionary.copy()
    if reviewed:
        df = df[df[ADOPT_COL].str.strip().str.upper() == "Y"]
        df["統合先"] = df[FIX_COL].where(df[FIX_COL].str.strip() != "", df["提案_統合後タグ"])
    else:
        df = df[df["提案元"].isin(["policy", "rule"])]
        df["統合先"] = df["提案_統合後タグ"]
    df = df[df["統合先"].str.strip() != ""]
    df = df.assign(_conf=pd.to_numeric(df["確信度"], errors="coerce").fillna(0))
    df = df.sort_values("_conf", ascending=False).drop_duplicates("元タグ")  # 確信度の高い方を使う
    return dict(zip(df["元タグ"], df["統合先"]))


def resolve(tag: str, mapping: dict[str, str]) -> str:
    """A→B→C のような連鎖をたどる（循環したら止める）。"""
    seen = {tag}
    while tag in mapping and mapping[tag] not in seen:
        tag = mapping[tag]
        seen.add(tag)
    return tag


def final_tag(tag: str, mapping: dict[str, str], policy) -> str:
    """最終的な正規化タグ。表記方針表を最優先し、次に辞書の統合をたどる。"""
    canon = policy.canonical_of(tag)
    if canon:
        return canon
    merged = resolve(tag, mapping)
    return policy.canonical_of(merged) or merged


def normalize_articles(articles: pd.DataFrame, mapping: dict[str, str], policy,
                       status: str) -> pd.DataFrame:
    """記事ごとに正規化タグを作る（重複は1つにまとめ、順番は元のまま）。"""
    out = articles[["article_id", "url", "title"]].copy()
    out["元タグ"] = articles["tags"]
    norm = articles["tags"].apply(lambda s: list(dict.fromkeys(
        final_tag(t, mapping, policy) for t in s.split(config.TAG_SEP) if t)))
    out["正規化タグ"] = norm.apply(config.TAG_SEP.join)
    out["正規化タグ数"] = norm.apply(len)
    out["正規化の状態"] = status
    return out


def main(limit: int | None = None, no_api: bool = False) -> None:
    io_utils.setup_console()
    start = time.time()
    print("=== ステップ2：タグ辞書 ===")
    articles, counts = load_articles()
    policy = tag_policy.load_policy()

    # 特殊文字の表記修正 → 表記方針表 → ルール統合 → AI の順。表記修正後のタグで比べる
    fix_rows, char_warnings = step2_tag_rules.char_fix_candidates(counts)
    for w in char_warnings:
        print(f"警告：対応表にない特殊文字（自動では直しません）: {w}")
    fixed_counts = step2_tag_rules.apply_char_fix(counts)
    policy_rows = policy.alias_rows(fixed_counts)
    rule_rows = fix_rows + step2_tag_rules.rule_candidates(fixed_counts, policy)
    ai_rows, rejected, ai_log = (([], [], ["AI候補: 未実行（--no-api）"]) if no_api
                                 else run_ai(fixed_counts, limit, policy))
    dictionary = build_dictionary(policy_rows + rule_rows + ai_rows)
    io_utils.write_csv(dictionary, config.TAG_DICT_SUGGESTED_CSV)

    reviewed = config.TAG_DICT_REVIEWED_CSV.exists()
    source = io_utils.read_csv_auto(config.TAG_DICT_REVIEWED_CSV)[0] if reviewed else dictionary
    status = STATUS_REVIEWED if reviewed else STATUS_SUGGESTED
    normalized = normalize_articles(articles, merge_map(source, reviewed), policy, status)
    io_utils.write_csv(normalized, config.OUT_TAGS_NORMALIZED)

    step2_report.print_report(dictionary, rejected, articles, normalized, status)
    before, after = step2_report.tag_stats(articles["tags"]), step2_report.tag_stats(normalized["正規化タグ"])
    io_utils.append_run_log(STEP, [
        f"--limit {limit} / --no-api {no_api}",
        f"候補: policy {len(policy_rows)} 行 / rule {len(rule_rows)} 行 / ai {len(ai_rows)} 行"
        f" / 捨てたAI提案 {len(rejected)} 件",
        f"正規化: {status} / タグ種類 {before[0]} → {after[0]} / 1回きり {before[1]} → {after[1]}",
        *ai_log,
        f"所要時間: {time.time() - start:.1f} 秒",
    ])
    for line in ai_log:
        print(line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-api", action="store_true")
    args = parser.parse_args()
    main(limit=args.limit, no_api=args.no_api)
