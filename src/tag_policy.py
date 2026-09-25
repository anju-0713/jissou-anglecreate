"""表記方針表（data/manual/tag_canonical_policy.csv）を読み込むモジュール。

統合後の表記（例：グーグル → Google）は人がこの表で決めます。コードには表記を書きません。
表がなければ「方針なし」として扱います。
"""
import pandas as pd

from src import config, io_utils

CANON = config.TAG_POLICY_CANON_COL
ALIAS = config.TAG_POLICY_ALIAS_COL
REASON = config.TAG_POLICY_REASON_COL


class TagPolicy:
    """表記方針表。canonical_of(タグ) で統合後の表記を返す。"""

    def __init__(self, df: pd.DataFrame):
        self.df = df
        self.reasons: dict[str, str] = {}
        self.aliases: dict[str, list[str]] = {}   # 統合後タグ → 別名の一覧
        self._to_canon: dict[str, str] = {}       # 別名・統合後タグ → 統合後タグ
        for _, row in df.iterrows():
            canon = row[CANON].strip()
            if not canon:
                continue
            names = [a.strip() for a in row[ALIAS].split(config.TAG_SEP) if a.strip()]
            self.aliases[canon] = names
            self.reasons[canon] = row[REASON]
            for name in [canon, *names]:
                # 同じ表記が2つの統合後タグに書かれていたら、表の誤りなので止める
                if self._to_canon.get(name, canon) != canon:
                    raise SystemExit(f"表記方針表の誤り：「{name}」が複数の統合後タグにあります")
                self._to_canon[name] = canon

    def canonical_of(self, tag: str) -> str:
        """方針表にあるタグなら統合後タグ、なければ空文字。"""
        return self._to_canon.get(tag, "")

    def alias_rows(self, counts) -> list[dict]:
        """データに出てくる別名を、統合後タグへ統合する辞書の行（提案元=policy）。"""
        rows = []
        for canon, names in self.aliases.items():
            for name in names:
                if name in counts and name != canon:
                    rows.append({
                        "元タグ": name, "出現回数": counts[name], "提案_統合後タグ": canon,
                        "関連先タグ": "", "提案元": "policy",
                        "理由": f"表記方針表：{self.reasons[canon]}",
                        "確信度": 1.0, "relation_type": "同義",
                    })
        return rows

    def display_name(self, tag: str) -> str:
        """Dify用の表示名（別名があれば「Google（グーグル）」の形）。フェーズ6で使う。"""
        names = self.aliases.get(tag)
        return f"{tag}（{'・'.join(names)}）" if names else tag


def load_policy() -> TagPolicy:
    """表記方針表を読む。ファイルがなければ空の方針を返す。"""
    if not config.TAG_POLICY_CSV.exists():
        print(f"表記方針表なし（{config.TAG_POLICY_CSV.name}）：方針なしで進めます")
        return TagPolicy(pd.DataFrame(columns=[CANON, ALIAS, REASON]))
    df, _ = io_utils.read_csv_auto(config.TAG_POLICY_CSV)
    return TagPolicy(df)
