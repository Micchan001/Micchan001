# スペクトル近似ツール 使い方ガイド

複数の基底スペクトルを線形結合して、ターゲットスペクトルを最もよく近似する手法を実装したノートブックです。

---

## Google Colab での実行方法

### 手順 1: ノートブックを開く

1. [Google Colab](https://colab.research.google.com/) を開く
2. メニューから「ファイル」→「ノートブックをアップロード」を選択
3. このリポジトリの `spectrum_approximation.ipynb` をアップロード

または GitHub から直接開く場合：

```
ファイル → GitHubからノートブックを開く
→ リポジトリURLを入力 → spectrum_approximation.ipynb を選択
```

### 手順 2: セルを順番に実行する

「ランタイム」→「すべてのセルを実行」で一括実行できます。

---

## ノートブックの構成

| セル | 内容 |
|------|------|
| 0 | パッケージ確認（numpy / scipy / matplotlib） |
| 1 | ライブラリのインポート |
| 2-A | サンプルスペクトルの自動生成 |
| 2-B | 実データの読み込み（CSV対応） |
| 3 | 入力スペクトルの可視化 |
| 4 | 3手法での近似計算 |
| 5 | 近似結果のグラフ比較 |
| 6 | 重みの棒グラフ比較 |
| 7 | 残差スペクトル |
| 8 | まとめ・手法の選び方 |
| 9 | 基底スペクトルの数を変える例 |

---

## 3つの近似手法

### 手法 1: 最小二乗法（制約なし）

```
minimize ||A·w - target||²
```

- 最も基本的な方法。負の重みも許容。
- `numpy.linalg.lstsq` を使用。
- **向いている場面**: 物理的な制約がなく、とにかく残差を最小化したいとき。

### 手法 2: 非負最小二乗法（NNLS）

```
minimize ||A·w - target||²  subject to  w ≥ 0
```

- 各重みが 0 以上になるよう制約。
- `scipy.optimize.nnls` を使用。
- **向いている場面**: 濃度・反射率など、物理的に負にならない量を扱うとき。

### 手法 3: 混合比制約

```
minimize ||A·w - target||²  subject to  w ≥ 0,  Σw = 1
```

- 重みの合計が 1 になるよう制約（混合比・配合比）。
- `scipy.optimize.minimize` (SLSQP法) を使用。
- **向いている場面**: 材料の混合比、成分分析など。

---

## 自分のデータを使う方法

### CSV ファイルの場合

ファイル形式（例）：

```
wavelength,intensity
400.0,0.012
401.0,0.015
...
```

ノートブックのセル **2-B** のコメントを外して、ファイルをアップロードします：

```python
from google.colab import files
uploaded = files.upload()  # ファイル選択ダイアログ

import io
data1 = np.loadtxt(io.BytesIO(uploaded['spectrum1.csv']), delimiter=',', skiprows=1)
wavelength = data1[:, 0]
s1 = data1[:, 1]
# s2, s3, target も同様に読み込む
```

### NumPy 配列がある場合

```python
# 直接代入するだけでOK
wavelength = np.array([...])
s1 = np.array([...])
s2 = np.array([...])
s3 = np.array([...])
target = np.array([...])
```

---

## 基底スペクトルの数を変える

セル 4 の行列定義を変えるだけです：

```python
# 2つの場合
A = np.column_stack([s1, s2])

# 3つの場合（デフォルト）
A = np.column_stack([s1, s2, s3])

# 4つの場合
A = np.column_stack([s1, s2, s3, s4])
```

---

## 出力ファイル

- `spectrum_approximation_result.png` — 近似結果の比較グラフ（自動保存）

---

## 必要なライブラリ

| ライブラリ | バージョン | 用途 |
|-----------|-----------|------|
| numpy | ≥ 1.20 | 行列演算・最小二乗法 |
| scipy | ≥ 1.7 | NNLS・制約付き最適化 |
| matplotlib | ≥ 3.4 | グラフ描画 |

Google Colab には標準でインストール済みです。ローカルで実行する場合：

```bash
pip install numpy scipy matplotlib
```

---

## よくある質問

**Q: RMSE とは？**
A: Root Mean Square Error（二乗平均平方根誤差）。値が小さいほど近似精度が高い。

**Q: 手法 1（最小二乗法）で負の重みが出た。**
A: 基底スペクトルが線形独立でないか、ターゲットが基底スペクトルの範囲を超えている可能性があります。NNLS（手法 2）を試してください。

**Q: 手法 3 で RMSE が大きくなった。**
A: 制約（合計=1）が強すぎるためです。ターゲットが基底スペクトルの単純な混合で表現できない場合に起こります。手法 1・2 も合わせて確認してください。

**Q: 波長軸が異なるスペクトルを混ぜたい。**
A: 事前に同じ波長グリッドに補間（`numpy.interp` や `scipy.interpolate.interp1d`）してから使用してください。
