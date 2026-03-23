"""
generate_notebook.py
====================
Generates notebooks/nanobody_design_colab.ipynb programmatically.
Run: python scripts/generate_notebook.py
"""

import json
from pathlib import Path

# ── helpers ────────────────────────────────────────────────────────────────

def code(src):
    return {"cell_type": "code", "metadata": {}, "outputs": [],
            "execution_count": None,
            "source": src if isinstance(src, list) else [src]}

def md(src):
    return {"cell_type": "markdown", "metadata": {},
            "source": src if isinstance(src, list) else [src]}

# ── cells ──────────────────────────────────────────────────────────────────

cells = []

# ---------- Title ----------
cells.append(md(
"# Nanobody Design Pipeline – Marmoset SWS1 Opsin (F7GQA6)\n"
"\n"
"End-to-end pipeline:\n"
"1. **Setup** – install tools\n"
"2. **Target prep** – ECL2 hotspot selection\n"
"3. **RFdiffusion** – backbone generation\n"
"4. **ProteinMPNN** – sequence design\n"
"5. **NanobodyBuilder2** – VHH structure prediction\n"
"6. **ColabFold multimer** – complex confidence scoring\n"
"7. **PRODIGY** – binding affinity estimate\n"
"8. **Filter & rank** – final candidate selection\n"
"\n"
"> **Runtime**: GPU required (A100 recommended). ~3–4 h for 200 designs.\n"
))

# ---------- 0. GPU check ----------
cells.append(md("## 0. GPU / Environment Check"))
cells.append(code(
"import subprocess, sys\n"
"r = subprocess.run(['nvidia-smi','--query-gpu=name,memory.total',\n"
"                    '--format=csv,noheader'], capture_output=True, text=True)\n"
"print(r.stdout or 'No GPU detected – switch runtime to GPU!')\n"
"print('Python', sys.version)\n"
))

# ---------- 1. Setup ----------
cells.append(md("## 1. Install Dependencies"))
cells.append(code(
"# Core bio libraries\n"
"!pip install -q biopython numpy pandas matplotlib seaborn pyyaml tqdm\n"
"\n"
"# Sequence scoring\n"
"!pip install -q ablang2\n"
"\n"
"# VHH structure prediction\n"
"!pip install -q ImmuneBuilder\n"
"\n"
"# PRODIGY (binding affinity)\n"
"!pip install -q prodigy-prot\n"
"\n"
"# ColabFold (for multimer scoring — optional, see Section 6)\n"
"# !pip install -q 'colabfold[alphafold-without-jax] @ git+https://github.com/sokrypton/ColabFold'\n"
))

cells.append(code(
"# Clone RFdiffusion\n"
"import os\n"
"if not os.path.exists('/content/RFdiffusion'):\n"
"    !git clone -q https://github.com/RosettaCommons/RFdiffusion /content/RFdiffusion\n"
"    %cd /content/RFdiffusion\n"
"    !pip install -q -e .\n"
"    %cd /content\n"
"os.environ['RFDIFFUSION_PATH'] = '/content/RFdiffusion'\n"
"print('RFdiffusion:', os.environ['RFDIFFUSION_PATH'])\n"
))

cells.append(code(
"# Clone ProteinMPNN\n"
"if not os.path.exists('/content/ProteinMPNN'):\n"
"    !git clone -q https://github.com/dauparas/ProteinMPNN /content/ProteinMPNN\n"
"os.environ['PROTEINMPNN_PATH'] = '/content/ProteinMPNN'\n"
"print('ProteinMPNN:', os.environ['PROTEINMPNN_PATH'])\n"
))

# ---------- 2. Upload PDB ----------
cells.append(md(
"## 2. Upload AF2 Structure\n"
"\n"
"Upload the AlphaFold2 model for **F7GQA6** (Marmoset SWS1 Opsin).\n"
"You can download it from [AlphaFold DB](https://alphafold.ebi.ac.uk/entry/F7GQA6).\n"
))
cells.append(code(
"from google.colab import files\n"
"import shutil, os\n"
"\n"
"os.makedirs('data', exist_ok=True)\n"
"uploaded = files.upload()          # select F7GQA6_AF2.pdb\n"
"for fname in uploaded:\n"
"    shutil.move(fname, f'data/{fname}')\n"
"    print('Saved:', f'data/{fname}')\n"
"\n"
"PDB_PATH = 'data/F7GQA6_AF2.pdb'  # adjust if filename differs\n"
))

