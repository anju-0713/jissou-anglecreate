"""ステップ6：エクスポート（Dify用・ダッシュボード用）。

実行方法（Git Bash、プロジェクトのルートで）:
    python -m src.step6_export             # 要約をAIで作って出力
    python -m src.step6_export --no-api    # 要約は保存済み（06_summaries.csv）を使う

- 要約は本文がある記事だけ。本文がない記事は要約を空欄にし「本文未取得」と記す
- 別名があるタグは「Google（グーグル）」の形で出す（表記方針表による）
- 業界・テーマは、人の確定 → AI提案（未確認）→ 元データ の順で使い、どれを使ったかを「分類の状態」に書く
"""
import argparse
import re
import time

import pandas as pd

from src import config, io_utils, llm_client, step6_dashboard, step6_summary, tag_policy

STEP = "step6_export"
REC_COLS = ["url", "提案_業界", "提案_テーマ", "提案_業界_主", "提案_業界_副", "提案_テーマ_主", "提案_テーマ_副",
            "新カテゴリ候補", "確信度(AI自己申告)", "要確認フラグ", "要確認理由"]


def load_all() -> pd.DataFrame:
    """記事一覧に、正規化タグ・再分類の提案・（あれば）人の確定を付ける。"""
    for p in [config.OUT_ARTICLES_CLEAN, config.OUT_TAGS_NORMALIZED, config.OUT_RECLASSIFICATION]:
        if not p.exists():
            raise SystemExit(f"先にステップ1〜3を実行してください（{p.name} がありません）")
    art, _ = io_utils.read_csv_auto(config.OUT_ARTICLES_CLEAN)
    tags, _ = io_utils.read_csv_auto(config.OUT_TAGS_NORMALIZED)
    rec, _ = io_utils.read_csv_auto(config.OUT_RECLASSIFICATION)
    if len(rec) != len(art):
        raise SystemExit(f"03_reclassification.csv が {len(rec)} 行です（全 {len(art)} 行が必要です）")
    df = (art.merge(tags[["url", "正規化タグ", "正規化の状態"]], on="url", how="left", validate="one_to_one")
             .merge(rec[REC_COLS], on="url", how="left", validate="one_to_one"))
    if config.CATEGORY_REVIEWED_CSV.exists():
        rv, _ = io_utils.read_csv_auto(config.CATEGORY_REVIEWED_CSV)
        df = df.merge(rv[["url", "確定_業界", "確定_テーマ"]], on="url", how="left")
    for col in ["確定_業界", "確定_テーマ"]:
        if col not in df.columns:
            df[col] = ""
    return df.fillna("")


def final_category(row: pd.Series, label: str) -> tuple[str, str]:
    """(カテゴリ, 状態)。人の確定 → AI提案（未確認）→ 元データ の順。"""
    if row[f"確定_{label}"]:
        return row[f"確定_{label}"], "確定"
    if row[f"提案_{label}"]:
        return row[f"提案_{label}"], "AI提案（未確認）"
    return row[f"元_{label}"], "元データ（AI提案なし）"


def display_tags(tags: str, policy) -> str:
    """別名があるタグを「Google（グーグル）」の形にする。"""
    return config.TAG_SEP.join(policy.display_name(t) for t in tags.split(config.TAG_SEP) if t)


def build_dify(df: pd.DataFrame, summaries: pd.DataFrame, policy) -> pd.DataFrame:
    """Dify用の表（タイトル, URL, 公開日, 正規化タグ, 業界, テーマ, 要約, 要約の根拠 ＋ 状態・備考）。"""
    summ = summaries.set_index("url") if len(summaries) else pd.DataFrame(columns=step6_summary.COLS).set_index("url")
    reviewed = step6_summary.load_reviewed()
    reviewed_ok = set(reviewed.loc[reviewed["確認(OK/NG)"].str.upper() == "OK", "url"]) if reviewed is not None else set()
    rows = []
    for _, r in df.iterrows():
        ind, ind_state = final_category(r, "業界")
        thm, thm_state = final_category(r, "テーマ")
        has_body = r["has_body"] == "True"
        s = summ.loc[r["url"]] if r["url"] in summ.index else None
        summary = s["要約"] if (has_body and s is not None) else ""
        notes = []
        if not has_body:
            notes.append("本文未取得")
        elif not summary:
            notes.append("要約未作成")
        elif r["url"] in reviewed_ok:
            notes.append("要約は人が確認済み")
        else:
            notes.append("要約はAI作成（未確認）")
            if s["要約_要確認理由"]:
                notes.append("要約要確認：" + s["要約_要確認理由"])
        if r["date_missing_reason"]:
            notes.append(f"公開日：{r['date_missing_reason']}")
        if r["is_pr"] == "True":
            notes.append("PR記事")
        rows.append({
            "タイトル": r["title"], "URL": r["url"], "公開日": r["date"],
            "正規化タグ": display_tags(r["正規化タグ"], policy), "業界": ind, "テーマ": thm,
            "要約": summary, "要約の根拠(本文/なし)": "本文" if summary else "なし",
            "分類の状態": f"業界:{ind_state} / テーマ:{thm_state}",
            "要確認(分類)": r["要確認フラグ"], "備考": " / ".join(notes),
        })
    return pd.DataFrame(rows)


