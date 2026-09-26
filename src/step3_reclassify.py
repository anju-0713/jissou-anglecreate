"""ステップ3：業界・テーマの再分類（API）。

実行方法（Git Bash、プロジェクトのルートで）:
    python -m src.step3_reclassify --limit 10   # 試し実行（J-Moshi・ベビーカー・はま寿司・VPPを含む10本）
    python -m src.step3_reclassify --limit 20   # 上の10本＋まだ試していない10本
    python -m src.step3_reclassify              # 全件
出力はすべて「提案」です。確定_業界・確定_テーマは人が記入します。
"""
import argparse
import re
import time

import pandas as pd

from src import config, io_utils, llm_client, step3_ai, step3_report

STEP = "step3_reclassify"


def split_categories(raw: str) -> list[str]:
    return [c for c in re.split(config.CATEGORY_SEP_REGEX, raw) if c]


def load_inputs() -> pd.DataFrame:
    """ステップ1の記事一覧に、ステップ2の正規化タグと本文冒頭を付ける。"""
    for path in [config.OUT_ARTICLES_CLEAN, config.OUT_TAGS_NORMALIZED]:
        if not path.exists():
            raise SystemExit(f"先にステップ1・2を実行してください（{path.name} がありません）")
    articles, _ = io_utils.read_csv_auto(config.OUT_ARTICLES_CLEAN)
    tags, _ = io_utils.read_csv_auto(config.OUT_TAGS_NORMALIZED)
    df = articles.merge(tags[["url", "正規化タグ", "正規化の状態"]], on="url", how="left", validate="one_to_one")

    def body_head(article_id: str) -> str:
        path = config.OUT_BODIES_CLEAN_DIR / f"{article_id}.txt"
        return path.read_text(encoding="utf-8")[: config.RECLASSIFY_BODY_CHARS] if path.exists() else ""

    df["本文冒頭"] = df["article_id"].apply(body_head)
    return df


