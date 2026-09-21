from __future__ import annotations

import typer

app = typer.Typer(add_completion=False, no_args_is_help=True)


@app.command("status")
def status() -> None:
    """Print scaffold status for the evaluation CLI."""
    typer.echo("safety-eval 0.1.0 (scaffold)")
    typer.echo("Detection, tracking, scene, rules, and product evaluators are not implemented yet.")


@app.command("version")
def version() -> None:
    """Print the package version."""
    typer.echo("0.1.0")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
