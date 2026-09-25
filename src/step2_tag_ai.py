"""ステップ2の補助：AIによるタグ統合候補（同義だけ）。

ルールで拾えない同義（グーグル／Google など）をAIに提案させます。
- 統合先の候補一覧は出現回数2回以上のタグだけ。統合元（対象タグ）は全タグ
- AIが返したタグ名は候補一覧と完全一致するものだけを採用し、新しいタグ名は作らせない
- 理由に推測表現があれば捨てる
- 統合後の表記は表記方針表を優先。方針表にない組は出現回数で仮決めし、そう明記する
"""
import re
from collections import Counter

from src import config, llm_client

SCHEMA = {
    "type": "object",
    "properties": {
        "matches": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "tag": {"type": "string"},
                    "reason": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["tag", "reason", "confidence"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["matches"],
    "additionalProperties": False,
}


def candidate_list(tags: list[str], counts: Counter) -> list[str]:
    """統合先の候補一覧（出現回数が config.TAG_AI_CANDIDATE_MIN_COUNT 回以上）。"""
    return [t for t in tags if counts[t] >= config.TAG_AI_CANDIDATE_MIN_COUNT]


def build_system_prompt(tag_list: list[str]) -> str:
    """プロンプトの雛形に候補タグ一覧を差し込む（一覧は全呼び出しで共通）。"""
    template = (config.PROMPTS_DIR / "tag_merge.txt").read_text(encoding="utf-8")
    return template.replace("{tag_list}", "\n".join(tag_list))


def user_prompt(target: str) -> str:
    return f"対象タグ: {target}"


def estimate(targets: list[str], system: str, client_model: str) -> tuple[int, int, float | None]:
    """概算の (入力トークン, 出力トークン, 米ドル)。"""
    input_tokens = sum(llm_client.estimate_tokens(system + user_prompt(t)) for t in targets)
    output_tokens = config.TAG_AI_OUTPUT_TOKENS * len(targets)
    return input_tokens, output_tokens, llm_client.cost_usd(client_model, input_tokens, output_tokens)


def ai_candidates(client, targets: list[str], tag_list: list[str], counts: Counter,
                  policy) -> tuple[list[dict], list[str]]:
    """AIの提案を行にする。戻り値は (候補の行, 捨てた提案の説明)。"""
    system = build_system_prompt(tag_list)
    valid = set(tag_list)
    rows, rejected, seen = [], [], set()
    for target in targets:
        result = client.chat_json(target, system, user_prompt(target), SCHEMA)
        if result is None:
            continue  # errors.csv に記録済み
        for m in result["matches"]:
            tag = m["tag"]
            if tag == target or m["confidence"] < config.TAG_AI_MIN_CONFIDENCE:
                continue
            if tag not in valid:
                rejected.append(f"{target} → {tag}（候補一覧にないタグ名）")
                continue
            if re.search(config.TAG_AI_SPECULATION_REGEX, m["reason"]):
                rejected.append(f"{target} → {tag}（理由に推測表現：{m['reason']}）")
                continue
            pair = frozenset([target, tag])
            if pair in seen:
                continue  # 逆向きで同じ組がすでに出ている
            seen.add(pair)
            row = _to_row(target, tag, m, counts, policy)
            if row:
                rows.append(row)
    return rows, rejected


def _to_row(target: str, tag: str, m: dict, counts: Counter, policy) -> dict | None:
    """統合の向きを決めて1行にする。方針表で決まっている組なら None（policy の行がある）。"""
    canon_t, canon_g = policy.canonical_of(target), policy.canonical_of(tag)
    if canon_t and canon_t == canon_g:
        return None
    if canon_t or canon_g:
        # 片方が方針表のグループ → もう片方をそのグループの統合後タグへ
        src, dst = (tag, canon_t) if canon_t else (target, canon_g)
        note = "（統合後の表記は表記方針表による）"
    else:
        # 方針表にない組は出現回数の多い方に仮決め（同数なら対象タグの方を残す）
        src, dst = (tag, target) if counts[target] >= counts[tag] else (target, tag)
        note = "（※統合後の表記は出現回数で仮決め。表記方針表に未登録）"
    return {
        "元タグ": src,
        "出現回数": counts[src],
        "提案_統合後タグ": dst,
        "関連先タグ": "",
        "提案元": "ai",
        "理由": m["reason"] + note,
        "確信度": round(float(m["confidence"]), 2),
        "relation_type": "同義",
    }
