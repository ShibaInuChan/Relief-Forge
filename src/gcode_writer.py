"""NC（Gコード）生成モジュール。

FANUC互換の汎用ラスター（走査線）方式。往復走査で各走査線ごとに
Zを画素深さに追従させる。

注意:
    17万行・4MB規模になり得る。巨大ファイルである旨を呼び出し側で
    標準出力に警告する。
    将来的な点列間引き（直線近似での圧縮）の余地を残すため、
    走査線の点列生成と圧縮を関数として分離している（圧縮は未実装）。

重要な免責:
    生成NCは機械非依存の素体であり、実機の制御装置・工具・原点に
    合わせた調整と、シミュレーション・試し切りによる検証が必須。
    未検証データを本番加工に流さないこと。
"""

import numpy as np


def _depth_to_z(depth_map, work_z):
    """彫り込み深さマップを、加工面の絶対Z座標へ変換する。

    板上面を Z=work_z として、そこから深さぶん下げる。
    """
    return work_z - depth_map


def build_raster_points(depth_map, work_x, work_y, work_z, step_over, sample_pitch_x):
    """ラスター走査線の点列を生成する。

    Returns:
        走査線のリスト。各走査線は (x, y, z) タプルのリスト。
        往復走査のため奇数番目の走査線はX方向が反転している。
    """
    rows, cols = depth_map.shape
    z_map = _depth_to_z(depth_map, work_z)

    # サンプリング格子の物理座標。
    xs = np.linspace(0.0, work_x, cols)
    ys = np.linspace(0.0, work_y, rows)

    # 走査線（Y方向）の本数を step_over から決める。
    n_lines = max(2, int(round(work_y / step_over)) + 1)
    # 各サンプル点（X方向）の数を sample_pitch_x から決める。
    n_samples = max(2, int(round(work_x / sample_pitch_x)) + 1)

    sample_xs = np.linspace(0.0, work_x, n_samples)
    line_ys = np.linspace(0.0, work_y, n_lines)

    lines = []
    for i, y in enumerate(line_ys):
        # この走査線のY位置に最も近い画像行を補間して深さを得る。
        # 行方向（Y）の線形補間係数。
        row_pos = np.interp(y, ys, np.arange(rows))
        r0 = int(np.floor(row_pos))
        r1 = min(r0 + 1, rows - 1)
        frac = row_pos - r0
        z_row = z_map[r0] * (1 - frac) + z_map[r1] * frac

        # X方向にサンプリング点へ補間。
        z_samples = np.interp(sample_xs, xs, z_row)

        pts = list(zip(sample_xs, np.full(n_samples, y), z_samples))
        if i % 2 == 1:
            pts = pts[::-1]  # 往復走査
        lines.append(pts)

    return lines


def compress_line(points, tolerance=0.0):
    """走査線の点列を直線近似で間引く（プレースホルダ）。

    将来的な圧縮拡張のために分離してある。tolerance=0 では何もしない。
    """
    if tolerance <= 0.0:
        return points
    # TODO: Douglas-Peucker等での間引きを実装する余地。
    return points


