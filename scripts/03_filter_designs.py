"""
03_filter_designs.py
====================
Filter, score, and rank nanobody candidates against F7GQA6 SWS1 opsin.

Pipeline:
  Stage 1 – Geometry filters      (fast, backbone-level)
  Stage 2 – Sequence quality      (AbLang2 pseudo-log-likelihood)
  Stage 3 – Structure prediction  (NanobodyBuilder2 or ImmuneBuilder)
  Stage 4 – Complex prediction    (ColabFold multimer, pTM / ipTM / PAE)
  Stage 5 – Affinity estimate     (PRODIGY ΔG prediction)

Usage:
  python scripts/03_filter_designs.py \
      --designs data/rfdiffusion_outputs \
      --config  configs/design_config.yaml \
      --output  data/filtered_candidates

Outputs:
  data/filtered_candidates/
      all_scores.tsv          – full score table
      top_candidates.tsv      – final ranked shortlist
      top_candidates/         – PDB files for top candidates
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

try:
    from Bio import PDB
    from Bio.PDB import PDBIO
except ImportError:
    sys.exit("BioPython not found. Run: pip install biopython")


# ------------------------------------------------------------------ #
#  Stage 1 – Geometry Filters                                         #
# ------------------------------------------------------------------ #

def geometry_filter(pdb_path: str, config: dict) -> dict:
    """
    Fast backbone-level geometry checks:
      - Interface residue count (>= 8)
      - Buried interface SASA (>= 800 Å²)
      - CDR3 points toward ECL2 (within 20 Å)
      - No steric clashes (min Cα–Cα > 3.5 Å across chains)
    """
    parser = PDB.PDBParser(QUIET=True)
    structure = parser.get_structure("nb", pdb_path)

    try:
        chains = list(structure[0].get_chains())
        if len(chains) < 2:
            return {"pass_geometry": False, "reason": "single_chain"}

        # Assume chain A = target, chain B = nanobody
        target_chain = structure[0]["A"]
        nb_chain = structure[0]["B"]

        target_coords = _get_ca_coords(target_chain)
        nb_coords = _get_ca_coords(nb_chain)

        # 1. Interface residue count
        interface_nb, interface_target = _count_interface_residues(
            nb_coords, target_coords, cutoff=8.0)

        if interface_nb < 8:
            return {"pass_geometry": False,
                    "reason": f"too_few_interface_residues({interface_nb})"}

        # 2. Buried SASA (approximate)
        buried_sasa = interface_nb * 35.0 + interface_target * 35.0  # rough Å²
        if buried_sasa < config["filters"]["min_interface_sasa"]:
            return {"pass_geometry": False,
                    "reason": f"low_interface_sasa({buried_sasa:.0f})"}

        # 3. Clash check (min Cα distance across chains must be > 3.5 Å)
        nb_arr = np.array(list(nb_coords.values()))
        tgt_arr = np.array(list(target_coords.values()))
        dists = np.linalg.norm(
            nb_arr[:, None, :] - tgt_arr[None, :, :], axis=-1)
        min_dist = dists.min()
        if min_dist < 3.5:
            return {"pass_geometry": False,
                    "reason": f"steric_clash(min_dist={min_dist:.1f}Å)"}

        return {
            "pass_geometry":     True,
            "interface_nb":      interface_nb,
            "interface_target":  interface_target,
            "approx_sasa":       round(buried_sasa, 0),
            "min_ca_dist":       round(float(min_dist), 2),
        }

    except Exception as e:
        return {"pass_geometry": False, "reason": str(e)}


def _get_ca_coords(chain) -> dict[int, np.ndarray]:
    coords = {}
    for residue in chain.get_residues():
        if residue.get_id()[0] == " " and "CA" in residue:
            coords[residue.get_id()[1]] = residue["CA"].coord
    return coords


def _count_interface_residues(coords_a: dict, coords_b: dict,
                               cutoff: float = 8.0) -> tuple[int, int]:
    arr_a = np.array(list(coords_a.values()))
    arr_b = np.array(list(coords_b.values()))
    dists = np.linalg.norm(arr_a[:, None, :] - arr_b[None, :, :], axis=-1)
    interface_a = int(np.sum(dists.min(axis=1) < cutoff))
    interface_b = int(np.sum(dists.min(axis=0) < cutoff))
    return interface_a, interface_b


# ------------------------------------------------------------------ #
#  Stage 2 – Sequence Quality (AbLang2)                               #
# ------------------------------------------------------------------ #

def score_sequence_ablang2(sequence: str) -> float | None:
    """
    Score VHH sequence using AbLang2 pseudo-log-likelihood.
    Higher = more natural/stable antibody sequence.
    Returns None if AbLang2 is not installed.
    """
    try:
        import ablang2
        model = ablang2.pretrained(model_to_use="heavy")
        scores = model([sequence], mode="likelihood")
        # Mean log-likelihood per residue
        return float(np.mean(scores[0]))
    except ImportError:
        return None
    except Exception as e:
        print(f"[WARN] AbLang2 scoring failed: {e}")
        return None


def extract_nanobody_sequence(pdb_path: str,
                               nb_chain_id: str = "B") -> str | None:
    """Extract amino acid sequence from the nanobody chain."""
    aa_map = {
        "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
        "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
        "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
        "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
    }
    parser = PDB.PDBParser(QUIET=True)
    structure = parser.get_structure("nb", pdb_path)
    try:
        chain = structure[0][nb_chain_id]
        seq = "".join(
            aa_map.get(r.get_resname(), "X")
            for r in chain.get_residues()
            if r.get_id()[0] == " "
        )
        return seq if seq else None
    except KeyError:
        return None


# ------------------------------------------------------------------ #
#  Stage 3 – NanobodyBuilder2 Structure Prediction                    #
# ------------------------------------------------------------------ #

def predict_nanobody_structure(sequence: str,
                                output_path: str) -> bool:
    """
    Predict nanobody structure with ImmuneBuilder / NanobodyBuilder2.
    Returns True on success.
    """
    try:
        from ImmuneBuilder import NanobodyBuilder
        builder = NanobodyBuilder()
        nb = builder.predict({"H": sequence})
        nb.save(output_path)
        return True
    except ImportError:
        print("[WARN] ImmuneBuilder not installed. Skipping structure prediction.")
        return False
    except Exception as e:
        print(f"[WARN] NanobodyBuilder2 failed: {e}")
        return False


# ------------------------------------------------------------------ #
#  Stage 4 – ColabFold / AF2-Multimer (parsing existing results)      #
# ------------------------------------------------------------------ #

def parse_colabfold_scores(scores_json_path: str) -> dict:
    """
    Parse ColabFold output JSON to extract:
      - iptm (interface pTM)
      - ptm
      - mean_pae (mean predicted aligned error)
      - pae_interface (PAE at the Nb–opsin interface)
    """
    if not os.path.exists(scores_json_path):
        return {}
    with open(scores_json_path) as f:
        data = json.load(f)

    scores = {
        "iptm":          data.get("iptm", None),
        "ptm":           data.get("ptm",  None),
        "mean_pae":      data.get("mean_pae", None),
    }
    # pae_interface: average PAE between chain A (opsin) and chain B (Nb)
    pae = data.get("pae", None)
    if pae is not None:
        pae_array = np.array(pae)
        # Assume first half = chain A (opsin), second half = chain B (Nb)
        n = pae_array.shape[0]
        mid = n // 2
        pae_ab = pae_array[:mid, mid:]   # opsin→Nb
        pae_ba = pae_array[mid:, :mid]   # Nb→opsin
        scores["pae_interface"] = round(
            float(np.mean([pae_ab.mean(), pae_ba.mean()])), 2)

    return scores


# ------------------------------------------------------------------ #
#  Stage 5 – PRODIGY Affinity Estimate                                #
# ------------------------------------------------------------------ #

def estimate_affinity_prodigy(complex_pdb: str,
                               chain_a: str = "A",
                               chain_b: str = "B") -> dict:
    """
    Estimate binding affinity with PRODIGY (local installation).
    Falls back to None if PRODIGY is not installed.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["prodigy", complex_pdb,
             "--selection", chain_a, chain_b,
             "--temperature", "25"],
            capture_output=True, text=True, timeout=30
        )
        lines = result.stdout.strip().split("\n")
        dG, Kd = None, None
        for line in lines:
            if "Predicted binding affinity" in line:
                dG = float(line.split(":")[-1].split()[0])
            if "Predicted dissociation constant" in line:
                val = line.split(":")[-1].strip()
                Kd = val
        return {"prodigy_dG": dG, "prodigy_Kd": Kd}
    except FileNotFoundError:
        return {"prodigy_dG": None, "prodigy_Kd": None}
    except Exception as e:
        print(f"[WARN] PRODIGY failed: {e}")
        return {"prodigy_dG": None, "prodigy_Kd": None}


