"""Command-line interface: `vrf ingest | index | assess | report | demo`."""

from __future__ import annotations

import os

import typer

from . import synth
from .index import IndexStore
from .ingest import load_dir, load_csv
from .report import summarize, write_json
from .rules import assess, coverage, findings_to_frame

app = typer.Typer(add_completion=False, help="Mitsubishi VRF log analyzer.")

DEFAULT_INDEX = ".vrf_index"


@app.command()
def index(
    path: str = typer.Argument(..., help="CSV file or directory of CSVs."),
    profile: str = typer.Option(None, help="Format profile (auto-detect if omitted)."),
    out: str = typer.Option(DEFAULT_INDEX, help="Index output directory."),
):
    """Ingest CSV(s) and build the Parquet/DuckDB index."""
    df = load_dir(path, profile=profile) if os.path.isdir(path) else load_csv(path, profile=profile)
    store = IndexStore(out).build(df)
    units = store.units()
    typer.echo(f"Indexed {len(df):,} rows across {len(units)} units into {out!r}.")
    for u in units:
        typer.echo(f"  {u.system_id}/{u.unit_id} [{u.unit_role}] {u.n_rows} rows "
                   f"{u.start:%Y-%m-%d %H:%M} -> {u.end:%Y-%m-%d %H:%M}")


@app.command(name="assess")
def assess_cmd(
    index_dir: str = typer.Option(DEFAULT_INDEX, "--index", help="Index directory."),
    report: str = typer.Option(None, help="Write findings JSON to this path."),
):
    """Run the top-25 detectors over the index and print a summary."""
    store = IndexStore(index_dir)
    if not store.exists():
        typer.echo(f"No index at {index_dir!r}. Run `vrf index` first.", err=True)
        raise typer.Exit(1)
    findings = assess(store.read())
    s = summarize(findings)
    typer.echo(f"{s['total_findings']} findings. By severity: {s['by_severity']}")
    frame = findings_to_frame(findings)
    if not frame.empty:
        cols = ["severity_label", "rule_id", "unit_id", "message"]
        typer.echo(frame[cols].to_string(index=False, max_colwidth=70))
    if report:
        write_json(findings, report)
        typer.echo(f"Wrote {report}")


@app.command()
def catalog():
    """List the top-25 issue catalog and which detectors are live."""
    for spec in coverage():
        flag = "LIVE " if spec.implemented else "plan "
        typer.echo(f"[{flag}] {spec.rule_id:22s} {spec.default_severity.label:8s} {spec.title}")


@app.command()
def demo(out: str = typer.Option(DEFAULT_INDEX, help="Index directory.")):
    """Generate synthetic faulted data, index it, and assess it in one shot."""
    os.makedirs("data/sample", exist_ok=True)
    csv_path = "data/sample/synthetic_vrf.csv"
    synth.write_csv(csv_path)
    typer.echo(f"Wrote synthetic data -> {csv_path}")
    df = load_csv(csv_path, profile="canonical")
    IndexStore(out).build(df)
    findings = assess(df)
    s = summarize(findings)
    typer.echo(f"Indexed {len(df):,} rows. {s['total_findings']} findings: {s['by_severity']}")
    frame = findings_to_frame(findings)
    if not frame.empty:
        typer.echo(frame[["severity_label", "rule_id", "unit_id", "message"]]
                   .to_string(index=False, max_colwidth=70))


if __name__ == "__main__":
    app()