def _summary_state(note: str) -> str:
    """備考から「要約の状態」の1行分を取り出す（CSVの備考欄と同じ内容）。"""
    if "本文未取得" in note:
        return "なし（本文未取得）"
    if "要約未作成" in note:
        return "なし（要約未作成）"
    if "人が確認済み" in note:
        return "人が確認済み"
    return "AI作成（未確認）"


def build_markdown(dify: pd.DataFrame) -> str:
    """1記事1ブロックのMarkdown（Dify取り込み用）。"""
    blocks = []
    for _, r in dify.iterrows():
        summary = r["要約"] if r["要約"] else "（本文未取得）" if "本文未取得" in r["備考"] else "（要約未作成）"
        blocks.append("\n".join([
            f"## {r['タイトル']}", "",
            f"- URL: {r['URL']}",
            f"- 公開日: {r['公開日'] or '（元データ欠損）'}",
            f"- 正規化タグ: {r['正規化タグ'].replace(config.TAG_SEP, '、') or '（なし）'}",
            f"- 業界: {r['業界']}",
            f"- テーマ: {r['テーマ']}",
            f"- 分類の状態: {r['分類の状態']}",
            f"- 要約: {summary}",
            f"- 要約の根拠: {r['要約の根拠(本文/なし)']}",
            f"- 要約の状態: {_summary_state(r['備考'])}",
        ]))
    return "\n\n---\n\n".join(blocks) + "\n"


def main(limit: int | None = None, no_api: bool = False) -> None:
    io_utils.setup_console()
    start = time.time()
    print("=== ステップ6：エクスポート ===")
    df = load_all()
    policy = tag_policy.load_policy()

    # 要約：本文がある記事だけ
    targets = df[df["has_body"] == "True"][["article_id", "url"]].copy()
    targets["本文"] = [(config.OUT_BODIES_CLEAN_DIR / f"{a}.txt").read_text(encoding="utf-8") for a in targets["article_id"]]
    if limit:
        targets = targets.head(limit)
    log = []
    if no_api:
        summaries = step6_summary.load_saved()
        log.append("要約: 保存済みを使用（--no-api）")
    else:
        client = llm_client.LLMClient(STEP)
        todo = [u for u in targets["url"] if not client.is_cached(u, *_request_key(targets, u))]
        print(f"要約：本文のある {len(targets)} 本（うちキャッシュなし {len(todo)} 本） / モデル: {client.model}")
        if todo:
            tin, tout, usd = step6_summary.estimate(targets[targets["url"].isin(todo)], client.model)
            print(f"  概算トークン: 入力 約{tin:,} / 出力 約{tout:,} / 概算費用: {llm_client.format_cost(usd)}")
            if not llm_client.confirm("AIを実行しますか？"):
                return
        summaries = step6_summary.summarize(targets, client)
        io_utils.write_csv(summaries, config.OUT_SUMMARIES)
        log += client.summary_lines()

    dify = build_dify(df, summaries, policy)
    io_utils.write_csv(dify, config.OUT_DIFY_CSV)
    io_utils.write_text(build_markdown(dify), config.OUT_DIFY_MD)
    review = step6_summary.build_review(df, summaries)
    io_utils.write_csv(review, config.OUT_SUMMARY_REVIEW)
    dash = step6_dashboard.build_articles(df)
    long = step6_dashboard.build_long(df)
    io_utils.write_csv(dash, config.OUT_DASH_ARTICLES)
    io_utils.write_csv(long, config.OUT_DASH_LONG)

    n_sum = int((dify["要約"] != "").sum())
    flagged = int((summaries["要約_要確認理由"] != "").sum()) if len(summaries) else 0
    print(f"\n出力（outputs/）:\n  {config.OUT_DIFY_CSV.name}（{len(dify)} 行 / 要約あり {n_sum} 本 / 要約要確認 {flagged} 本）"
          f"\n  {config.OUT_DIFY_MD.name}\n  {config.OUT_DASH_ARTICLES.name}（{len(dash)} 行）"
          f"\n  {config.OUT_DASH_LONG.name}（{len(long)} 行）\n  {config.OUT_SUMMARIES.name}")
    for line in log:
        print(line)
    io_utils.append_run_log(STEP, [f"記事 {len(dify)} 本 / 要約 {n_sum} 本（要確認 {flagged}）/ ダッシュボード long {len(long)} 行",
                                   *log, f"所要時間: {time.time() - start:.1f} 秒"])


def _request_key(targets: pd.DataFrame, url: str) -> tuple[str, str, dict]:
    """キャッシュ確認用の (system, user, schema)。summarize と同じ組み立て。"""
    system = (config.PROMPTS_DIR / "summarize.txt").read_text(encoding="utf-8")
    body = targets.loc[targets["url"] == url, "本文"].iloc[0]
    return system, f"本文:\n{body[: config.SUMMARY_BODY_CHARS]}", step6_summary.SCHEMA


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-api", action="store_true")
    args = parser.parse_args()
    main(limit=args.limit, no_api=args.no_api)