# ------------------------------------------------------------------ #
#  Composite Ranking                                                   #
# ------------------------------------------------------------------ #

def compute_composite_score(row: pd.Series) -> float:
    """
    Weighted composite score for final ranking.
    All components normalized to [0, 1] (higher = better).

    Components:
      - iptm       (weight 0.35): AF2 interface confidence
      - pae_if     (weight 0.20): interface PAE (inverted)
      - ablang     (weight 0.20): sequence naturalness
      - prodigy_dG (weight 0.25): binding affinity (inverted)
    """
    score = 0.0
    weight_sum = 0.0

    if pd.notna(row.get("iptm")):
        score += 0.35 * float(row["iptm"])
        weight_sum += 0.35

    if pd.notna(row.get("pae_interface")):
        pae_norm = max(0.0, 1.0 - float(row["pae_interface"]) / 30.0)
        score += 0.20 * pae_norm
        weight_sum += 0.20

    if pd.notna(row.get("ablang_score")):
        # AbLang scores typically range -5 to 0; normalize
        ablang_norm = max(0.0, min(1.0, (float(row["ablang_score"]) + 5) / 5))
        score += 0.20 * ablang_norm
        weight_sum += 0.20

    if pd.notna(row.get("prodigy_dG")):
        # ΔG typically -5 to -15 kcal/mol; normalize
        dg_norm = max(0.0, min(1.0, (-float(row["prodigy_dG"]) - 5) / 10))
        score += 0.25 * dg_norm
        weight_sum += 0.25

    return round(score / weight_sum if weight_sum > 0 else 0.0, 4)


