"""IGES生成モジュール。

ハイトマップ（深さ配列）の上面（彫り込み面）を、格子点をそのまま
制御点とする線形B-spline曲面（IGES Entity 128 / Rational B-Spline
Surface, 多項式・非有理）として出力する。

STLが三角形メッシュなのに対し、IGESはCADで扱える解析的な曲面として
レリーフ面を表現できる。木目レリーフのCAM／形状確認用途では、彫り込み
面（上面）1枚があれば十分なため、上面のみを1枚の曲面として書き出す。

追加ライブラリ不要（ASCII手書き）。numpy-stl等への依存はない。
"""

import numpy as np


# IGES 1行は固定80桁。1-72桁がデータ、73桁がセクション識別子、
# 74-80桁が各セクション内の連番。
_LINE_DATA_WIDTH = 72


def _section_line(content, section, seq):
    """1行（80桁）を組み立てる。content は 72桁以内。"""
    return "{:<72}{}{:>7d}".format(content[:72], section, seq)


def _hollerith(text):
    """Hollerith文字列（nHxxxx 形式）に変換する。"""
    return "{}H{}".format(len(text), text)


def _build_param_records(depth_map, work_x, work_y, work_z):
    """Entity 128 のパラメータデータ（カンマ区切りトークン列）を作る。

    U方向 = X（列）、V方向 = Y（行）に対応させる。
    制御点は格子点そのもの（線形B-splineなので格子点を厳密に通る）。
    """
    rows, cols = depth_map.shape

    xs = np.linspace(0.0, work_x, cols)
    ys = np.linspace(0.0, work_y, rows)
    # 上面のZ = 板上面(work_z) - 彫り込み深さ
    top_z = work_z - depth_map

    k1 = cols - 1  # U方向の制御点上限インデックス
    k2 = rows - 1  # V方向の制御点上限インデックス
    m1 = 1         # U方向の次数（線形）
    m2 = 1         # V方向の次数（線形）

    tokens = []

    def add(v):
        tokens.append(v)

    add("128")          # エンティティ種別
    add(str(k1))
    add(str(k2))
    add(str(m1))
    add(str(m2))
    add("0")            # PROP1: U方向で閉じない
    add("0")            # PROP2: V方向で閉じない
    add("1")            # PROP3: 多項式（非有理）
    add("0")            # PROP4: U方向 非周期
    add("0")            # PROP5: V方向 非周期

    # ノットベクトル（クランプ線形）。制御点 n 個に対し
    # [0, 0,1,2,...,n-1, n-1] （両端を重複させて始点・終点を通す）。
    def clamped_linear_knots(n):
        return [0.0] + [float(i) for i in range(n)] + [float(n - 1)]

    u_knots = clamped_linear_knots(cols)
    v_knots = clamped_linear_knots(rows)
    for s in u_knots:
        add(_fmt_real(s))
    for t in v_knots:
        add(_fmt_real(t))

    # 重み（多項式なので全て1.0）。順序は U が内側ループ。
    for _j in range(rows):
        for _i in range(cols):
            add(_fmt_real(1.0))

    # 制御点 X,Y,Z。順序は U（列）が内側ループ、V（行）が外側ループ。
    for j in range(rows):
        for i in range(cols):
            add(_fmt_real(xs[i]))
            add(_fmt_real(ys[j]))
            add(_fmt_real(top_z[j, i]))

    # パラメータ範囲 U0,U1,V0,V1。
    add(_fmt_real(0.0))
    add(_fmt_real(float(cols - 1)))
    add(_fmt_real(0.0))
    add(_fmt_real(float(rows - 1)))

    return tokens


def _fmt_real(v):
    """実数をIGES向けに整形する（不要な桁を抑えつつ精度を確保）。"""
    return "{:.6f}".format(float(v))


