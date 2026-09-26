"""ステップ3の補助：AIへの入力の組み立てと、応答の検証。

- 選択肢（enum）はマスタのカテゴリ名に固定。「その他」は入れない
- 根拠語がタイトル・タグ・本文冒頭に本当にあるかをコードで確かめる
- 根拠に推測表現があれば提案を除外する（ステップ2と同じフィルタ）
"""
import re
import unicodedata

import pandas as pd

from src import config, io_utils, llm_client

AXES = {"業界": "industry", "テーマ": "theme"}


def load_masters() -> dict[str, pd.DataFrame]:
    """{"業界": 表, "テーマ": 表}。"""
    return {label: io_utils.read_csv_auto(path)[0] for label, path in config.MASTER_FILES.items()}


def _master_text(master: pd.DataFrame) -> str:
    return "\n".join(f"- {r['カテゴリ名']}：{r['説明']}／{r['主要キーワード']}" for _, r in master.iterrows())


def build_system_prompt(masters: dict[str, pd.DataFrame]) -> str:
    template = (config.PROMPTS_DIR / "reclassify.txt").read_text(encoding="utf-8")
    return (template.replace("{industry_master}", _master_text(masters["業界"]))
                    .replace("{theme_master}", _master_text(masters["テーマ"])))


def build_schema(masters: dict[str, pd.DataFrame]) -> dict:
    """選択肢をマスタのカテゴリ名に固定したJSONスキーマ。"""
    def nullable(label):
        names = list(masters[label]["カテゴリ名"])
        return {"anyOf": [{"type": "string", "enum": names}, {"type": "null"}]}

    props = {}
    for label, key in AXES.items():
        props[f"{key}_main"] = nullable(label)
        props[f"{key}_sub"] = nullable(label)
    props["new_category_candidates"] = {"type": "array", "items": {
        "type": "object",
        "properties": {"axis": {"type": "string", "enum": list(AXES)},
                       "name": {"type": "string"}, "reason": {"type": "string"}},
        "required": ["axis", "name", "reason"], "additionalProperties": False}}
    props["evidence_words"] = {"type": "array", "items": {"type": "string"}}
    props["confidence"] = {"type": "number"}
    props["reason"] = {"type": "string"}
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def user_prompt(title: str, tags: str, body_head: str) -> str:
    tag_text = " / ".join(t for t in tags.split(config.TAG_SEP) if t) or "なし"
    return f"タイトル: {title}\nタグ: {tag_text}\n本文冒頭: {body_head or 'なし'}"


def estimate(prompts: list[str], system: str, model: str) -> tuple[int, int, float | None]:
    tin = sum(llm_client.estimate_tokens(system + p) for p in prompts)
    tout = config.RECLASSIFY_OUTPUT_TOKENS * len(prompts)
    return tin, tout, llm_client.cost_usd(model, tin, tout)


def _norm(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def check_result(result: dict | None, source_text: str, original: dict[str, list[str]],
                 masters: dict[str, pd.DataFrame]) -> dict:
    """AIの応答を検証し、提案と要確認の理由をまとめる。"""
    if result is None:
        return {"flags": ["API失敗（errors.csv を参照）"], "excluded": True}
    flags = []
    if re.search(config.TAG_AI_SPECULATION_REGEX, result["reason"]):
        return {"flags": [f"根拠に推測表現のため提案を除外（{result['reason']}）"], "excluded": True}

    picked = {}
    for label, key in AXES.items():
        main, sub = result[f"{key}_main"], result[f"{key}_sub"]
        if sub == main:
            sub = None
        if main is None and sub is not None:
            flags.append(f"{label}：主なしで副あり（副は使わない）")
            sub = None
        picked[label] = (main, sub)
        cands = [c for c in result["new_category_candidates"] if c["axis"] == label]
        if main is None and not cands:
            flags.append(f"{label}：主カテゴリも新カテゴリ候補もない")
        if main is not None and main not in original[label]:
            flags.append(f"{label}：元と主カテゴリが異なる")

    cands = [c for c in result["new_category_candidates"]
             if c["name"] != config.OTHER_LABEL and c["name"] not in set(masters[c["axis"]]["カテゴリ名"])]
    if cands:
        flags.append("新カテゴリ候補あり")
    if result["confidence"] < config.RECLASSIFY_CONFIDENCE_MIN:
        flags.append(f"確信度が{config.RECLASSIFY_CONFIDENCE_MIN}未満")
    missing = [w for w in result["evidence_words"] if _norm(w) not in _norm(source_text)]
    if missing:
        flags.append("根拠語が入力にない：" + "、".join(missing))
    return {"picked": picked, "candidates": cands, "flags": flags, "excluded": False,
            "confidence": result["confidence"], "reason": result["reason"],
            "evidence": result["evidence_words"]}