def _select_first10(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """最初の試し記事：必須の4本＋「その他」が両方の記事＋テーマ3つ以上の記事（新しい順）。"""
    required = df[df["article_id"].isin(config.TRIAL_REQUIRED_IDS)]
    missing = set(config.TRIAL_REQUIRED_IDS) - set(required["article_id"])
    if missing:
        raise SystemExit(f"試し実行の必須記事が見つかりません: {missing}")
    rest = df[~df.index.isin(required.index)].sort_values("article_id", ascending=False)
    other = rest[rest["元_業界"].str.contains(config.OTHER_LABEL) & rest["元_テーマ"].str.contains(config.OTHER_LABEL)]
    k = (n - len(required)) // 2
    many = rest[(rest["テーマ数"].astype(int) >= 3) & ~rest.index.isin(other.index)]
    picked = pd.concat([required, other.head(k), many.head(n - len(required) - k)])
    return picked.head(n)


def select_trial(df: pd.DataFrame, n: int) -> pd.DataFrame:
    """試し実行の記事。n が10を超えるときは、最初の10本に「まだ試していない記事」を足す。

    足す記事：本文がある記事を config.TRIAL_EXTRA_BODY_COUNT 本、残りは固定の乱数で選ぶ（毎回同じ）。
    """
    first = _select_first10(df, min(n, 10))
    if n <= 10:
        return first
    rest = df[~df.index.isin(first.index)]
    with_body = rest[rest["has_body"] == "True"].sample(config.TRIAL_EXTRA_BODY_COUNT, random_state=config.TRIAL_EXTRA_SEED)
    others = rest[~rest.index.isin(with_body.index)].sample(n - len(first) - len(with_body),
                                                            random_state=config.TRIAL_EXTRA_SEED)
    return pd.concat([first, with_body, others])


def to_row(a: pd.Series, checked: dict) -> dict:
    """1記事分の出力行。"""
    orig = {"業界": split_categories(a["元_業界"]), "テーマ": split_categories(a["元_テーマ"])}
    row = {"url": a["url"], "title": a["title"], "article_id": a["article_id"],
           "元_業界": a["元_業界"], "元_テーマ": a["元_テーマ"]}
    ok = not checked["excluded"]
    for label in ["業界", "テーマ"]:
        main, sub = checked["picked"][label] if ok else (None, None)
        row[f"提案_{label}"] = ", ".join(x for x in (main, sub) if x)
        row[f"提案_{label}_主"] = main or ""
        row[f"提案_{label}_副"] = sub or ""
    row["新カテゴリ候補"] = "; ".join(f"{c['axis']}：{c['name']}（{c['reason']}）"
                                for c in checked.get("candidates", [])) if ok else ""
    row["確信度(AI自己申告)"] = checked.get("confidence", "") if ok else ""
    row["根拠"] = checked.get("reason", "") if ok else ""
    row["根拠語"] = " / ".join(checked.get("evidence", [])) if ok else ""
    for label in ["業界", "テーマ"]:
        row[f"照合語_{label}"] = " / ".join(checked["matched"][label]) if ok else ""
    changed = ok and any(set(split_categories(row[f"提案_{lb}"])) != set(orig[lb]) for lb in orig)
    row["変更有無"] = ("変更あり" if changed else "変更なし") if ok else ""
    row["要確認フラグ"] = "要確認" if checked["flags"] else ""
    row["要確認理由"] = " / ".join(checked["flags"])
    row["入力_本文"] = "本文冒頭あり" if a["本文冒頭"] else "なし（タイトル・タグのみ）"
    row["入力_タグ正規化"] = a["正規化の状態"]
    row["確定_業界"] = ""
    row["確定_テーマ"] = ""
    return row


def main(limit: int | None = None, no_api: bool = False) -> None:
    io_utils.setup_console()
    start = time.time()
    print("=== ステップ3：業界・テーマの再分類 ===")
    if no_api:
        print("--no-api のためステップ3は実行しません（APIが必要です）")
        return
    df = load_inputs()
    targets = select_trial(df, limit) if limit else df
    masters = step3_ai.load_masters()
    system, schema = step3_ai.build_system_prompt(masters), step3_ai.build_schema(masters)
    prompts = [step3_ai.user_prompt(r["title"], r["正規化タグ"], r["本文冒頭"]) for _, r in targets.iterrows()]

    client = llm_client.LLMClient(STEP)
    todo = [p for (_, r), p in zip(targets.iterrows(), prompts) if not client.is_cached(r["url"], system, p, schema)]
    print(f"対象 {len(targets)} 本（うちキャッシュなし {len(todo)} 本） / モデル: {client.model}")
    if todo:
        tin, tout, usd = step3_ai.estimate(todo, system, client.model)
        print(f"  概算トークン: 入力 約{tin:,} / 出力 約{tout:,}（多めの見積もり）")
        print(f"  概算費用: {llm_client.format_cost(usd)}")
        if not llm_client.confirm("AIを実行しますか？"):
            return
    results = client.chat_json_many([(r["url"], system, p, schema) for (_, r), p in zip(targets.iterrows(), prompts)])

    rows = []
    for (_, a), p, res in zip(targets.iterrows(), prompts, results):
        orig = {"業界": split_categories(a["元_業界"]), "テーマ": split_categories(a["元_テーマ"])}
        rows.append(to_row(a, step3_ai.check_result(res, p, orig, masters)))
    out = pd.DataFrame(rows)
    io_utils.write_csv(out, config.OUT_RECLASSIFICATION)
    if limit:
        step3_report.write_trial_report(
            out, config.OUT_TRIAL20_REPORT if limit > 10 else config.OUT_TRIAL10_REPORT)
    step3_report.print_summary(out)
    io_utils.append_run_log(STEP, [
        f"--limit {limit} / 対象 {len(out)} 本 / 要確認 {(out['要確認フラグ'] == '要確認').sum()} 本",
        *client.summary_lines(),
        f"所要時間: {time.time() - start:.1f} 秒",
    ])
    for line in client.summary_lines():
        print(line)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-api", action="store_true")
    args = parser.parse_args()
    main(limit=args.limit, no_api=args.no_api)
