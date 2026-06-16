# relief-forge

画像（任意のグレースケール変換可能な写真・テクスチャ）を、CNC加工用の
**レリーフ**へ鋳造（forge）する CLI ツール群です。2 つの使い方があります。

1. **画像 → 平面レリーフ**（`relief.py`）: 画像を平らな板に彫り込み、**IGES**
   （B-spline 曲面）・**NC（Gコード）**・陰影プレビュー **PNG** を生成。
2. **画像 → 既存STLへ転写**（`shape_relief.py`）: 包丁の柄などの既存ソリッド
   STL の上面に画像を彫り込み、彫り込み後の **STL**・**NC**・**PNG** を生成。

IGES は彫り込み面（上面）を B-spline 曲面（IGES Entity 128）として書き出すため、
CAD/CAM で解析的な曲面として読み込めます。

## 方式（グレースケール・ハイトマップ方式）

画像をグレースケール化し、明度を切削深さに**比例写像**します。
暗い画素ほど深く彫り、明るい画素は浅く彫る／彫りません。明度レンジは画像の
実 min–max で 0–1 に正規化してから深さへ写像します。これにより画像が持つ全情報
（濃淡・輪郭・パターン）を、線抽出やパターン生成なしでそのまま深さに落とせます。

> 年輪を数式（サインカーブ／ガウシアン）でモデル化する方式や V ビット線彫りは
> 検証の結果、品質不足のため採用していません（ボールエンドミルによるレリーフ前提）。

## インストール

```bash
pip install -r requirements.txt
```

依存: numpy, pillow, matplotlib（Python 3）。IGES 出力は追加ライブラリ不要で
ASCII を直接生成します。

## 基本コマンド

```bash
python src/relief.py samples/images/cherry.jpg --out output/
```

- IGES: `output/{stem}_relief.igs`
- NC : `output/{stem}_relief.nc`
- PNG: `output/{stem}_relief.png`

パラメータは CLI 引数（例 `--max_depth 0.8`）または JSON 設定ファイル
（`--config myconf.json`）で上書きできます。`--timestamp` で上書きを回避、
`--no-fit-aspect` で WORK_Y の自動調整を無効化します。

## 既存STLへの木目彫り込み（面ごと2.5D）

平らな板ではなく、**既存のソリッドSTL（包丁の柄など）の上面**に木目を彫り込む
こともできます。上から見て高さが一意に決まる面（2.5D）が対象です。

```bash
# テスト用の柄STLを生成（実STLが無い時の確認用）
python src/make_test_handle.py

# 対象STL + 木目画像 → 彫り込み
python src/shape_relief.py samples/shapes/test_handle.stl samples/images/cherry.jpg --out output/
```

- STL: `output/{shape}_{image}_grain.stl`（彫り込み後の上面ソリッド、可視化用）
- NC : `output/{shape}_{image}_grain.nc`（マスク付き表面仕上げラスター）
- PNG: `output/{shape}_{image}_grain.png`（陰影プレビュー）

処理は、対象STLから上面高さマップ `H(x,y)` とマスクを抽出し、木目深さ `d` を
マスク内だけ差し引いて `Z = H − d` を彫る方式です。対象STLの置き方や注意点は
`samples/shapes/README.md` を参照してください。全周への巻き付けは3軸では不可で、
裏面など別の面は向きを変えてのマルチセットアップになります。

## パラメータ一覧

| パラメータ | 既定値 | 説明 |
|------------|--------|------|
| WORK_X | 150.0 | mm 板の長さ |
| WORK_Y | 100.0 | mm 板の幅（画像アスペクトに合わせ調整可） |
| WORK_Z | 20.0 | mm 板の厚み（曲面の基準高さ） |
| MAX_DEPTH | 0.1 | mm 最大切削深さ（暗部）。実加工を考慮し浅めに設定 |
| MIN_DEPTH | 0.0 | mm 最小切削深さ（明部） |
| BALL_DIA | 1.0 | mm ボールエンドミル径 |
| STEP_OVER | 0.3 | mm 走査線ピッチ |
| SAMPLE_PITCH_X | 0.3 | mm X方向サンプリング間隔 |
| FEED_CUT | 1000 | mm/min 切削送り |
| FEED_PLUNGE | 400 | mm/min 突込み送り |
| SPINDLE_RPM | 18000 | 主軸回転数 |
| SAFE_Z | 5.0 | mm 安全高さ |
| STL_COLS | 500 | 曲面の制御点 列数（解像度。名称は後方互換のため STL_ 接頭辞のまま） |
| STL_ROWS | 333 | 曲面の制御点 行数（アスペクトで自動調整） |
| IGES_PATCH_PTS | 64 | IGES曲面の1パッチあたり片側最大制御点数（タイル分割の細かさ） |

## 出力規模の目安と注意

- **IGES**: 既定の制御点解像度は 500×333 程度。上面の格子点を制御点とする線形
  B-spline 曲面（格子点を厳密に通る区分双線形面）を、CADで軽快に読めるよう
  複数パッチ（タイル）に分割して出力します。隣接パッチは境界の制御点を共有する
  ため隙間なく連続します。500列が品質と読み込み時間の最適点で、600以上は差が
  ほぼ分かりません。重い場合は `--iges_patch_pts` を下げると分割が細かくなり
  読み込みが速くなります。
- **NC**: 17 万行・数 MB 規模になります。生成時に標準出力で警告します。
  将来的な点列間引き（直線近似での圧縮）は `gcode_writer.compress_line` に
  関数を分離してあります（現状は未実装）。

## リポジトリ肥大化対策

生成物（IGES・NC・PNG）は大きいためコミットしません。`output/` と
`*.igs` / `*.iges` / `*.stl` / `*.nc` / `*.gcode` は `.gitignore` で除外しています。サンプル画像
（小さい jpg）とコードだけがあれば誰でも同じ出力を再現できます。

## ⚠️ 重要な免責

生成される NC は**機械非依存の素体**です。実機の制御装置・工具・原点に合わせた
調整と、シミュレーション・試し切りによる検証が**必須**です。
**未検証データを本番加工に流さないでください。**