def _pack_param_lines(tokens, de_pointer):
    """トークン列をパラメータデータ行（72桁以内）に詰める。

    最後のトークンの後にレコード区切り ';' を付ける。各行は
    カンマ区切りで、データ部 64桁以内、65-72桁にDEバックポインタ。
    """
    # 末尾にレコード区切りを付与したカンマ区切り文字列を作る。
    body = ",".join(tokens) + ";"

    # 64桁以内になるよう、カンマ境界で分割する。
    lines = []
    remaining = body
    while remaining:
        if len(remaining) <= 64:
            lines.append(remaining)
            break
        # 64桁以内で最後のカンマ（または ';'）の位置を探す。
        cut = 64
        seg = remaining[:cut]
        idx = max(seg.rfind(","), seg.rfind(";"))
        if idx == -1:
            idx = cut - 1
        lines.append(remaining[:idx + 1])
        remaining = remaining[idx + 1:]

    # 各行に DE バックポインタ（65-72桁）を付ける。
    out = []
    for ln in lines:
        out.append("{:<64}{:>8d}".format(ln, de_pointer))
    return out


def write_iges(depth_map, work_x, work_y, work_z, path,
               product_id="photo-relief-cam"):
    """深さマップの上面をB-spline曲面としてIGESに出力する。

    Returns:
        書き出したパラメータデータ行数（曲面の規模の目安）。
    """
    from datetime import datetime

    path = str(path)
    rows, cols = depth_map.shape
    max_coord = max(work_x, work_y, work_z)

    # --- パラメータデータ（Entity 128） ---
    tokens = _build_param_records(depth_map, work_x, work_y, work_z)
    # DEポインタは 1（最初で唯一のエンティティ）。
    param_lines = _pack_param_lines(tokens, de_pointer=1)

    # --- 各セクション組み立て ---
    start_lines = ["Photo relief surface (IGES Entity 128 B-Spline surface)."]

    now = datetime.now().strftime("%Y%m%d.%H%M%S")
    fname = path.split("/")[-1]
    g = [
        "1H,", "1H;",
        _hollerith(product_id),
        _hollerith(fname),
        _hollerith("photo-relief-cam"),
        _hollerith("1.0"),
        "32", "38", "6", "308", "15",
        _hollerith(product_id),
        "1.0", "2", _hollerith("MM"), "1", "0.01",
        _hollerith(now),
        "1.0E-06", _fmt_real(max_coord),
        _hollerith("author"), _hollerith("org"),
        "11", "0",
        _hollerith(now),
    ]
    global_body = ",".join(g) + ";"
    # グローバルセクションも72桁で折り返す。
    global_lines = []
    remaining = global_body
    while remaining:
        if len(remaining) <= _LINE_DATA_WIDTH:
            global_lines.append(remaining)
            break
        seg = remaining[:_LINE_DATA_WIDTH]
        idx = max(seg.rfind(","), seg.rfind(";"))
        if idx == -1:
            idx = _LINE_DATA_WIDTH - 1
        global_lines.append(remaining[:idx + 1])
        remaining = remaining[idx + 1:]

    # --- ディレクトリエントリ（Entity 128, 2行で20フィールド） ---
    param_line_count = len(param_lines)
    de_line1 = "{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}".format(
        128, 1, 0, 0, 0, 0, 0, 0, 0)
    de_line2 = "{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8d}{:>8s}{:>8d}".format(
        128, 0, 0, param_line_count, 0, 0, 0, "", 0)

    # --- 出力 ---
    lines = []
    for i, c in enumerate(start_lines, start=1):
        lines.append(_section_line(c, "S", i))
    for i, c in enumerate(global_lines, start=1):
        lines.append(_section_line(c, "G", i))
    lines.append(_section_line(de_line1, "D", 1))
    lines.append(_section_line(de_line2, "D", 2))
    for i, c in enumerate(param_lines, start=1):
        # パラメータ行は既に65-72桁にポインタを含むので72桁固定。
        lines.append("{:<72}{}{:>7d}".format(c, "P", i))

    # --- ターミネートセクション ---
    term = "{:>8s}{:>7d}{:>8s}{:>7d}{:>8s}{:>7d}{:>8s}{:>7d}".format(
        "S", len(start_lines), "G", len(global_lines),
        "D", 2, "P", len(param_lines))
    lines.append(_section_line(term, "T", 1))

    with open(path, "w", encoding="ascii") as f:
        f.write("\n".join(lines) + "\n")

    return len(param_lines)
