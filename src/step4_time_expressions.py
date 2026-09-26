"""ステップ4：時点表現の検出（APIなし・正規表現）。

本文（広告除去後）から「今年」「開催予定」などの時点表現を探し、公開日から解釈案を付けます。
公開日がない記事は解釈案を空欄にし、要確認として目立たせます。

実行方法（Git Bash、プロジェクトのルートで）:
    python -m src.step4_time_expressions
"""
import re
import time

import pandas as pd

from src import config, io_utils

STEP = "step4_time_expressions"
FLAG_NO_DATE = "★公開日欠損のため解釈不可"


def build_pattern() -> tuple[re.Pattern, dict[str, tuple[str, str]]]:
    """全対象語をまとめた正規表現（長い語を先に。「今年度」が「今年」より優先される）。"""
    info = {w: (kind, level) for kind, (level, words) in config.TIME_EXPRESSIONS.items() for w in words}
    words = sorted(info, key=len, reverse=True)
    return re.compile("|".join(map(re.escape, words))), info


def interpret(word: str, kind: str, date: str) -> tuple[str, str]:
    """公開日から解釈案を作る。戻り値は (解釈案, 注記)。推測で埋めない。"""
    if not date:
        return "", FLAG_NO_DATE
    y, m = int(date[:4]), int(date[5:7])
    fy = y if m >= config.FISCAL_YEAR_START_MONTH else y - 1
    table = {
        "今年": (f"{y}年", ""), "年内": (f"{y}年内", ""),
        "昨年": (f"{y - 1}年", ""), "去年": (f"{y - 1}年", ""), "来年": (f"{y + 1}年", ""),
        "今年度": (f"{fy}年度", f"{config.FISCAL_YEAR_START_MONTH}月始まりの年度と仮定"),
        "今期": ("", "企業の決算期が不明なため解釈しない"),
        "来期": ("", "企業の決算期が不明なため解釈しない"),
    }
    if word in table:
        return table[word]
    if kind == "予定・告知":
        return f"{date}時点の予定・告知", "公開日以降に実施済みか確認"
    return "", ""  # 状態（参考）は解釈しない


def detect(article: pd.Series, body: str, pattern, info) -> list[dict]:
    """1記事分の検出結果。"""
    rows = []
    n = config.TIME_CONTEXT_CHARS
    for m in pattern.finditer(body):
        word = m.group()
        kind, level = info[word]
        context = body[max(0, m.start() - n): m.start()] + f"【{word}】" + body[m.end(): m.end() + n]
        plan, note = interpret(word, kind, article["date"])
        rows.append({
            "url": article["url"], "title": article["title"], "article_id": article["article_id"],
            "公開日": article["date"], "表現": word, "分類": kind, "level": level,
            "前後30字の文脈": context.replace("\n", " "), "解釈案": plan, "解釈の注記": note,
            "要確認(自動)": "要確認" if note == FLAG_NO_DATE and level != "参考" else "",
            "要更新(人が記入)": "",
        })
    return rows


def check(df: pd.DataFrame) -> None:
    """受け入れテスト：相対年を含む本文が期待どおりか。"""
    rel = set(df.loc[df["分類"] == "相対年", "article_id"])
    kaisai = rel | set(df.loc[df["表現"] == "開催される", "article_id"])
    exp1 = set(config.EXPECTED_RELATIVE_YEAR_IDS)
    exp2 = exp1 | set(config.EXPECTED_WITH_KAISAI_EXTRA_IDS)
    print("\n--- 受け入れテスト ---")
    for label, actual, expected in [("相対年を含む本文", rel, exp1), ("＋「開催される」", kaisai, exp2)]:
        ok = "OK" if actual == expected else "NG"
        print(f"  {label}: 期待 {len(expected)} 本 / 実測 {len(actual)} 本 {ok}"
              + ("" if ok == "OK" else f"（多い: {actual - expected} / 足りない: {expected - actual}）"))


def main(limit: int | None = None, no_api: bool = False) -> None:
    """limit / no_api は使わない（APIなし・本文のある記事すべて）。"""
    io_utils.setup_console()
    start = time.time()
    print("=== ステップ4：時点表現の検出 ===")
    articles, _ = io_utils.read_csv_auto(config.OUT_ARTICLES_CLEAN)
    pattern, info = build_pattern()
    rows = []
    for _, a in articles[articles["has_body"] == "True"].iterrows():
        body = (config.OUT_BODIES_CLEAN_DIR / f"{a['article_id']}.txt").read_text(encoding="utf-8")
        rows += detect(a, body, pattern, info)
    df = pd.DataFrame(rows)
    # 要確認（公開日欠損）を先頭に、次に要チェック、参考は最後
    df["_順"] = df["要確認(自動)"].eq("要確認").map({True: 0, False: 1}) * 10 + df["level"].eq("参考").astype(int)
    df = df.sort_values(["_順", "公開日", "article_id"], kind="stable").drop(columns="_順")
    io_utils.write_csv(df, config.OUT_TIME_EXPRESSIONS)

    print(f"出力: {config.OUT_TIME_EXPRESSIONS.name}（{len(df)} 行 / 本文 {df['article_id'].nunique()} 本）")
    print(df.groupby(["level", "分類"]).size().to_string())
    flagged = df[df["要確認(自動)"] == "要確認"]
    if len(flagged):
        print(f"\n{FLAG_NO_DATE}：{len(flagged)} 件")
        print(flagged[["article_id", "表現", "前後30字の文脈"]].to_string(index=False))
    check(df)
    io_utils.append_run_log(STEP, [
        f"検出 {len(df)} 件（要チェック {(df['level'] == '要チェック').sum()} / 参考 {(df['level'] == '参考').sum()}）"
        f" / 公開日欠損で解釈不可 {len(flagged)} 件",
        f"所要時間: {time.time() - start:.1f} 秒 / API呼び出し: 0 回 / 概算費用: 0 円",
    ])


if __name__ == "__main__":
    main()
