"""
01_prepare_target.py
====================
Prepare the AF2 structure of marmoset SWS1 opsin (F7GQA6) for nanobody design.

Steps:
  1. Load AF2 structure and validate
  2. Assign transmembrane topology (from config)
  3. Identify solvent-exposed ECL2 residues (SASA analysis)
  4. Select hotspot residues for RFdiffusion
  5. Extract extracellular-domain-only PDB (input to RFdiffusion)
  6. Update config with final hotspot residues

Usage:
  python scripts/01_prepare_target.py --config configs/design_config.yaml \
                                      --pdb data/F7GQA6_AF2.pdb

Output:
  data/F7GQA6_extracellular.pdb   -- ECL-only structure for RFdiffusion
  data/F7GQA6_hotspots.json       -- Selected hotspot residues
  data/F7GQA6_topology.tsv        -- Per-residue topology assignment
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
    from Bio.PDB import PDBIO, Select
    from Bio.PDB.DSSP import DSSP
except ImportError:
    sys.exit("BioPython not found. Run: pip install biopython")


# ------------------------------------------------------------------ #
#  Constants                                                           #
# ------------------------------------------------------------------ #

# ECL2 beta-hairpin in SWS1: approximate secondary-structure positions
# (residues forming the beta-sheet core of ECL2 should not be hotspots)
ECL2_BETA_SHEET_OFFSET = [0, 1, 2, -1, -2]  # relative to Cys187

# Minimum pLDDT score to consider a residue (AF2 confidence)
MIN_PLDDT = 50.0

# Minimum relative SASA to count as solvent-exposed
MIN_RELATIVE_SASA = 0.25


# ------------------------------------------------------------------ #
#  Utility classes                                                     #
# ------------------------------------------------------------------ #

class TopologySelector(Select):
    """BioPython Select subclass: keep only residues in allowed_ids."""

    def __init__(self, chain_id: str, residue_ids: list[int]):
        self.chain_id = chain_id
        self.residue_ids = set(residue_ids)

    def accept_residue(self, residue):
        chain = residue.get_parent()
        res_id = residue.get_id()[1]
        return chain.id == self.chain_id and res_id in self.residue_ids


# ------------------------------------------------------------------ #
#  Core functions                                                      #
# ------------------------------------------------------------------ #

def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def load_structure(pdb_path: str) -> PDB.Structure.Structure:
    parser = PDB.PDBParser(QUIET=True)
    structure = parser.get_structure("target", pdb_path)
    print(f"[INFO] Loaded structure: {pdb_path}")
    n_residues = sum(1 for _ in structure.get_residues())
    print(f"       Total residues: {n_residues}")
    return structure


def assign_topology(structure: PDB.Structure.Structure,
                    topology: dict,
                    chain_id: str) -> pd.DataFrame:
    """
    Assign topology labels (TM1..7, ECL1..3, ICL1..3, N-term, C-term)
    to each residue based on the config ranges.
    """
    chain = structure[0][chain_id]
    residue_list = [r for r in chain.get_residues()
                    if r.get_id()[0] == " "]  # exclude HETATM

    region_map: dict[int, str] = {}

    for category, regions in topology.items():
        for region_name, (start, end) in regions.items():
            for resid in range(start, end + 1):
                region_map[resid] = region_name

    rows = []
    for residue in residue_list:
        resid = residue.get_id()[1]
        resname = residue.get_resname()
        region = region_map.get(resid, "UNKNOWN")
        is_extracellular = region in (
            "N_terminus", "ECL1", "ECL2", "ECL3"
        )

        # AF2 pLDDT stored in B-factor column
        plddt = np.mean([a.get_bfactor() for a in residue.get_atoms()])

        rows.append({
            "resid":           resid,
            "resname":         resname,
            "region":          region,
            "is_extracellular": is_extracellular,
            "plddt":           round(plddt, 1),
        })

    df = pd.DataFrame(rows)
    print(f"[INFO] Topology assigned ({len(df)} residues)")
    print(df.groupby("region")["resid"].count().to_string())
    return df


def compute_sasa(pdb_path: str,
                 structure: PDB.Structure.Structure,
                 chain_id: str) -> dict[int, float]:
    """
    Compute per-residue relative SASA using DSSP (if available),
    falling back to a simple sphere-overlap approximation.

    Returns: dict {resid: relative_sasa}
    """
    try:
        model = structure[0]
        dssp = DSSP(model, pdb_path, dssp="mkdssp")
        sasa_map = {}
        for key in dssp.keys():
            if key[0] == chain_id:
                resid = key[1][1]
                sasa_map[resid] = dssp[key][3]  # relative ASA
        print(f"[INFO] SASA computed via DSSP ({len(sasa_map)} residues)")
        return sasa_map
    except Exception as e:
        print(f"[WARN] DSSP failed ({e}). Using CB-distance approximation.")
        return _approximate_sasa(structure, chain_id)


def _approximate_sasa(structure: PDB.Structure.Structure,
                      chain_id: str) -> dict[int, float]:
    """
    Rough exposure estimate: fraction of a sphere around Cβ (or Cα for Gly)
    that is unoccupied by other heavy atoms within 8 Å.
    """
    chain = structure[0][chain_id]
    residues = [r for r in chain.get_residues() if r.get_id()[0] == " "]

    cb_coords = {}
    for r in residues:
        atom_name = "CB" if "CB" in r else "CA"
        if atom_name in r:
            cb_coords[r.get_id()[1]] = r[atom_name].coord

    sasa_map = {}
    coord_array = np.array(list(cb_coords.values()))
    resids = list(cb_coords.keys())

    for i, resid in enumerate(resids):
        center = cb_coords[resid]
        dists = np.linalg.norm(coord_array - center, axis=1)
        n_neighbors = np.sum((dists > 0.1) & (dists < 8.0))
        # Empirical: ~0 neighbors → exposed, ~20+ neighbors → buried
        relative_sasa = max(0.0, 1.0 - n_neighbors / 20.0)
        sasa_map[resid] = round(relative_sasa, 3)

    return sasa_map


def select_hotspots(topo_df: pd.DataFrame,
                    sasa_map: dict[int, float],
                    config: dict) -> list[str]:
    """
    Select ECL2 hotspot residues for RFdiffusion by applying:
      1. Region must be ECL2
      2. pLDDT >= MIN_PLDDT
      3. Relative SASA >= MIN_RELATIVE_SASA
      4. Exclude Cys187 (disulfide bond partner)
      5. Prefer central/exposed residues

    Returns list of hotspot strings, e.g. ["A178", "A181", "A191"]
    """
    chain_id = config["target"]["chain_id"]
    cys_disulfide = config["functional_residues"]["disulfide"]
    hotspot_candidates = config["epitope"]["hotspot_candidates"]

    ecl2_df = topo_df[topo_df["region"] == "ECL2"].copy()
    ecl2_df["sasa"] = ecl2_df["resid"].map(sasa_map).fillna(0.0)

    # Apply filters
    mask = (
        ecl2_df["resid"].isin(hotspot_candidates) &
        (ecl2_df["plddt"] >= MIN_PLDDT) &
        (ecl2_df["sasa"] >= MIN_RELATIVE_SASA) &
        (~ecl2_df["resid"].isin(cys_disulfide))
    )
    filtered = ecl2_df[mask].sort_values("sasa", ascending=False)

    # Select top 6 residues (well-distributed along ECL2)
    # Ensure spacing >= 2 residues to avoid clustering
    selected = []
    last_selected = -999
    for _, row in filtered.iterrows():
        if row["resid"] - last_selected >= 2:
            selected.append(row)
            last_selected = row["resid"]
        if len(selected) >= 6:
            break

    hotspots = [f"{chain_id}{r['resid']}" for r in selected]

    print(f"\n[INFO] Selected hotspot residues ({len(hotspots)}):")
    for hs in hotspots:
        resid = int(hs[1:])
        row = ecl2_df[ecl2_df["resid"] == resid].iloc[0]
        print(f"       {hs}  {row['resname']}  "
              f"pLDDT={row['plddt']:.0f}  SASA={row['sasa']:.2f}")
    return hotspots


def extract_extracellular_pdb(structure: PDB.Structure.Structure,
                               topo_df: pd.DataFrame,
                               chain_id: str,
                               output_path: str) -> None:
    """
    Write a PDB containing only extracellular residues.
    This is the structure passed to RFdiffusion.
    """
    extracellular_resids = topo_df[topo_df["is_extracellular"]]["resid"].tolist()
    selector = TopologySelector(chain_id, extracellular_resids)

    io = PDBIO()
    io.set_structure(structure)
    io.save(output_path, selector)

    print(f"\n[INFO] Extracellular domain saved: {output_path}")
    print(f"       ({len(extracellular_resids)} residues: "
          f"{min(extracellular_resids)}–{max(extracellular_resids)})")


def update_config_with_hotspots(config: dict,
                                 hotspots: list[str],
                                 config_path: str) -> None:
    """Write hotspot residues back to the YAML config."""
    config["rfdiffusion"]["hotspot_residues"] = hotspots
    with open(config_path, "w") as f:
        yaml.dump(config, f, default_flow_style=False, sort_keys=False)
    print(f"[INFO] Config updated with hotspots: {config_path}")


def save_outputs(topo_df: pd.DataFrame,
                 hotspots: list[str],
                 sasa_map: dict[int, float],
                 output_dir: str) -> None:
    """Save topology table and hotspot list as files."""
    topo_df["sasa"] = topo_df["resid"].map(sasa_map).fillna(0.0)
    topo_path = os.path.join(output_dir, "F7GQA6_topology.tsv")
    topo_df.to_csv(topo_path, sep="\t", index=False)
    print(f"[INFO] Topology table saved: {topo_path}")

    hotspot_path = os.path.join(output_dir, "F7GQA6_hotspots.json")
    with open(hotspot_path, "w") as f:
        json.dump({"hotspot_residues": hotspots,
                   "target": "F7GQA6",
                   "epitope": "ECL2"}, f, indent=2)
    print(f"[INFO] Hotspots saved: {hotspot_path}")


# ------------------------------------------------------------------ #
#  Visualisation summary                                               #
# ------------------------------------------------------------------ #

def print_ecl2_summary(topo_df: pd.DataFrame,
                        sasa_map: dict[int, float],
                        hotspots: list[str]) -> None:
    ecl2 = topo_df[topo_df["region"] == "ECL2"].copy()
    ecl2["sasa"] = ecl2["resid"].map(sasa_map).fillna(0.0)
    hs_ids = {int(h[1:]) for h in hotspots}

    print("\n" + "=" * 55)
    print("  ECL2 residue map (F7GQA6 marmoset SWS1 opsin)")
    print("  ★ = selected hotspot   ● = exposed   · = buried")
    print("=" * 55)
    for _, row in ecl2.iterrows():
        tag = "★" if row["resid"] in hs_ids else (
              "●" if row["sasa"] >= MIN_RELATIVE_SASA else "·")
        cys_note = " ← disulfide" if row["resname"] == "CYS" else ""
        print(f"  {tag} {row['resid']:>4}  {row['resname']:3}  "
              f"pLDDT={row['plddt']:5.1f}  SASA={row['sasa']:.2f}{cys_note}")
    print("=" * 55)


# ------------------------------------------------------------------ #
#  Main                                                                #
# ------------------------------------------------------------------ #

def main():
    parser = argparse.ArgumentParser(
        description="Prepare F7GQA6 AF2 structure for nanobody design")
    parser.add_argument("--config", default="configs/design_config.yaml")
    parser.add_argument("--pdb",    default=None,
                        help="Path to AF2 PDB (overrides config)")
    args = parser.parse_args()

    config = load_config(args.config)
    pdb_path = args.pdb or config["target"]["pdb_file"]

    if not os.path.exists(pdb_path):
        sys.exit(f"[ERROR] PDB not found: {pdb_path}\n"
                 f"  Place your AF2 structure at: {pdb_path}")

    chain_id = config["target"]["chain_id"]
    topology = config["topology"]
    output_dir = str(Path(pdb_path).parent)

    # 1. Load structure
    structure = load_structure(pdb_path)

    # 2. Assign topology
    topo_df = assign_topology(structure, topology, chain_id)

    # 3. Compute SASA
    sasa_map = compute_sasa(pdb_path, structure, chain_id)

    # 4. Select hotspots
    hotspots = select_hotspots(topo_df, sasa_map, config)

    # 5. Extract extracellular PDB
    ecl_pdb_path = os.path.join(output_dir, "F7GQA6_extracellular.pdb")
    extract_extracellular_pdb(structure, topo_df, chain_id, ecl_pdb_path)

    # 6. Save outputs
    save_outputs(topo_df, hotspots, sasa_map, output_dir)

    # 7. Update config
    update_config_with_hotspots(config, hotspots, args.config)

    # 8. Print ECL2 summary
    print_ecl2_summary(topo_df, sasa_map, hotspots)

    print("\n[DONE] Next step:")
    print("  python scripts/02_run_rfdiffusion.py --config", args.config)


if __name__ == "__main__":
    main()
