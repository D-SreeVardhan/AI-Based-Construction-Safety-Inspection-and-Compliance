from __future__ import annotations

import typer

from llm.narration.cli import corpus_app, eval_app, student_app, teacher_app

app = typer.Typer(add_completion=False, no_args_is_help=True)
app.add_typer(corpus_app, name="corpus")
app.add_typer(teacher_app, name="teacher")
app.add_typer(student_app, name="student")
app.add_typer(eval_app, name="eval")


@app.command("status")
def status() -> None:
    """Print the state of the narration experiment."""
    typer.echo("safety-llm 0.2.0")
    typer.echo("Fine-tuning is a graded experiment, not the authority for rules or citations.")


@app.command("version")
def version() -> None:
    """Print the package version."""
    typer.echo("0.2.0")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
