"""
02_run_rfdiffusion.py
=====================
Generate nanobody backbone structures targeting F7GQA6 ECL2
using RFdiffusion.

This script:
  1. Reads hotspot residues from config (set by 01_prepare_target.py)
  2. Builds the RFdiffusion command for binder design
  3. Runs RFdiffusion (if --run flag given) or prints the command
  4. Runs ProteinMPNN on each backbone to design sequences

Prerequisites:
  - RFdiffusion installed at $RFDIFFUSION_PATH
    (https://github.com/RosettaCommons/RFdiffusion)
  - ProteinMPNN installed at $PROTEINMPNN_PATH
    (https://github.com/dauparas/ProteinMPNN)

Usage (dry run — prints command):
  python scripts/02_run_rfdiffusion.py --config configs/design_config.yaml

Usage (actual run):
  python scripts/02_run_rfdiffusion.py --config configs/design_config.yaml --run
  python scripts/02_run_rfdiffusion.py --config configs/design_config.yaml --run --mpnn
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

import yaml


# ------------------------------------------------------------------ #
#  VHH (nanobody) secondary-structure blueprint for RFdiffusion       #
# ------------------------------------------------------------------ #
# Partial diffusion guide: fix framework, diffuse CDR regions
# SSSSSLLLLLSSSSSSSLLLLLLLSSSSSSSSLLLLLLLLLLLSSSSSSSSSSSSSSS
# S=sheet/strand,  L=loop (CDR),  H=helix (framework beta-strand equiv.)
#
# Simplified notation for RFdiffusion contigmap:
#   [binder_length] is sufficient for de novo design
#   For CDR-specific partial diffusion, use the blueprint below
VHH_SS_BLUEPRINT = (
    "HHHHHHHHHHHHHLLLLLLLLHHHHHHHHHHHHHHLLLLLL"
    "HHHHHHHHHHHHHHHHHLLLLLLLLLLLLLLHHHHHHHHHH"
    "HHHHHHHHHHHHHHHHHHHHHHHHHHHHHHHH"
)  # ~125 residues


def load_config(config_path: str) -> dict:
    with open(config_path) as f:
        return yaml.safe_load(f)


def check_environment() -> dict[str, str | None]:
    """Check for RFdiffusion / ProteinMPNN installations."""
    paths = {
        "rfdiffusion": os.environ.get("RFDIFFUSION_PATH"),
        "proteinmpnn": os.environ.get("PROTEINMPNN_PATH"),
    }
    for tool, path in paths.items():
        if path and os.path.isdir(path):
            print(f"[OK]   {tool}: {path}")
        else:
            print(f"[WARN] {tool} not found. "
                  f"Set ${tool.upper()}_PATH or use Colab notebook.")
    return paths


def build_rfdiffusion_command(config: dict, output_dir: str) -> list[str]:
    """
    Construct the RFdiffusion inference command for binder design.

    Key parameters:
      - contigmap: specifies the target chain + binder length
      - ppi.hotspot_res: ECL2 residues the binder must contact
      - diffuser.T: diffusion timesteps (larger = more diverse)
    """
    rf_config = config["rfdiffusion"]
    target_pdb = rf_config["target_pdb"]
    hotspots = rf_config["hotspot_residues"]
    n_designs = rf_config["num_designs"]
    binder_min, binder_max = rf_config["nanobody_length"]
    noise_scale = rf_config["noise_scale"]

    if not hotspots:
        sys.exit("[ERROR] No hotspot_residues in config. "
                 "Run 01_prepare_target.py first.")

    hotspot_str = ",".join(hotspots)  # e.g. "A178,A181,A185,A191"
    binder_length = (binder_min + binder_max) // 2  # use midpoint

    rfdiffusion_path = os.environ.get("RFDIFFUSION_PATH", "/content/RFdiffusion")
    script = os.path.join(rfdiffusion_path, "scripts", "run_inference.py")

    # contigmap: "A1-203/0 125-130"
    # → target chain A residues 1-203 (extracellular) + binder of 125-130 AA
    chain_id = config["target"]["chain_id"]
    ecl_end = config["topology"]["extracellular"]["ECL2"][1]
    contig = f"{chain_id}1-{ecl_end}/0 {binder_min}-{binder_max}"

    cmd = [
        "python", script,
        f"inference.input_pdb={target_pdb}",
        f"inference.output_prefix={output_dir}/design",
        f"inference.num_designs={n_designs}",
        f"'contigmap.contigs=[\"{contig}\"]'",
        f"'ppi.hotspot_res=[\"{hotspot_str}\"]'",
        f"diffuser.noise_scale_ca={noise_scale}",
        f"diffuser.noise_scale_frame={noise_scale}",
        "inference.num_recycles=3",
        # Antibody-like fold guidance (RFdiffusion >= 1.1.0)
        # "potentials.guiding_potentials=['type:binder_ncontacts']",
    ]
    return cmd


def build_proteinmpnn_command(config: dict,
                               designs_dir: str,
                               output_dir: str) -> list[str]:
    """
    Construct ProteinMPNN command to design sequences for each backbone.

    Fixed positions: VHH framework residues (all except CDR1/CDR2/CDR3)
    Designed positions: CDR1 (27-38), CDR2 (56-65), CDR3 (105-117) — IMGT
    """
    mpnn_path = os.environ.get("PROTEINMPNN_PATH", "/content/ProteinMPNN")
    script = os.path.join(mpnn_path, "protein_mpnn_run.py")

    seq_config = config["sequence_design"]
    n_seqs = seq_config["sequences_per_design"]
    temp = seq_config["sampling_temperature"]

    # pdb_paths.json maps {stem: path} for all design PDBs — created by
    # generate_mpnn_fixed_positions() before this command runs.
    cmd = [
        "python", script,
        "--pdb_path_multi", f"{output_dir}/pdb_paths.json",
        "--out_folder", output_dir,
        "--num_seq_per_target", str(n_seqs),
        "--sampling_temp", str(temp),
        "--batch_size", "1",
        # Design only binder chain (chain B); fix target chain (chain A)
        "--chain_id_jsonl", f"{output_dir}/fixed_chains.jsonl",
        "--fixed_positions_jsonl", f"{output_dir}/fixed_positions.jsonl",
    ]
    return cmd


def generate_mpnn_fixed_positions(designs_dir: str,
                                   output_dir: str) -> None:
    """
    Generate ProteinMPNN fixed_positions.jsonl for each design.

    CDR definition (IMGT numbering):
      CDR1: 27-38, CDR2: 56-65, CDR3: 105-117

    Framework residues are fixed; CDR residues are designed.
    Target chain (A) is fully fixed.
    """
    import json

    # IMGT CDR positions (1-indexed in the binder chain)
    cdr1 = set(range(27, 39))
    cdr2 = set(range(56, 66))
    cdr3 = set(range(105, 118))
    cdr_positions = cdr1 | cdr2 | cdr3

    # Framework positions for a 125-residue VHH (all except CDR)
    vhh_length = 125
    framework_positions = [
        i for i in range(1, vhh_length + 1)
        if i not in cdr_positions
    ]

    fixed_positions = {}
    fixed_chains = {}
    pdb_paths = {}

    design_pdbs = list(Path(designs_dir).glob("design_*.pdb"))
    for pdb in design_pdbs:
        name = pdb.stem
        # Fix target chain A entirely + fix VHH framework (chain B)
        fixed_positions[name] = {
            "A": list(range(1, 204)),   # all target residues fixed
            "B": framework_positions,   # VHH framework fixed
        }
        fixed_chains[name] = ["A"]  # target chain fully fixed
        pdb_paths[name] = str(pdb.resolve())

    os.makedirs(output_dir, exist_ok=True)

    with open(f"{output_dir}/fixed_positions.jsonl", "w") as f:
        for name, pos in fixed_positions.items():
            f.write(json.dumps({name: pos}) + "\n")

    with open(f"{output_dir}/fixed_chains.jsonl", "w") as f:
        for name, chains in fixed_chains.items():
            f.write(json.dumps({name: chains}) + "\n")

    # pdb_paths.json: {name: path} mapping required by ProteinMPNN --pdb_path_multi
    with open(f"{output_dir}/pdb_paths.json", "w") as f:
        json.dump(pdb_paths, f, indent=2)

    print(f"[INFO] ProteinMPNN fixed positions written to {output_dir}/")
    print(f"       CDR positions designed: CDR1={list(cdr1)[:3]}..., "
          f"CDR2={list(cdr2)[:3]}..., CDR3={list(cdr3)[:3]}...")
    print(f"       Framework positions fixed: {len(framework_positions)} residues")


def run_command(cmd: list[str], dry_run: bool = True) -> None:
    cmd_str = " \\\n  ".join(cmd)
    print("\n" + "=" * 60)
    print("Command:")
    print(f"  {cmd_str}")
    print("=" * 60)

    if not dry_run:
        print("\n[RUN] Executing...")
        result = subprocess.run(" ".join(cmd), shell=True, check=False)
        if result.returncode != 0:
            print(f"[ERROR] Command failed with code {result.returncode}")
        else:
            print("[OK] Command completed successfully.")
    else:
        print("\n[DRY RUN] Add --run to execute.")


def main():
    parser = argparse.ArgumentParser(
        description="Run RFdiffusion nanobody design for F7GQA6")
    parser.add_argument("--config", default="configs/design_config.yaml")
    parser.add_argument("--run", action="store_true",
                        help="Actually execute RFdiffusion (default: dry run)")
    parser.add_argument("--mpnn", action="store_true",
                        help="Also run ProteinMPNN sequence design after RFdiffusion")
    parser.add_argument("--output-dir", default="data/rfdiffusion_outputs")
    args = parser.parse_args()

    config = load_config(args.config)
    os.makedirs(args.output_dir, exist_ok=True)

    print("[INFO] Environment check:")
    paths = check_environment()

    # --- RFdiffusion ---
    print("\n[STEP 1] RFdiffusion backbone generation")
    rf_cmd = build_rfdiffusion_command(config, args.output_dir)
    run_command(rf_cmd, dry_run=not args.run)

    # --- ProteinMPNN ---
    if args.mpnn:
        print("\n[STEP 2] ProteinMPNN sequence design")
        mpnn_output_dir = os.path.join(args.output_dir, "mpnn_seqs")
        os.makedirs(mpnn_output_dir, exist_ok=True)

        if args.run:
            generate_mpnn_fixed_positions(args.output_dir, mpnn_output_dir)

        mpnn_cmd = build_proteinmpnn_command(
            config, args.output_dir, mpnn_output_dir)
        run_command(mpnn_cmd, dry_run=not args.run)
    else:
        print("\n[NOTE] Add --mpnn to also run ProteinMPNN sequence design.")

    print("\n[DONE] Next step:")
    print(f"  python scripts/03_filter_designs.py "
          f"--designs {args.output_dir} --config {args.config}")


if __name__ == "__main__":
    main()
