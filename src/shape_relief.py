#!/usr/bin/env python3
"""対象ソリッドSTLの上面に木目レリーフを彫り込む試作CLI（面ごと2.5D）。

包丁の柄のような形状でも、上から見て高さが一意に決まる面（2.5D）なら、
その面の高さマップを抽出し、木目深さを差し引いて彫り込める。

処理:
    1. 対象STLから上面高さマップ H(x,y) と部品マスクを抽出
    2. 画像をグレースケール→深さ d(x,y) に比例写像（暗いほど深い）
    3. 彫り込み後の上面 = H - d（マスク内のみ）
    4. 変位プレビューPNG / 彫り込み後の上面ソリッドSTL / マスク付きラスターNC

注意:
    - 全周への巻き付けは3軸では不可（回転軸加工の領域）。本ツールは1面ずつ。
    - 合成ソリッドのブール演算は不安定なため、本ツールは「彫り込み後の上面
      （＋スカート）」を可視化用に出力する。実加工は対象ソリッドに対する
      表面仕上げツールパス（NC）として扱う。
    - 生成NCは機械非依存の素体。実機調整・シミュレーション・試し切り必須。
"""

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stl_writer
import gcode_writer
import preview as preview_mod
import shape_sampler
from relief import Params, load_params
from dataclasses import fields


def grain_depth_for_grid(image_path, mask, params):
    """マスク形状に画像を当てはめ、彫り込み深さマップ d(x,y) を返す。"""
    rows, cols = mask.shape
    img = Image.open(image_path).convert("L").resize((cols, rows), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.float64)

    # マスク内の実min-maxで正規化（部品外は無視）。
    if mask.any():
        vals = arr[mask]
        lo, hi = vals.min(), vals.max()
    else:
        lo, hi = arr.min(), arr.max()
    norm = np.zeros_like(arr) if hi - lo < 1e-9 else (arr - lo) / (hi - lo)

    depth = params.MAX_DEPTH - norm * (params.MAX_DEPTH - params.MIN_DEPTH)
    depth = np.where(mask, depth, 0.0)
    return depth


def process(shape_path, image_path, out_dir, params, grid_cols=400):
    shape_path = Path(shape_path)
    image_path = Path(image_path)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 対象STLのアスペクトに合わせ行数を決める。
    from stl import mesh as _mesh
    v = _mesh.Mesh.from_file(str(shape_path)).vectors
    ext_x = v[:, :, 0].max() - v[:, :, 0].min()
    ext_y = v[:, :, 1].max() - v[:, :, 1].min()
    grid_rows = max(2, int(round(grid_cols * ext_y / max(ext_x, 1e-9))))

    print(f"[抽出] 上面高さマップ {grid_cols}x{grid_rows} ...")
    H, mask, xs, ys = shape_sampler.sample_top_heightmap(shape_path, grid_cols, grid_rows)
    print(f"[抽出] 部品セル率 {100*mask.mean():.1f}% / 高さ {H[mask].min():.2f}..{H[mask].max():.2f} mm")

    d = grain_depth_for_grid(image_path, mask, params)
    engraved = np.where(mask, H - d, 0.0)

    stem = f"{shape_path.stem}_{image_path.stem}_grain"
    stl_path = out_dir / f"{stem}.stl"
    nc_path = out_dir / f"{stem}.nc"
    png_path = out_dir / f"{stem}.png"

    # 彫り込み後の上面ソリッド（底面0、可視化用）。
    print("[STL] 彫り込み後の上面ソリッド生成 ...")
    bot = np.zeros_like(engraved)
    m = stl_writer.build_masked_solid(engraved, bot, mask, xs, ys)
    m.save(str(stl_path))
    print(f"[STL] {stl_path} ({len(m.vectors)} faces)")

    # マスク付きラスターNC。
    print("[NC] マスク付きラスターNC生成 ...")
    n_lines = gcode_writer.write_gcode_surface(engraved, mask, xs, ys, params.as_dict(), nc_path)
    print(f"[NC] {nc_path} ({n_lines} 行)")
    if n_lines > 50000:
        print(f"[警告] NCが巨大です（{n_lines} 行）。DNC運転等を確認のこと。")

    # プレビュー（彫り込み後の上面を陰影表示）。深さ=最大Z-面。
    print("[PNG] 陰影プレビュー生成 ...")
    surf = np.where(mask, engraved, np.nan)
    zmax = np.nanmax(surf)
    depth_for_preview = np.where(mask, zmax - engraved, 0.0)
    preview_mod.write_preview(depth_for_preview, zmax, png_path)
    print(f"[PNG] {png_path}")

    return stl_path, nc_path, png_path


def build_arg_parser():
    p = argparse.ArgumentParser(
        description="対象ソリッドSTLの上面に木目レリーフを彫り込む（面ごと2.5D）"
    )
    p.add_argument("shape", help="対象ソリッドSTL")
    p.add_argument("image", help="木目画像（jpg/png）")
    p.add_argument("--out", default="output/", help="出力ディレクトリ")
    p.add_argument("--config", help="パラメータJSON設定ファイル")
    p.add_argument("--grid-cols", type=int, default=400, help="サンプリンググリッド列数")
    for fld in fields(Params):
        p.add_argument("--" + fld.name.lower(), type=type(fld.default), default=None)
    return p


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    overrides = {}
    for fld in fields(Params):
        val = getattr(args, fld.name.lower())
        if val is not None:
            overrides[fld.name] = val
    params = load_params(args.config, overrides)
    process(args.shape, args.image, args.out, params, grid_cols=args.grid_cols)
    print("[完了] 生成物は output/ に保存（Git管理対象外）。")


if __name__ == "__main__":
    main()
