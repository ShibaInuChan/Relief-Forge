#!/usr/bin/env python3
"""テスト用の包丁の柄ソリッドSTLを生成する。

実STLが大きい間の試作用。スタジアム状（角丸長方形）の輪郭に、
レンズ状に盛り上がった上面を持つ握り形状を作る。底面は平ら(Z=0)。
2.5D（上から見て高さが一意）なので、面ごと彫り込みの検証に使える。
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import stl_writer


def make_handle(length=130.0, width=36.0, max_h=14.0, cols=160, rows=60):
    xs = np.linspace(0.0, length, cols)
    ys = np.linspace(0.0, width, rows)
    gx, gy = np.meshgrid(xs, ys)

    # スタジアム状の輪郭（両端を半円で丸めた長方形）。
    cx = length / 2.0
    half_len = length / 2.0
    r = width / 2.0
    # 直線部の半長さ。
    straight = max(half_len - r, 0.0)
    # 中心線までの距離で内外判定。
    dx = np.abs(gx - cx) - straight
    dx = np.clip(dx, 0.0, None)
    dist = np.sqrt(dx ** 2 + (gy - r) ** 2)
    mask = dist <= r

    # 上面: 輪郭中心で最も高く、縁で0へ滑らかに落ちるレンズ状。
    t = np.clip(1.0 - (dist / r) ** 2, 0.0, 1.0)
    top = max_h * np.sqrt(t)            # ドーム
    top = np.where(mask, top + 2.0, 0.0)  # 縁で薄さ2mmを残す
    bot = np.zeros_like(top)

    return top, bot, mask, xs, ys


def main():
    out = Path("samples/shapes/test_handle.stl")
    out.parent.mkdir(parents=True, exist_ok=True)
    top, bot, mask, xs, ys = make_handle()
    m = stl_writer.build_masked_solid(top, bot, mask, xs, ys)
    m.save(str(out))
    print(f"[OK] {out} ({len(m.vectors)} faces)")


if __name__ == "__main__":
    main()
