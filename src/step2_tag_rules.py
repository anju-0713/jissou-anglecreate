"""ステップ2の補助：ルールによるタグ統合候補（APIなし）。

NFKC正規化・大文字小文字・ハイフンの字形・空白・「・」の違いだけで一致するタグを
同じグループにまとめ、出現回数が一番多い表記を統合後タグとして提案します。
あわせて、部首用の文字などの特殊文字を通常の文字に直す「表記修正」も提案します。
"""
import re
import unicodedata
from collections import Counter, defaultdict

from src import config

# 比べる前にそろえる処理（名前, 関数）。理由の説明にも使う
_HYPHEN_TABLE = str.maketrans({h: "-" for h in config.TAG_RULE_HYPHENS})
NORMALIZERS = [
    ("全角半角", lambda t: unicodedata.normalize("NFKC", t)),
    ("大文字小文字", str.casefold),
    ("ハイフンの字形", lambda t: t.translate(_HYPHEN_TABLE)),
    ("空白・「・」", lambda t: re.sub(config.TAG_RULE_REMOVE_CHARS, "", t)),
]


def rule_key(tag: str, skip: str = "") -> str:
    """ルールで比べるためのキー（正規化を順にかける。skip に名前を渡すとその処理を飛ばす）。"""
    for name, func in NORMALIZERS:
        if name != skip:
            tag = func(tag)
    return tag


def rule_reason(tag: str, rep: str) -> str:
    """2つのタグの違いを説明する（その処理を外すと一致しなくなるものだけを挙げる）。"""
    kinds = [name for name, _ in NORMALIZERS if rule_key(tag, skip=name) != rule_key(rep, skip=name)]
    return "表記ゆれ（" + "・".join(kinds) + "の違い）"


def special_chars(tag: str) -> list[str]:
    """部首用の文字・互換漢字・私用領域・ゼロ幅・結合文字・制御文字を探す。"""
    found = []
    for ch in tag:
        cp = ord(ch)
        if (0x2E80 <= cp <= 0x2FDF or 0x31C0 <= cp <= 0x31EF or 0xF900 <= cp <= 0xFAFF
                or 0xE000 <= cp <= 0xF8FF or unicodedata.category(ch) in ("Mn", "Cc", "Cf", "Co")):
            found.append(ch)
    return found


def char_fix_candidates(counts: Counter) -> tuple[list[dict], list[str]]:
    """特殊文字を通常の文字に直す「表記修正」の行。戻り値は (行, 対応表にない文字の警告)。"""
    rows, warnings = [], []
    for tag in counts:
        chars = special_chars(tag)
        if not chars:
            continue
        unknown = [ch for ch in chars if ch not in config.TAG_CHAR_FIX]
        if unknown:
            warnings.append(f"{tag}: " + ", ".join(f"U+{ord(c):04X} {unicodedata.name(c, '?')}" for c in unknown))
            continue  # 対応表にない文字は自動で直さない（config.TAG_CHAR_FIX に追加して再実行）
        fixed = tag.translate(str.maketrans(config.TAG_CHAR_FIX))
        detail = "、".join(f"U+{ord(c):04X}→「{config.TAG_CHAR_FIX[c]}」" for c in dict.fromkeys(chars))
        rows.append({
            "元タグ": tag, "出現回数": counts[tag], "提案_統合後タグ": fixed, "関連先タグ": "",
            "提案元": "rule", "理由": f"特殊文字を通常の文字に修正（{detail}）",
            "確信度": 1.0, "relation_type": "表記修正",
        })
    return rows, warnings


def apply_char_fix(counts: Counter) -> Counter:
    """表記修正を当てた後の出現回数（ルール統合・AIはこの後の表記で比べる）。"""
    fixed = Counter()
    for tag, n in counts.items():
        fixed[tag.translate(str.maketrans(config.TAG_CHAR_FIX))] += n
    return fixed


def rule_groups(counts: Counter) -> dict[str, list[str]]:
    """ルールキーが同じタグのグループ（2つ以上あるものだけ）。"""
    groups = defaultdict(list)
    for tag in counts:
        groups[rule_key(tag)].append(tag)
    return {k: v for k, v in groups.items() if len(v) > 1}


def pick_representative(members: list[str], counts: Counter, policy) -> tuple[str, bool]:
    """代表表記を決める。戻り値は (代表, 表記方針表で決めたか)。

    表記方針表にあるグループなら方針表の統合後タグ。なければ出現回数が一番多い表記
    （同数なら NFKC で変わらない表記、次に文字順）。
    """
    for tag in members:
        canon = policy.canonical_of(tag)
        if canon:
            return canon, True
    rep = sorted(members, key=lambda t: (-counts[t], unicodedata.normalize("NFKC", t) != t, t))[0]
    return rep, False


def rule_candidates(counts: Counter, policy) -> list[dict]:
    """ルールによる統合候補の行（代表以外のタグ1つにつき1行）。"""
    rows = []
    for members in rule_groups(counts).values():
        rep, by_policy = pick_representative(members, counts, policy)
        for tag in members:
            if tag == rep:
                continue
            if rule_key(tag) != rule_key(rep):  # 例：グループ内の「ｸﾞｰｸﾞﾙ」→ 方針表の「Google」
                reason = "統合後の表記は表記方針表による"
            else:
                reason = rule_reason(tag, rep) + ("（統合後の表記は表記方針表による）" if by_policy else "")
            rows.append({
                "元タグ": tag,
                "出現回数": counts[tag],
                "提案_統合後タグ": rep,
                "関連先タグ": "",
                "提案元": "rule",
                "理由": reason,
                "確信度": 1.0,
                "relation_type": "同義",
            })
    return rows


def representatives(counts: Counter, policy) -> list[str]:
    """ルール統合後に残るタグ（代表表記＋グループに入らなかったタグ）。出現回数の多い順。"""
    merged_away = {r["元タグ"] for r in rule_candidates(counts, policy)}
    return sorted((t for t in counts if t not in merged_away), key=lambda t: (-counts[t], t))