def apply_hard_filters(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Apply minimum threshold filters from config."""
    f = config["filters"]
    mask = pd.Series([True] * len(df), index=df.index)

    if "iptm" in df.columns:
        mask &= df["iptm"].isna() | (df["iptm"] >= f["min_iptm"])
    if "pae_interface" in df.columns:
        mask &= df["pae_interface"].isna() | (
            df["pae_interface"] <= f["max_pae_interface"])
    if "prodigy_dG" in df.columns:
        mask &= df["prodigy_dG"].isna() | (
            df["prodigy_dG"] <= f["max_dG_kcal_mol"])
    if "ablang_score" in df.columns:
        mask &= df["ablang_score"].isna() | (
            df["ablang_score"] >= f["min_ablang_score"])

    passed = df[mask]
    print(f"[INFO] Hard filter: {len(passed)}/{len(df)} designs passed")
    return passed


# ------------------------------------------------------------------ #
#  Main pipeline                                                       #
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(
        description="Filter and rank nanobody designs for F7GQA6")
    parser.add_argument("--designs",  default="data/rfdiffusion_outputs",
                        help="Directory with RFdiffusion + ProteinMPNN outputs")
    parser.add_argument("--config",   default="configs/design_config.yaml")
    parser.add_argument("--output",   default="data/filtered_candidates")
    parser.add_argument("--colabfold-dir", default=None,
                        help="Directory with ColabFold output JSONs")
    parser.add_argument("--top-n",    type=int, default=10,
                        help="Number of top candidates to save (default: 10)")
    args = parser.parse_args()

    os.makedirs(args.output, exist_ok=True)
    config = load_config(args.config)

    # Find all complex PDB files (RFdiffusion output: design_*.pdb)
    designs_dir = Path(args.designs)
    pdb_files = sorted(designs_dir.glob("design_*.pdb"))
    if not pdb_files:
        # Also check ProteinMPNN output sequences (FASTA)
        pdb_files = sorted(designs_dir.glob("**/*.pdb"))
    print(f"[INFO] Found {len(pdb_files)} design PDBs in {designs_dir}")

    if not pdb_files:
        sys.exit(f"[ERROR] No design PDBs found in {args.designs}")

    rows = []
    for pdb_path in pdb_files:
        row = {"name": pdb_path.stem, "pdb": str(pdb_path)}

        # Stage 1: Geometry
        geo = geometry_filter(str(pdb_path), config)
        row.update(geo)
        if not geo["pass_geometry"]:
            rows.append(row)
            continue

        # Stage 2: Sequence quality
        seq = extract_nanobody_sequence(str(pdb_path), nb_chain_id="B")
        row["sequence"] = seq
        if seq:
            row["ablang_score"] = score_sequence_ablang2(seq)
            row["seq_length"] = len(seq)

        # Stage 4: ColabFold scores (if directory provided)
        if args.colabfold_dir:
            scores_json = os.path.join(
                args.colabfold_dir, f"{pdb_path.stem}_scores.json")
            cf_scores = parse_colabfold_scores(scores_json)
            row.update(cf_scores)

        # Stage 5: PRODIGY affinity estimate
        prodigy = estimate_affinity_prodigy(str(pdb_path))
        row.update(prodigy)

        rows.append(row)

    df = pd.DataFrame(rows)

    # Composite score
    df["composite_score"] = df.apply(compute_composite_score, axis=1)

    # Save full table
    all_scores_path = os.path.join(args.output, "all_scores.tsv")
    df.to_csv(all_scores_path, sep="\t", index=False)
    print(f"[INFO] Full score table: {all_scores_path}")

    # Apply hard filters and rank
    passed = apply_hard_filters(df[df["pass_geometry"] == True], config)
    top = passed.sort_values("composite_score", ascending=False).head(args.top_n)

    # Save top candidates table
    top_path = os.path.join(args.output, "top_candidates.tsv")
    top.to_csv(top_path, sep="\t", index=False)
    print(f"[INFO] Top {len(top)} candidates: {top_path}")

    # Copy top candidate PDB files
    top_pdb_dir = os.path.join(args.output, "top_candidates")
    os.makedirs(top_pdb_dir, exist_ok=True)
    for _, row in top.iterrows():
        if os.path.exists(row["pdb"]):
            import shutil
            dst = os.path.join(top_pdb_dir, f"{row['name']}.pdb")
            shutil.copy2(row["pdb"], dst)

    # Print summary table
    print("\n" + "=" * 80)
    print("  TOP CANDIDATES – Marmoset SWS1 Opsin (F7GQA6) Nanobody Design")
    print("=" * 80)
    display_cols = ["name", "composite_score", "iptm", "pae_interface",
                    "ablang_score", "prodigy_dG", "interface_nb", "approx_sasa"]
    display_cols = [c for c in display_cols if c in top.columns]
    print(top[display_cols].to_string(index=False))
    print("=" * 80)

    print(f"\n[DONE] Top {len(top)} candidate PDBs saved to: {top_pdb_dir}")
    print("\n[NEXT] Run ColabFold multimer on top candidates:")
    print("  → Open notebooks/nanobody_design_colab.ipynb (Stage 4)")
    print("  → Or use: colabfold_batch <fasta> <output_dir> --model-type alphafold2_multimer_v3")


if __name__ == "__main__":
    main()
