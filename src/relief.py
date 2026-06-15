#!/usr/bin/env python3
"""画像→木目レリーフ試作データ生成ツール（中核ロジック）。

方式（グレースケール・ハイトマップ方式）:
    画像をグレースケール化し、明度を切削深さに比例写像する。
    暗い画素 → 深く彫る／明るい画素 → 浅く彫る・彫らない。
    明度レンジは画像の実min-maxで0-1に正規化してから深さへ写像する。
    画像が持つ全情報（濃淡・輪郭・パターン）を再構成なしでそのまま
    深さに落とすため、線抽出やパターン生成は不要。

使い方:
    python src/relief.py samples/images/cherry.jpg --out output/

免責:
    生成NCは機械非依存の素体であり、実機の制御装置・工具・原点に
    合わせた調整と、シミュレーション・試し切りによる検証が必須。
    未検証データを本番加工に流さないこと。
"""

import argparse
import json
import sys
from dataclasses import dataclass, asdict, fields
from pathlib import Path

import numpy as np
from PIL import Image

# src/ をパッケージとして扱わず単体実行できるようにする。
sys.path.insert(0, str(Path(__file__).resolve().parent))
import stl_writer
import gcode_writer
import preview as preview_mod


@dataclass
class Params:
    WORK_X: float = 150.0       # mm 板の長さ
    WORK_Y: float = 100.0       # mm 板の幅（画像アスペクトに合わせ調整可）
    WORK_Z: float = 20.0        # mm 板の厚み（STL用）
    MAX_DEPTH: float = 0.5      # mm 最大切削深さ（暗部）
    MIN_DEPTH: float = 0.0      # mm 最小切削深さ（明部）
    BALL_DIA: float = 1.0       # mm ボールエンドミル径
    STEP_OVER: float = 0.3      # mm 走査線ピッチ
    SAMPLE_PITCH_X: float = 0.3  # mm X方向サンプリング間隔
    FEED_CUT: float = 1000      # mm/min
    FEED_PLUNGE: float = 400    # mm/min
    SPINDLE_RPM: float = 18000
    SAFE_Z: float = 5.0         # mm

    # STL解像度（実証済み: 300x200程度に抑える）
    STL_COLS: int = 300
    STL_ROWS: int = 200

    def as_dict(self):
        return asdict(self)


def load_params(config_path=None, overrides=None):
    """デフォルト→設定ファイル→CLI上書き の順でパラメータを構築する。"""
    p = Params()
    if config_path:
        with open(config_path) as f:
            cfg = json.load(f)
        for k, v in cfg.items():
            if hasattr(p, k):
                setattr(p, k, v)
    if overrides:
        for k, v in overrides.items():
            if v is not None and hasattr(p, k):
                setattr(p, k, v)
    return p


def image_to_depth_map(image_path, params, rows, cols):
    """画像をグレースケール化し、彫り込み深さマップへ比例写像する。

    Returns:
        (rows, cols) の深さ ndarray[mm]。0=彫らない、正=深く彫る。
    """
    img = Image.open(image_path).convert("L")  # グレースケール
    img = img.resize((cols, rows), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.float64)

    # 実min-maxで0-1に正規化。
    lo, hi = arr.min(), arr.max()
    if hi - lo < 1e-9:
        norm = np.zeros_like(arr)
    else:
        norm = (arr - lo) / (hi - lo)

    # 暗い画素ほど深く彫る → 明度が低いほど深さが大きい。
    # 明度0(暗)→MAX_DEPTH、明度1(明)→MIN_DEPTH
    depth = params.MAX_DEPTH - norm * (params.MAX_DEPTH - params.MIN_DEPTH)
    return depth


def adjust_work_y_to_aspect(params, image_path):
    """画像アスペクト比に合わせて WORK_Y を調整する。"""
    with Image.open(image_path) as img:
        w, h = img.size
    if w <= 0:
        return params.WORK_Y
    return params.WORK_X * (h / w)