def write_gcode_surface(top_z_map, mask, xs, ys, params, path):
    """対象面の絶対Zマップ（彫り込み済み上面）をなぞるラスターNCを生成する。

    マスク外では安全高さへ退避し、内側に入ったら切り込む。柄など輪郭を持つ
    対象面の仕上げツールパス用。

    Args:
        top_z_map: (rows, cols) 加工する上面の絶対Z[mm]（既に木目深さを差し引き済み）。
        mask: (rows, cols) bool。加工対象の範囲。
        xs, ys: 格子座標[mm]。
        params: パラメータ辞書。
        path: 出力パス。

    Returns:
        書き出した行数。
    """
    safe_z = params["SAFE_Z"]
    feed_cut = params["FEED_CUT"]
    feed_plunge = params["FEED_PLUNGE"]
    rpm = params["SPINDLE_RPM"]

    rows, cols = top_z_map.shape

    out = []
    out.append("%")
    out.append("O0002")
    out.append("(PHOTO RELIEF ON TARGET SHAPE - SURFACE FINISH RASTER)")
    out.append("(MACHINE-INDEPENDENT TEMPLATE - VERIFY BEFORE USE)")
    out.append("(SINGLE FACE / 2.5D - MULTI-SETUP FOR OTHER FACES)")
    out.append("G21 G90 G94")
    out.append("G17 G54")
    out.append(f"S{int(rpm)} M3")
    out.append(f"G0 Z{safe_z:.3f}")

    for r in range(rows):
        col_order = range(cols) if r % 2 == 0 else range(cols - 1, -1, -1)
        cutting = False
        for c in col_order:
            x, y, z = xs[c], ys[r], top_z_map[r, c]
            if mask[r, c]:
                if not cutting:
                    out.append(f"G0 X{x:.3f} Y{y:.3f}")
                    out.append(f"G0 Z{z + 1.0:.3f}")
                    out.append(f"G1 Z{z:.3f} F{int(feed_plunge)}")
                    cutting = True
                else:
                    out.append(f"G1 X{x:.3f} Y{y:.3f} Z{z:.3f} F{int(feed_cut)}")
            else:
                if cutting:
                    out.append(f"G0 Z{safe_z:.3f}")
                    cutting = False
        if cutting:
            out.append(f"G0 Z{safe_z:.3f}")

    out.append(f"G0 Z{safe_z:.3f}")
    out.append("M5")
    out.append("M30")
    out.append("%")

    text = "\n".join(out) + "\n"
    with open(path, "w") as f:
        f.write(text)
    return len(out)


def write_gcode(depth_map, params, path):
    """深さマップからNC（Gコード）を生成して保存する。

    Args:
        depth_map: 彫り込み深さの ndarray。
        params: パラメータ辞書（relief.Params.as_dict 相当）。
        path: 出力パス。

    Returns:
        書き出した行数。
    """
    work_x = params["WORK_X"]
    work_y = params["WORK_Y"]
    work_z = params["WORK_Z"]
    safe_z = params["SAFE_Z"]
    feed_cut = params["FEED_CUT"]
    feed_plunge = params["FEED_PLUNGE"]
    rpm = params["SPINDLE_RPM"]
    step_over = params["STEP_OVER"]
    sample_pitch_x = params["SAMPLE_PITCH_X"]

    lines = build_raster_points(
        depth_map, work_x, work_y, work_z, step_over, sample_pitch_x
    )

    out = []
    out.append("%")
    out.append("O0001")
    out.append("(PHOTO RELIEF - RASTER ROUGHING/FINISH)")
    out.append("(MACHINE-INDEPENDENT TEMPLATE - VERIFY BEFORE USE)")
    out.append("(UNITS: MM)")
    out.append("G21 G90 G94")  # mm, 絶対, 毎分送り
    out.append("G17")          # XY平面
    out.append("G54")          # ワーク座標系
    out.append(f"S{int(rpm)} M3")
    out.append(f"G0 Z{safe_z:.3f}")

    for li, pts in enumerate(lines):
        pts = compress_line(pts, tolerance=0.0)
        x0, y0, z0 = pts[0]
        out.append(f"G0 X{x0:.3f} Y{y0:.3f}")
        out.append(f"G0 Z{z0 + 1.0:.3f}")
        out.append(f"G1 Z{z0:.3f} F{int(feed_plunge)}")
        for (x, y, z) in pts[1:]:
            out.append(f"G1 X{x:.3f} Y{y:.3f} Z{z:.3f} F{int(feed_cut)}")
        out.append(f"G0 Z{safe_z:.3f}")

    out.append(f"G0 Z{safe_z:.3f}")
    out.append("M5")
    out.append("M30")
    out.append("%")

    text = "\n".join(out) + "\n"
    with open(path, "w") as f:
        f.write(text)

    return len(out)