# ---------- 3. Clone repo & target prep ----------
cells.append(md("## 3. Clone Pipeline Repo & Prepare Target"))
cells.append(code(
"if not os.path.exists('/content/Micchan001'):\n"
"    !git clone -q https://github.com/Micchan001/Micchan001 /content/Micchan001\n"
"%cd /content/Micchan001\n"
"!cp /content/data/F7GQA6_AF2.pdb data/\n"
))

cells.append(code(
"!python scripts/01_prepare_target.py \\\n"
"    --config configs/design_config.yaml \\\n"
"    --pdb data/F7GQA6_AF2.pdb\n"
))

cells.append(code(
"# Verify outputs\n"
"import json\n"
"with open('data/F7GQA6_hotspots.json') as f:\n"
"    hotspots = json.load(f)\n"
"print('Hotspot residues:', hotspots['hotspot_residues'])\n"
"\n"
"import pandas as pd\n"
"topo = pd.read_csv('data/F7GQA6_topology.tsv', sep='\\t')\n"
"print('\\nECL2 residues:')\n"
"print(topo[topo['region']=='ECL2'][['resid','resname','plddt','sasa']].to_string(index=False))\n"
))

# ---------- 4. RFdiffusion ----------
cells.append(md(
"## 4. RFdiffusion – Backbone Generation\n"
"\n"
"Generates 200 de-novo nanobody backbones targeting ECL2.\n"
"~2–3 h on A100. Reduce `NUM_DESIGNS` for a quick test.\n"
))
cells.append(code(
"NUM_DESIGNS = 200   # set to 10 for a quick test\n"
"\n"
"import yaml\n"
"with open('configs/design_config.yaml') as f:\n"
"    cfg = yaml.safe_load(f)\n"
"cfg['rfdiffusion']['num_designs'] = NUM_DESIGNS\n"
"with open('configs/design_config.yaml', 'w') as f:\n"
"    yaml.dump(cfg, f, default_flow_style=False, sort_keys=False)\n"
"print(f'Set num_designs = {NUM_DESIGNS}')\n"
))

cells.append(code(
"!python scripts/02_run_rfdiffusion.py \\\n"
"    --config configs/design_config.yaml \\\n"
"    --output-dir data/rfdiffusion_outputs \\\n"
"    --run\n"
))

cells.append(code(
"# Count outputs\n"
"from pathlib import Path\n"
"pdbs = list(Path('data/rfdiffusion_outputs').glob('design_*.pdb'))\n"
"print(f'Generated {len(pdbs)} backbone PDBs')\n"
))

# ---------- 5. ProteinMPNN ----------
cells.append(md(
"## 5. ProteinMPNN – Sequence Design\n"
"\n"
"Designs 8 sequences per backbone (CDR1/2/3 redesigned; framework fixed).\n"
))
cells.append(code(
"!python scripts/02_run_rfdiffusion.py \\\n"
"    --config configs/design_config.yaml \\\n"
"    --output-dir data/rfdiffusion_outputs \\\n"
"    --run --mpnn\n"
))

cells.append(code(
"fastas = list(Path('data/rfdiffusion_outputs/mpnn_seqs').glob('**/*.fa'))\n"
"print(f'Sequence FASTA files: {len(fastas)}')\n"
"if fastas:\n"
"    print(open(fastas[0]).read()[:500])\n"
))

# ---------- 6. NanobodyBuilder2 ----------
cells.append(md(
"## 6. NanobodyBuilder2 – VHH Structure Prediction\n"
"\n"
"Predicts 3D structure of each VHH sequence (fast, ~1 s/seq).\n"
))
cells.append(code(
"from ImmuneBuilder import NanobodyBuilder\n"
"import os\n"
"from pathlib import Path\n"
"\n"
"builder = NanobodyBuilder()\n"
"os.makedirs('data/nb_structures', exist_ok=True)\n"
"\n"
"# Parse all FASTA sequences from ProteinMPNN output\n"
"def parse_fasta(path):\n"
"    seqs = {}\n"
"    name, buf = None, []\n"
"    for line in open(path):\n"
"        line = line.strip()\n"
"        if line.startswith('>'):\n"
"            if name: seqs[name] = ''.join(buf)\n"
"            name, buf = line[1:].split()[0], []\n"
"        else:\n"
"            buf.append(line)\n"
"    if name: seqs[name] = ''.join(buf)\n"
"    return seqs\n"
"\n"
"all_seqs = {}\n"
"for fa in Path('data/rfdiffusion_outputs/mpnn_seqs').glob('**/*.fa'):\n"
"    all_seqs.update(parse_fasta(str(fa)))\n"
"\n"
"print(f'Total sequences: {len(all_seqs)}')\n"
"\n"
"failed = []\n"
"for name, seq in list(all_seqs.items())[:200]:   # cap at 200\n"
"    out = f'data/nb_structures/{name}.pdb'\n"
"    if os.path.exists(out):\n"
"        continue\n"
"    try:\n"
"        nb = builder.predict({'H': seq})\n"
"        nb.save(out)\n"
"    except Exception as e:\n"
"        failed.append((name, str(e)))\n"
"\n"
"predicted = list(Path('data/nb_structures').glob('*.pdb'))\n"
"print(f'Predicted: {len(predicted)}, Failed: {len(failed)}')\n"
))

