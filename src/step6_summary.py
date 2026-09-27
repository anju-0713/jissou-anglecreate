"""ステップ6の補助：本文がある記事だけ、要約をAIで作る（150字程度）。

- タイトルは渡さず、本文だけを渡す（タイトルから要約を作らせないため）
- 本文にない数字・英字の語が要約に入っていたら、コードで見つけて要確認にする
"""
import re
import unicodedata

import pandas as pd

from src import config, io_utils, llm_client

STEP = "step6_export"
SCHEMA = {"type": "object", "properties": {"summary": {"type": "string"}},
          "required": ["summary"], "additionalProperties": False}
COLS = ["article_id", "url", "要約", "要約_要確認理由"]


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def check_summary(summary: str, body: str) -> list[str]:
    """要約の確認：文字数、本文にない数字・英字の語、本文にない推測表現。"""
    flags = []
    if not config.SUMMARY_MIN_CHARS <= len(summary) <= config.SUMMARY_MAX_CHARS:
        flags.append(f"文字数が{config.SUMMARY_MIN_CHARS}〜{config.SUMMARY_MAX_CHARS}字の範囲外（{len(summary)}字）")
    s, b = _norm(summary).replace(",", ""), _norm(body).replace(",", "")
    nums = [x.rstrip(".") for x in re.findall(r"\d[\d.]*", s)]
    words = re.findall(r"[a-z][a-z0-9\-]+", s)
    missing = sorted({w for w in nums + words if w not in b})
    if missing:
        flags.append("本文にない数字・英字：" + "、".join(missing))
    spec = sorted({w for w in re.findall(config.TAG_AI_SPECULATION_REGEX, summary) if w not in body})
    if spec:
        flags.append("本文にない推測表現：" + "、".join(spec))
    return flags


def summarize(targets: pd.DataFrame, client) -> pd.DataFrame:
    """targets（article_id, url, 本文 の列）の要約を並列に作る。"""
    system = (config.PROMPTS_DIR / "summarize.txt").read_text(encoding="utf-8")
    prompts = [f"本文:\n{b[: config.SUMMARY_BODY_CHARS]}" for b in targets["本文"]]
    results = client.chat_json_many([(u, system, p, SCHEMA) for u, p in zip(targets["url"], prompts)])
    rows = []
    for (_, t), res in zip(targets.iterrows(), results):
        if res is None:
            rows.append({"article_id": t["article_id"], "url": t["url"], "要約": "",
                         "要約_要確認理由": "API失敗（errors.csv を参照）"})
            continue
        summary = res["summary"].strip()
        rows.append({"article_id": t["article_id"], "url": t["url"], "要約": summary,
                     "要約_要確認理由": " / ".join(check_summary(summary, t["本文"]))})
    return pd.DataFrame(rows, columns=COLS)


def estimate(targets: pd.DataFrame, model: str) -> tuple[int, int, float | None]:
    system = (config.PROMPTS_DIR / "summarize.txt").read_text(encoding="utf-8")
    tin = sum(llm_client.estimate_tokens(system) + min(len(b), config.SUMMARY_BODY_CHARS) for b in targets["本文"])
    tout = config.SUMMARY_OUTPUT_TOKENS * len(targets)
    return tin, tout, llm_client.cost_usd(model, tin, tout)


def load_saved() -> pd.DataFrame:
    """保存済みの要約（--no-api のときに使う）。なければ空の表。"""
    if config.OUT_SUMMARIES.exists():
        return io_utils.read_csv_auto(config.OUT_SUMMARIES)[0]
    return pd.DataFrame(columns=COLS)


def load_reviewed() -> pd.DataFrame | None:
    """人が確認した結果（data/manual/summary_reviewed.csv）。なければ None。"""
    if not config.SUMMARY_REVIEWED_CSV.exists():
        return None
    return io_utils.read_csv_auto(config.SUMMARY_REVIEWED_CSV)[0]


def build_review(df: pd.DataFrame, summaries: pd.DataFrame) -> pd.DataFrame:
    """人が目で確認するための一覧（記事名・要約・要確認の理由）。確認の記入欄つき。

    data/manual/summary_reviewed.csv があれば、その確認結果・メモを反映する。
    """
    m = summaries.merge(df[["url", "title", "date"]], on="url", how="left")
    ok, memo = pd.Series([""] * len(m)), pd.Series([""] * len(m))
    reviewed = load_reviewed()
    if reviewed is not None:
        r = m[["url"]].merge(reviewed, on="url", how="left").fillna("")
        ok, memo = r["確認(OK/NG)"], r["メモ"]
    return pd.DataFrame({
        "記事名": m["title"], "URL": m["url"], "公開日": m["date"],
        "要約": m["要約"], "文字数": m["要約"].str.len(),
        "要確認の理由": m["要約_要確認理由"].replace("", "（自動チェックで指摘なし）"),
        "確認(OK/NG・人が記入)": ok, "修正後の要約・メモ(人が記入)": memo,
    })
