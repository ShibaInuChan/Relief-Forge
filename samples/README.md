# サンプル

`samples/images/` の画像はリポジトリにコミットされています（各 ~75KB と小さい）。

## 重い生成物はコミットしない

サンプルから生成される STL / NC / PNG は**コミットしません**。
これらは画像とコードがあれば誰でも同じ出力を再現できるためです
（重い生成物はソースから再現可能だからリポジトリに置かない、という原則）。

## 再生成コマンド

```bash
python src/relief.py samples/images/cherry.jpg --out output/
python src/relief.py samples/images/pine.jpg   --out output/
python src/relief.py samples/images/alder.jpg  --out output/
```

生成物は `output/`（`.gitignore` で除外）に保存されます。

| サンプル | 説明 |
|----------|------|
| cherry.jpg | 緩い年輪・濃いめの木目 |
| pine.jpg   | 明るく年輪間隔の広い木目 |
| alder.jpg  | 細かい年輪・中庸な明度 |

> 注: 同梱のサンプル画像は方式検証用に生成した木目調のテスト画像です。
> 任意の写真（jpg/png）を入力に使えます。