# ---------- 7. ColabFold ----------
cells.append(md(
"## 7. ColabFold Multimer – Complex Confidence Scoring\n"
"\n"
"Scores nanobody–opsin complex using AF2-multimer.\n"
"Generates ipTM, pTM, and interface PAE for each candidate.\n"
))
cells.append(code(
"# Build FASTA for ColabFold multimer (opsin:nanobody)\n"
"from Bio import SeqIO\n"
"from Bio.PDB import PDBParser\n"
"\n"
"def pdb_to_seq(pdb_path, chain_id='A'):\n"
"    aa = {'ALA':'A','ARG':'R','ASN':'N','ASP':'D','CYS':'C','GLN':'Q',\n"
"          'GLU':'E','GLY':'G','HIS':'H','ILE':'I','LEU':'L','LYS':'K',\n"
"          'MET':'M','PHE':'F','PRO':'P','SER':'S','THR':'T','TRP':'W',\n"
"          'TYR':'Y','VAL':'V'}\n"
"    p = PDBParser(QUIET=True)\n"
"    s = p.get_structure('x', pdb_path)\n"
"    return ''.join(aa.get(r.get_resname(),'X')\n"
"                   for r in s[0][chain_id].get_residues()\n"
"                   if r.get_id()[0]==' ')\n"
"\n"
"opsin_seq = pdb_to_seq('data/F7GQA6_AF2.pdb', 'A')\n"
"\n"
"os.makedirs('data/colabfold_inputs', exist_ok=True)\n"
"nb_pdbs = sorted(Path('data/nb_structures').glob('*.pdb'))[:50]  # top 50\n"
"\n"
"fasta_out = 'data/colabfold_inputs/complexes.fasta'\n"
"with open(fasta_out, 'w') as f:\n"
"    for nb_pdb in nb_pdbs:\n"
"        nb_seq = pdb_to_seq(str(nb_pdb), 'H')\n"
"        name = nb_pdb.stem\n"
"        f.write(f'>{name}\\n{opsin_seq}:{nb_seq}\\n')\n"
"\n"
"print(f'Written {len(nb_pdbs)} complex FASTAs to {fasta_out}')\n"
))

cells.append(code(
"# Run ColabFold (requires colabfold installation; ~2 min/complex on A100)\n"
"# Uncomment to run:\n"
"# !colabfold_batch data/colabfold_inputs/complexes.fasta \\\n"
"#     data/colabfold_outputs \\\n"
"#     --model-type alphafold2_multimer_v3 \\\n"
"#     --num-recycle 3 \\\n"
"#     --num-models 1\n"
"\n"
"print('ColabFold block ready. Uncomment the command above to run.')\n"
))

# ---------- 8. PRODIGY ----------
cells.append(md(
"## 8. PRODIGY – Binding Affinity Estimation\n"
"\n"
"Estimates ΔG (kcal/mol) and Kd for each complex structure.\n"
))
cells.append(code(
"import subprocess\n"
"\n"
"def run_prodigy(pdb_path, chain_a='A', chain_b='B'):\n"
"    r = subprocess.run(\n"
"        ['prodigy', pdb_path, '--selection', chain_a, chain_b,\n"
"         '--temperature', '25'],\n"
"        capture_output=True, text=True, timeout=30\n"
"    )\n"
"    dG = Kd = None\n"
"    for line in r.stdout.splitlines():\n"
"        if 'Predicted binding affinity' in line:\n"
"            dG = float(line.split(':')[-1].split()[0])\n"
"        if 'Predicted dissociation constant' in line:\n"
"            Kd = line.split(':')[-1].strip()\n"
"    return dG, Kd\n"
"\n"
"# Test on first available complex PDB\n"
"complex_pdbs = sorted(Path('data/nb_structures').glob('*.pdb'))\n"
"if complex_pdbs:\n"
"    dG, Kd = run_prodigy(str(complex_pdbs[0]))\n"
"    print(f'Test: {complex_pdbs[0].name}  ΔG={dG} kcal/mol  Kd={Kd}')\n"
"else:\n"
"    print('No complex PDBs found yet.')\n"
))