def process(image_path, out_dir, params, timestamp=False, fit_aspect=True):
    """1枚の画像を処理して STL/NC/PNG を生成する。"""
    image_path = Path(image_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    if fit_aspect:
        params.WORK_Y = round(adjust_work_y_to_aspect(params, image_path), 3)
        # STL行数もアスペクトに合わせ更新（列数基準）。
        params.STL_ROWS = max(2, int(round(params.STL_COLS * params.WORK_Y / params.WORK_X)))

    stem = image_path.stem
    suffix = ""
    if timestamp:
        from datetime import datetime
        suffix = "_" + datetime.now().strftime("%Y%m%d_%H%M%S")

    stl_path = out_dir / f"{stem}_relief{suffix}.stl"
    nc_path = out_dir / f"{stem}_relief{suffix}.nc"
    png_path = out_dir / f"{stem}_relief{suffix}.png"

    for pth in (stl_path, nc_path, png_path):
        if pth.exists() and not timestamp:
            print(f"[警告] 上書きします: {pth}")

    # --- STL用の深さマップ（解像度を抑える） ---
    print(f"[STL] 深さマップ生成 {params.STL_COLS}x{params.STL_ROWS} ...")
    stl_depth = image_to_depth_map(image_path, params, params.STL_ROWS, params.STL_COLS)
    n_faces = stl_writer.write_stl(
        stl_depth, params.WORK_X, params.WORK_Y, params.WORK_Z, stl_path
    )
    print(f"[STL] {stl_path} ({n_faces} faces)")

    # --- NC用の深さマップ（高解像度） ---
    nc_cols = max(2, int(round(params.WORK_X / params.SAMPLE_PITCH_X)) + 1)
    nc_rows = max(2, int(round(params.WORK_Y / params.STEP_OVER)) + 1)
    print(f"[NC] 深さマップ生成 {nc_cols}x{nc_rows} ...")
    nc_depth = image_to_depth_map(image_path, params, nc_rows, nc_cols)
    n_lines = gcode_writer.write_gcode(nc_depth, params.as_dict(), nc_path)
    print(f"[NC] {nc_path} ({n_lines} 行)")
    if n_lines > 50000:
        print(f"[警告] NCファイルが巨大です（{n_lines} 行）。"
              " 制御装置のメモリ／DNC運転を確認してください。")

    # --- プレビューPNG ---
    print("[PNG] 陰影プレビュー生成 ...")
    preview_mod.write_preview(stl_depth, params.WORK_Z, png_path)
    print(f"[PNG] {png_path}")

    return stl_path, nc_path, png_path


def build_arg_parser():
    p = argparse.ArgumentParser(
        description="画像→木目レリーフ STL/NC/PNG 生成ツール（グレースケール・ハイトマップ方式）"
    )
    p.add_argument("image", help="入力画像ファイル（jpg/png）")
    p.add_argument("--out", default="output/", help="出力ディレクトリ（既定: output/）")
    p.add_argument("--config", help="パラメータJSON設定ファイル")
    p.add_argument("--timestamp", action="store_true",
                   help="出力名にタイムスタンプを付与（上書き回避）")
    p.add_argument("--no-fit-aspect", action="store_true",
                   help="画像アスペクトでWORK_Yを自動調整しない")

    # 主要パラメータのCLI上書き。
    for fld in fields(Params):
        argname = "--" + fld.name.lower()
        p.add_argument(argname, type=type(fld.default), default=None,
                       help=f"{fld.name} を上書き")
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)

    overrides = {}
    for fld in fields(Params):
        val = getattr(args, fld.name.lower())
        if val is not None:
            overrides[fld.name] = val

    params = load_params(args.config, overrides)

    process(
        args.image,
        args.out,
        params,
        timestamp=args.timestamp,
        fit_aspect=not args.no_fit_aspect,
    )
    print("[完了] 生成物は output/ に保存しました（Git管理対象外）。")


if __name__ == "__main__":
    main()
