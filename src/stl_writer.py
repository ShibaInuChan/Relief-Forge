"""STL生成モジュール。

ハイトマップ（深さ配列）から、板の上面に画像を彫り込んだ
閉じたソリッドメッシュを生成する。
上面・底面・側面4枚をすべて閉じることで watertight なメッシュにする。

注意（実証済みの知見）:
    解像度は 300x200 程度に抑える（約24万面）。これ以上細かいと
    Fusion 360 で開けない／重くなる。形状確認・3Dプリント用と割り切る。
"""

import numpy as np
from stl import mesh


def build_solid_mesh(depth_map, work_x, work_y, work_z):
    """深さマップから閉じたソリッドメッシュを構築する。

    Args:
        depth_map: (rows, cols) の ndarray。各要素は上面からの彫り込み深さ[mm]。
                   0 = 彫らない（板の上面）、正の値 = 深く彫る。
        work_x: 板の長さ[mm]（X方向）。
        work_y: 板の幅[mm]（Y方向）。
        work_z: 板の厚み[mm]。

    Returns:
        numpy-stl の mesh.Mesh オブジェクト。
    """
    rows, cols = depth_map.shape

    # 各格子点の座標を計算する。
    xs = np.linspace(0.0, work_x, cols)
    ys = np.linspace(0.0, work_y, rows)
    grid_x, grid_y = np.meshgrid(xs, ys)

    # 上面のZ = 板上面(work_z) - 彫り込み深さ
    top_z = work_z - depth_map

    # 頂点を集める。
    triangles = []

    # --- 上面（彫り込み面） ---
    for r in range(rows - 1):
        for c in range(cols - 1):
            v00 = (grid_x[r, c], grid_y[r, c], top_z[r, c])
            v01 = (grid_x[r, c + 1], grid_y[r, c + 1], top_z[r, c + 1])
            v10 = (grid_x[r + 1, c], grid_y[r + 1, c], top_z[r + 1, c])
            v11 = (grid_x[r + 1, c + 1], grid_y[r + 1, c + 1], top_z[r + 1, c + 1])
            triangles.append((v00, v11, v01))
            triangles.append((v00, v10, v11))

    # --- 底面（Z=0、上から見て裏なので法線が下向きになるよう逆巻き） ---
    for r in range(rows - 1):
        for c in range(cols - 1):
            v00 = (grid_x[r, c], grid_y[r, c], 0.0)
            v01 = (grid_x[r, c + 1], grid_y[r, c + 1], 0.0)
            v10 = (grid_x[r + 1, c], grid_y[r + 1, c], 0.0)
            v11 = (grid_x[r + 1, c + 1], grid_y[r + 1, c + 1], 0.0)
            triangles.append((v00, v01, v11))
            triangles.append((v00, v11, v10))

    # --- 側面4枚 ---
    # 前後（Y最小・Y最大の端）
    for c in range(cols - 1):
        # Y最小側（r=0）
        t_a = (grid_x[0, c], grid_y[0, c], top_z[0, c])
        t_b = (grid_x[0, c + 1], grid_y[0, c + 1], top_z[0, c + 1])
        b_a = (grid_x[0, c], grid_y[0, c], 0.0)
        b_b = (grid_x[0, c + 1], grid_y[0, c + 1], 0.0)
        triangles.append((t_a, b_a, b_b))
        triangles.append((t_a, b_b, t_b))

        # Y最大側（r=rows-1）
        rr = rows - 1
        t_a = (grid_x[rr, c], grid_y[rr, c], top_z[rr, c])
        t_b = (grid_x[rr, c + 1], grid_y[rr, c + 1], top_z[rr, c + 1])
        b_a = (grid_x[rr, c], grid_y[rr, c], 0.0)
        b_b = (grid_x[rr, c + 1], grid_y[rr, c + 1], 0.0)
        triangles.append((t_a, b_b, b_a))
        triangles.append((t_a, t_b, b_b))

    # 左右（X最小・X最大の端）
    for r in range(rows - 1):
        # X最小側（c=0）
        t_a = (grid_x[r, 0], grid_y[r, 0], top_z[r, 0])
        t_b = (grid_x[r + 1, 0], grid_y[r + 1, 0], top_z[r + 1, 0])
        b_a = (grid_x[r, 0], grid_y[r, 0], 0.0)
        b_b = (grid_x[r + 1, 0], grid_y[r + 1, 0], 0.0)
        triangles.append((t_a, b_b, b_a))
        triangles.append((t_a, t_b, b_b))

        # X最大側（c=cols-1）
        cc = cols - 1
        t_a = (grid_x[r, cc], grid_y[r, cc], top_z[r, cc])
        t_b = (grid_x[r + 1, cc], grid_y[r + 1, cc], top_z[r + 1, cc])
        b_a = (grid_x[r, cc], grid_y[r, cc], 0.0)
        b_b = (grid_x[r + 1, cc], grid_y[r + 1, cc], 0.0)
        triangles.append((t_a, b_a, b_b))
        triangles.append((t_a, b_b, t_b))

    data = np.zeros(len(triangles), dtype=mesh.Mesh.dtype)
    for i, tri in enumerate(triangles):
        data["vectors"][i] = np.array(tri)

    return mesh.Mesh(data)


def write_stl(depth_map, work_x, work_y, work_z, path):
    """深さマップからSTLを生成して保存する。

    Returns:
        生成された三角形面の数。
    """
    m = build_solid_mesh(depth_map, work_x, work_y, work_z)
    m.save(str(path))
    return len(m.vectors)