# ---------- 9. Filter & rank ----------
cells.append(md("## 9. Filter & Rank Final Candidates"))
cells.append(code(
"!python scripts/03_filter_designs.py \\\n"
"    --designs data/nb_structures \\\n"
"    --config configs/design_config.yaml \\\n"
"    --output data/filtered_candidates \\\n"
"    --top-n 10\n"
))

cells.append(code(
"import pandas as pd\n"
"\n"
"top = pd.read_csv('data/filtered_candidates/top_candidates.tsv', sep='\\t')\n"
"display_cols = [c for c in ['name','composite_score','iptm','pae_interface',\n"
"                             'ablang_score','prodigy_dG','interface_nb']\n"
"                if c in top.columns]\n"
"print(top[display_cols].to_string(index=False))\n"
))

# ---------- 10. Visualize ----------
cells.append(md("## 10. Visualize Results"))
cells.append(code(
"import matplotlib.pyplot as plt\n"
"import pandas as pd\n"
"\n"
"all_df = pd.read_csv('data/filtered_candidates/all_scores.tsv', sep='\\t')\n"
"\n"
"fig, axes = plt.subplots(1, 3, figsize=(15, 4))\n"
"\n"
"# Composite score distribution\n"
"axes[0].hist(all_df['composite_score'].dropna(), bins=30, color='steelblue', edgecolor='white')\n"
"axes[0].set_title('Composite Score Distribution')\n"
"axes[0].set_xlabel('Composite Score')\n"
"\n"
"# ipTM vs PAE interface\n"
"if 'iptm' in all_df and 'pae_interface' in all_df:\n"
"    sc = axes[1].scatter(all_df['pae_interface'], all_df['iptm'],\n"
"                         c=all_df['composite_score'], cmap='viridis', alpha=0.7)\n"
"    axes[1].set_xlabel('PAE Interface (Å)')\n"
"    axes[1].set_ylabel('ipTM')\n"
"    axes[1].set_title('ipTM vs PAE Interface')\n"
"    plt.colorbar(sc, ax=axes[1], label='Composite Score')\n"
"else:\n"
"    axes[1].text(0.5, 0.5, 'ColabFold scores\\nnot available', ha='center', va='center')\n"
"    axes[1].set_title('ipTM vs PAE Interface')\n"
"\n"
"# PRODIGY ΔG\n"
"if 'prodigy_dG' in all_df:\n"
"    axes[2].hist(all_df['prodigy_dG'].dropna(), bins=30, color='coral', edgecolor='white')\n"
"    axes[2].axvline(-8, color='red', linestyle='--', label='threshold (-8)')\n"
"    axes[2].set_title('PRODIGY ΔG Distribution')\n"
"    axes[2].set_xlabel('ΔG (kcal/mol)')\n"
"    axes[2].legend()\n"
"else:\n"
"    axes[2].text(0.5, 0.5, 'PRODIGY scores\\nnot available', ha='center', va='center')\n"
"    axes[2].set_title('PRODIGY ΔG Distribution')\n"
"\n"
"plt.tight_layout()\n"
"plt.savefig('data/filtered_candidates/score_overview.png', dpi=150, bbox_inches='tight')\n"
"plt.show()\n"
"print('Saved: data/filtered_candidates/score_overview.png')\n"
))

# ---------- 11. Download ----------
cells.append(md("## 11. Download Results"))
cells.append(code(
"from google.colab import files\n"
"import zipfile, os\n"
"\n"
"zip_path = 'nanobody_candidates.zip'\n"
"with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:\n"
"    for f in Path('data/filtered_candidates').rglob('*'):\n"
"        if f.is_file():\n"
"            zf.write(f, f.relative_to('data'))\n"
"\n"
"print(f'Archive: {zip_path} ({os.path.getsize(zip_path)/1024:.0f} KB)')\n"
"files.download(zip_path)\n"
))

# ── assemble notebook ──────────────────────────────────────────────────────

nb = {
    "nbformat": 4,
    "nbformat_minor": 5,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "name": "python",
            "version": "3.10.0"
        },
        "accelerator": "GPU",
        "colab": {
            "provenance": [],
            "gpuType": "A100",
            "name": "nanobody_design_F7GQA6.ipynb"
        }
    },
    "cells": cells
}

out = Path('notebooks/nanobody_design_colab.ipynb')
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(nb, indent=1, ensure_ascii=False))
print(f'Notebook written: {out}  ({out.stat().st_size/1024:.0f} KB)')
