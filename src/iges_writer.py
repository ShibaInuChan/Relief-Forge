"""IGES生成モジュール。

ハイトマップ（深さ配列）の上面（彫り込み面）を、格子点をそのまま
制御点とする線形B-spline曲面（IGES Entity 128 / Rational B-Spline
Surface, 多項式・非有理）として出力する。

高精細化のため、曲面を格子状のタイル（パッチ）に分割して複数の
Entity 128 として書き出せる。隣接パッチは境界の制御点列を共有する
ため、隙間なく連続する（線形B-splineは格子点を厳密に通る）。1枚あたりの
制御点数が小さくなることで、CADでの読み込みが大幅に速くなる。

STLが三角形メッシュなのに対し、IGESはCADで扱える解析的な曲面として
レリーフ面を表現できる。木目レリーフのCAM／形状確認用途では、彫り込み
面（上面）があれば十分なため、上面のみを曲面として書き出す。

追加ライブラリ不要（ASCII手書き）。numpy-stl等への依存はない。
"""

import numpy as np


# IGES 1行は固定80桁。1-72桁がデータ、73桁がセクション識別子、
# 74-80桁が各セクション内の連番。
_LINE_DATA_WIDTH = 72

# 1パッチあたりの片側方向の最大制御点数（既定）。これを超える格子は
# タイル分割される。64×64 ≒ 約4千点/パッチでCADが軽快に開ける。
DEFAULT_PATCH_PTS = 64


def _section_line(content, section, seq):
    """1行（80桁）を組み立てる。content は 72桁以内。"""
    return "{:<72}{}{:>7d}".format(content[:72], section, seq)


def _hollerith(text):
    """Hollerith文字列（nHxxxx 形式）に変換する。"""
    return "{}H{}".format(len(text), text)


def _fmt_real(v):
    """実数をIGES向けに整形する。"""
    return "{:.6f}".format(float(v))


def _chunk_ranges(n, max_pts):
    """制御点数 n を、1パッチ最大 max_pts 点の区間に分割する。

    隣接区間は端点を共有する（overlap=1）ため、パッチ同士の境界が
    厳密に一致する。返り値は (start, end) の包含インデックスのリスト。
    """
    max_pts = max(2, int(max_pts))
    step = max_pts - 1  # 1パッチあたりのセル数
    ranges = []
    start = 0
    while start < n - 1:
        end = min(start + step, n - 1)
        ranges.append((start, end))
        start = end
    if not ranges:  # n == 1 の保険
        ranges.append((0, 0))
    return ranges


def _clamped_linear_knots(n):
    """制御点 n 個に対するクランプ線形ノットベクトル。

    [0, 0,1,2,...,n-1, n-1]（両端を重複させ始点・終点を通す）。
    """
    return [0.0] + [float(i) for i in range(n)] + [float(n - 1)]


def _build_patch_tokens(xs, ys, top_z, c0, c1, r0, r1):
    """1パッチ分の Entity 128 パラメータデータ（トークン列）を作る。

    U方向 = X（列 c0..c1）、V方向 = Y（行 r0..r1）。
    """
    cols = c1 - c0 + 1
    rows = r1 - r0 + 1

    k1 = cols - 1
    k2 = rows - 1
    m1 = 1
    m2 = 1

    tokens = ["128", str(k1), str(k2), str(m1), str(m2),
              "0", "0", "1", "0", "0"]

    for s in _clamped_linear_knots(cols):
        tokens.append(_fmt_real(s))
    for t in _clamped_linear_knots(rows):
        tokens.append(_fmt_real(t))

    # 重み（多項式なので全て1.0）。順序は U が内側ループ。
    for _j in range(rows):
        for _i in range(cols):
            tokens.append(_fmt_real(1.0))

    # 制御点 X,Y,Z。U（列）が内側ループ、V（行）が外側ループ。
    for j in range(r0, r1 + 1):
        for i in range(c0, c1 + 1):
            tokens.append(_fmt_real(xs[i]))
            tokens.append(_fmt_real(ys[j]))
            tokens.append(_fmt_real(top_z[j, i]))

    # パラメータ範囲 U0,U1,V0,V1。
    tokens.append(_fmt_real(0.0))
    tokens.append(_fmt_real(float(cols - 1)))
    tokens.append(_fmt_real(0.0))
    tokens.append(_fmt_real(float(rows - 1)))

    return tokens


