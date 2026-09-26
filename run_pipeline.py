"""パイプライン全体の実行。

使い方（Git Bash、プロジェクトのルートで）:
    python run_pipeline.py              # 実装済みのステップを順に全部
    python run_pipeline.py --step 1     # ステップ1だけ
    python run_pipeline.py --step 3 --limit 10   # 10件だけ試す
    python run_pipeline.py --no-api     # APIを呼ぶ処理をスキップ
"""
import argparse

from src import (io_utils, step1_load_clean, step2_tag_dictionary, step3_reclassify,
                 step4_time_expressions)

# ステップ番号 → 実行する関数（フェーズ2以降で追加していく）
STEPS = {
    1: step1_load_clean.main,
    2: step2_tag_dictionary.main,
    3: step3_reclassify.main,
    4: step4_time_expressions.main,
}


def main() -> None:
    io_utils.setup_console()
    parser = argparse.ArgumentParser(description="Business Journal 記事整理パイプライン")
    parser.add_argument("--step", type=int, choices=range(1, 7), help="実行するステップ（1〜6）")
    parser.add_argument("--limit", type=int, default=None, help="処理する記事数の上限（試し実行用）")
    parser.add_argument("--no-api", action="store_true", help="OpenAI APIを呼ばない")
    args = parser.parse_args()

    targets = [args.step] if args.step else sorted(STEPS)
    for step in targets:
        if step not in STEPS:
            print(f"ステップ{step} はまだ実装していません。")
            continue
        STEPS[step](limit=args.limit, no_api=args.no_api)


if __name__ == "__main__":
    main()
