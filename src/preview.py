"""プレビューPNG生成モジュール。

彫り後の陰影シミュレーションを matplotlib の LightSource で擬似3D表示する。
深部（暗部）が彫り込まれた様子を陰影で確認できる。
"""

import numpy as np
import matplotlib

matplotlib.use("Agg")  # GUIなし環境向け
import matplotlib.pyplot as plt
from matplotlib.colors import LightSource


def write_preview(depth_map, work_z, path):
    """深さマップから陰影プレビューPNGを生成して保存する。"""
    # 加工面の高さ（深いほど低い）。
    surface = work_z - depth_map

    ls = LightSource(azdeg=315, altdeg=45)
    # グレースケールのカラーマップで木目調の陰影を作る。
    rgb = ls.shade(surface, cmap=plt.cm.copper, vert_exag=8.0, blend_mode="soft")

    rows, cols = depth_map.shape
    aspect = cols / rows
    fig_h = 6.0
    fig_w = fig_h * aspect
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.imshow(rgb, origin="upper")
    ax.set_axis_off()
    fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
    fig.savefig(str(path), dpi=100, bbox_inches="tight", pad_inches=0)
    plt.close(fig)