def _pack_param_lines(tokens, de_pointer):
    """トークン列をパラメータデータ行（64桁以内 + DEバックポインタ）に詰める。"""
    body = ",".join(tokens) + ";"
    lines = []
    remaining = body
    while remaining:
        if len(remaining) <= 64:
            lines.append(remaining)
            break
        seg = remaining[:64]
        idx = max(seg.rfind(","), seg.rfind(";"))
        if idx == -1:
            idx = 63
        lines.append(remaining[:idx + 1])
        remaining = remaining[idx + 1:]
    return ["{:<64}{:>8d}".format(ln, de_pointer) for ln in lines]


def _wrap_global(body):
    """グローバルセクション本文を72桁で折り返す。"""
    out = []
    remaining = body
    while remaining:
        if len(remaining) <= _LINE_DATA_WIDTH:
            out.append(remaining)
            break
        seg = remaining[:_LINE_DATA_WIDTH]
        idx = max(seg.rfind(","), seg.rfind(";"))
        if idx == -1:
            idx = _LINE_DATA_WIDTH - 1
        out.append(remaining[:idx + 1])
        remaining = remaining[idx + 1:]
    return out


def write_iges(depth_map, work_x, work_y, work_z, path,
               product_id="photo-relief-cam", patch_pts=DEFAULT_PATCH_PTS):
    """深さマップの上面をB-spline曲面（複数パッチ）としてIGESに出力する。

    Args:
        patch_pts: 1パッチあたりの片側方向の最大制御点数。グリッドが
                   これを超える場合はタイル分割される。

    Returns:
        (パッチ数, 総パラメータデータ行数) のタプル。
    """
    from datetime import datetime

    path = str(path)
    rows, cols = depth_map.shape

    xs = np.linspace(0.0, work_x, cols)
    ys = np.linspace(0.0, work_y, rows)
    top_z = work_z - depth_map
    max_coord = max(work_x, work_y, work_z)

    # --- パッチ分割 ---
    col_ranges = _chunk_ranges(cols, patch_pts)
    row_ranges = _chunk_ranges(rows, patch_pts)

    # 各パッチの DE と P を組み立てる。
    de_lines = []      # ディレクトリエントリ行
    param_lines = []   # パラメータデータ行
    n_patches = 0

    for (r0, r1) in row_ranges:
        for (c0, c1) in col_ranges:
            n_patches += 1
            de_seq = len(de_lines) + 1          # このDEの先頭行の連番（奇数）
            p_start = len(param_lines) + 1      # このエンティティの先頭P連番

            tokens = _build_patch_tokens(xs, ys, top_z, c0, c1, r0, r1)
            plines = _pack_param_lines(tokens, de_pointer=de_seq)
            param_lines.extend(plines)

            de1 = ("{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}"
                   .format(128, p_start, 0, 0, 0, 0, 0, 0, 0))
            de2 = ("{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8s}{:>8d}"
                   .format(128, 0, 0, len(plines), 0, 0, 0, "", 0))
            de_lines.append(de1)
            de_lines.append(de2)

    # --- Start / Global ---
    start_lines = ["Photo relief surface(s) (IGES Entity 128 B-Spline)."]

    now = datetime.now().strftime("%Y%m%d.%H%M%S")
    fname = path.split("/")[-1]
    g = [
        "1H,", "1H;",
        _hollerith(product_id), _hollerith(fname),
        _hollerith("photo-relief-cam"), _hollerith("1.0"),
        "32", "38", "6", "308", "15",
        _hollerith(product_id),
        "1.0", "2", _hollerith("MM"), "1", "0.01",
        _hollerith(now), "1.0E-06", _fmt_real(max_coord),
        _hollerith("author"), _hollerith("org"),
        "11", "0", _hollerith(now),
    ]
    global_lines = _wrap_global(",".join(g) + ";")

    # --- 出力 ---
    lines = []
    for i, c in enumerate(start_lines, start=1):
        lines.append(_section_line(c, "S", i))
    for i, c in enumerate(global_lines, start=1):
        lines.append(_section_line(c, "G", i))
    for i, c in enumerate(de_lines, start=1):
        lines.append(_section_line(c, "D", i))
    for i, c in enumerate(param_lines, start=1):
        lines.append("{:<72}{}{:>7d}".format(c, "P", i))

    term = "{:>8s}{:>7d}{:>8s}{:>7d}{:>8s}{:>7d}{:>8s}{:>7d}".format(
        "S", len(start_lines), "G", len(global_lines),
        "D", len(de_lines), "P", len(param_lines))
    lines.append(_section_line(term, "T", 1))

    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")

    return n_patches, len(param_lines)
