"""ファイルの読み書きをまとめたモジュール。

文字コードは utf-8-sig → cp932 の順に試して自動判定します。
出力CSVは必ず BOM付きUTF-8 にします。
"""
import sys
from datetime import datetime
from pathlib import Path

import pandas as pd

from src import config


def setup_console() -> None:
    """コンソール出力をUTF-8にする（Git Bash で日本語が化けないように）。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass


def has_bom(path: Path) -> bool:
    """ファイル先頭にUTF-8のBOMがあるかどうか。"""
    return Path(path).read_bytes()[:3] == b"\xef\xbb\xbf"


def detect_encoding(path: Path) -> str:
    """config.READ_ENCODINGS の順にデコードを試し、最初に成功した文字コードを返す。"""
    raw = Path(path).read_bytes()
    for enc in config.READ_ENCODINGS:
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    raise ValueError(f"文字コードを判定できません: {path}")


def read_csv_auto(path: Path) -> tuple[pd.DataFrame, str]:
    """CSVを文字コード自動判定で読む。値はすべて文字列、欠損は空文字、前後空白は除去。"""
    enc = detect_encoding(path)
    df = pd.read_csv(path, encoding=enc, dtype=str, keep_default_na=False)
    df.columns = [c.strip() for c in df.columns]
    for col in df.columns:
        df[col] = df[col].str.strip()
    return df, enc


def read_table_auto(path: Path) -> tuple[pd.DataFrame, str]:
    """CSV または xlsx を読む。戻り値は (DataFrame, 文字コード or 'xlsx')。"""
    path = Path(path)
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(path, dtype=str).fillna("")
        df.columns = [str(c).strip() for c in df.columns]
        for col in df.columns:
            df[col] = df[col].str.strip()
        return df, "xlsx"
    return read_csv_auto(path)


def read_text_auto(path: Path) -> tuple[str, str]:
    """テキストファイルを文字コード自動判定で読む。戻り値は (本文, 文字コード)。"""
    enc = detect_encoding(path)
    return Path(path).read_text(encoding=enc), enc


def write_csv(df: pd.DataFrame, path: Path) -> None:
    """BOM付きUTF-8でCSVを書き出す（フォルダがなければ作る）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, encoding=config.WRITE_ENCODING)


def write_text(text: str, path: Path) -> None:
    """UTF-8でテキストを書き出す（WindowsでもCRLFに変換しない）。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")  # 改行はLFのまま


def append_run_log(step: str, lines: list[str]) -> None:
    """outputs/run_log.txt に実行ログを追記する。"""
    config.RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(config.RUN_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{stamp}] {step}\n")
        for line in lines:
            f.write(f"    {line}\n")
