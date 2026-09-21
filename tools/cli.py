from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("status")
def status() -> None:
    """Print scaffold status for the data/tooling CLI."""
    typer.echo("safety-tools 0.1.0 (scaffold)")
    typer.echo("Existing scripts: tools/cctv.py, fetch_sard.py, profile_sard.py, profile_yolo.py")


@app.command("version")
def version() -> None:
    """Print the package version."""
    typer.echo("0.1.0")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
