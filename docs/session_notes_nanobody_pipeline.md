# ナノボディ設計パイプライン — 作業記録

対象: marmoset (Callithrix jacchus) SWS1 cone opsin (UniProt: F7GQA6)
ブランチ: `claude/antibody-design-tool-dF1eH`

## パイプライン概要

1. `scripts/01_prepare_target.py` — AF2構造の読み込み、トポロジー割当、SASA計算、ECL2ホットスポット選定
2. `scripts/02_run_rfdiffusion.py` — RFdiffusionでバックボーン生成 → ProteinMPNNで配列設計
3. NanobodyBuilder2 / ImmuneBuilder — 構造予測
4. ColabFold (AF2-multimer) — 複合体スコアリング (ipTM/pTM/PAE)
5. PRODIGY — 結合親和性 (ΔG/Kd) 推定
6. `scripts/03_filter_designs.py` — 複合スコアによるフィルタリング・ランキング

実行環境: `notebooks/nanobody_design_colab.ipynb` (Google Colab, 34セル/11セクション)

## 解決済みの問題

- `se3-transformer` はPyPIに存在せず、`/content/RFdiffusion/env/SE3Transformer` から直接インストールが必要
- `pip install --no-deps -e .` で抜ける依存（hydra-core, omegaconf, iopath, opt_einsum, e3nn, pyrsistent, decorator）を明示インストール
- `dgl` はCUDAバージョンに応じたwheelが必要（`nvidia-smi`の出力をパースしてcu121/cu118/CPUを判定）。Cell 5だけでなくCell 15/18にも自己完結的にインストール処理を追加し、ランタイム再起動やセル順序のズレに対応
- `os.environ['RFDIFFUSION_PATH']` 等がセル間で失われる問題 → Cell 15/18で`setdefault`により自前で再設定
- リポジトリclone時にブランチ指定漏れ（`main`にはscripts/が無い）→ `BRANCH='claude/antibody-design-tool-dF1eH'`を明示してclone
- ProteinMPNNの`--pdb_path_multi`に不正な値（`"1"`）を渡していたバグ → `pdb_paths.json`を生成して正しく渡すよう修正
- `02_run_rfdiffusion.py`のフォールバックパスを`/opt/...`から`/content/...`に修正
- Cell 6 (`import os`漏れ), Cell 23 (未使用import), Cell 26/28 (1チェーン構造ディレクトリを参照していたバグ → 2チェーン構造の`data/rfdiffusion_outputs`に修正), Cell 33 (`from pathlib import Path`漏れ) を一括修正

## 未解決の課題

### 1. AF2構造ファイルの転送
ユーザーのローカルPC上のパス:
`C:\Users\kirio\OneDrive - NITech\デスクトップ\神取研\構造解析\構造モデル(AlphaFold2)\MB\WT 220708\F7GQA6_AF2.pdb`

このサーバーはサンドボックス環境のため、ユーザーのWindows/OneDriveファイルシステムには直接アクセスできず、また外部プロキシがAlphaFold DB等への直接ダウンロードもブロックしている（`Proxy tunneling failed: Forbidden`）。

選択肢:
- A. OneDriveの共有リンクを発行してダウンロード
- B. GitHubリポジトリにPDBファイルをコミットしてもらい、こちらで`git pull`
- C. base64エンコードしてチャットに貼り付け

### 2. ステップ実行の再開
ファイル配置後、以下から再開:
```
python scripts/01_prepare_target.py --config configs/design_config.yaml --pdb data/F7GQA6_AF2.pdb
```

## Obsidianへの保存について

このサーバーには `/`（ext4ルート）とツール用の読み取り専用マウントのみが存在し、ユーザーのローカルマシン上のObsidian Vaultへの直接アクセス経路はありません。そのため、このファイルをリポジトリ内に保存し、後ほどユーザー側でObsidian Vaultにコピーする形としました。
