"""対象ソリッドSTLから上面ハイトマップとマスクを抽出するモジュール。

包丁の柄のような3Dソリッドでも、指定方向（既定はZ+）から見て高さが一意に
決まる面（2.5D）であれば、真上から各XYへレイを下ろし最初に当たる面のZを
取ることで「上面の高さマップ H(x,y)」と「部品が存在する範囲のマスク」を得られる。

実装は三角形のZバッファ・ラスタライズ（各三角形をXYグリッドへ投影し、
平面式で高さを求め、最大Zを採用）。trimesh等の追加依存なしで動く軽量版。
"""

import numpy as np
from stl import mesh


def sample_top_heightmap(stl_path, cols, rows, margin=0.0):
    """STLの上面（Z+から見える面）の高さマップとマスクを返す。

    Args:
        stl_path: 入力STLパス。
        cols, rows: 出力グリッドの列数・行数。
        margin: バウンディングボックスに加える余白[mm]。

    Returns:
        (H, mask, xs, ys):
            H: (rows, cols) 上面Z[mm]。mask外は0。
            mask: (rows, cols) bool。部品が存在する格子点。
            xs, ys: 格子座標[mm]。
    """
    m = mesh.Mesh.from_file(str(stl_path))
    v = m.vectors.astype(np.float64)  # (n,3,3)

    x_min = v[:, :, 0].min() - margin
    x_max = v[:, :, 0].max() + margin
    y_min = v[:, :, 1].min() - margin
    y_max = v[:, :, 1].max() + margin

    xs = np.linspace(x_min, x_max, cols)
    ys = np.linspace(y_min, y_max, rows)

    H = np.full((rows, cols), -np.inf)

    dx = (x_max - x_min) / max(cols - 1, 1)
    dy = (y_max - y_min) / max(rows - 1, 1)

    for tri in v:
        (x0, y0, z0), (x1, y1, z1), (x2, y2, z2) = tri

        # 三角形のXYバウンディングをグリッド添字に変換。
        tx_min, tx_max = min(x0, x1, x2), max(x0, x1, x2)
        ty_min, ty_max = min(y0, y1, y2), max(y0, y1, y2)
        c0 = max(0, int(np.floor((tx_min - x_min) / dx)))
        c1 = min(cols - 1, int(np.ceil((tx_max - x_min) / dx)))
        r0 = max(0, int(np.floor((ty_min - y_min) / dy)))
        r1 = min(rows - 1, int(np.ceil((ty_max - y_min) / dy)))
        if c1 < c0 or r1 < r0:
            continue

        gx = xs[c0:c1 + 1]
        gy = ys[r0:r1 + 1]
        px, py = np.meshgrid(gx, gy)

        # 重心座標で三角形内判定。
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(denom) < 1e-12:
            continue
        a = ((y1 - y2) * (px - x2) + (x2 - x1) * (py - y2)) / denom
        b = ((y2 - y0) * (px - x2) + (x0 - x2) * (py - y2)) / denom
        cc = 1.0 - a - b
        inside = (a >= -1e-9) & (b >= -1e-9) & (cc >= -1e-9)
        if not inside.any():
            continue

        z = a * z0 + b * z1 + cc * z2
        sub = H[r0:r1 + 1, c0:c1 + 1]
        upd = inside & (z > sub)
        sub[upd] = z[upd]
        H[r0:r1 + 1, c0:c1 + 1] = sub

    mask = np.isfinite(H)
    H = np.where(mask, H, 0.0)
    return H, mask, xs, ys
