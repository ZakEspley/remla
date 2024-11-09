import typer
from rich import print as rprint
from rich.prompt import IntPrompt
from rich.panel import Panel
from functools import wraps
from pathlib import Path

def warning(message: str):
    """Prints a warning message in orange with an alert emoji."""
    rprint(f"⚠️ [orange1] {message} [/orange1] ⚠️ ")

def alert(message: str):
    """Prints a alerting message in red with an alert emoji."""
    rprint(f"🚨 [red] {message} [/red] 🚨 ")

def success(message: str):
    """Prints a sucess message in green with a thumbs up emoji"""
    rprint(f"✅ [green] {message} [/green] ✅ ")

def echoResult(result, goodMessage, badMessage=None):
    if result:
        success(goodMessage)
    else:
        if badMessage is not None:
            alert(badMessage)
        raise typer.Abort()

def panelDisplay(message:str, **kwargs):
    panel  = Panel(message, expand=False, **kwargs)
    rprint(panel)

def remlaPanel(message:str):
    panelDisplay(message, title="Remla", border_style="#febc11")
