from .typerHelpers import *
import typer
from click import style
import validators
from remla.typerHelpers import *
from typing import Callable, Any

def sensorValidator(selection: str) -> int:
    validMessage = "Please input a number between 1 and 5."
    try:
        value = int(selection)
    except ValueError:
        raise RemlaBadParameter(validMessage)

    if value-1 in range(6):
        return value-1
    else:
        raise RemlaBadParameter(validMessage)

def domainOrHostnameValidtor(domainOrHostname:str, alertUser:bool=True) -> bool:

    if validators.domain(domainOrHostname):
        return True

    if validators.hostname(domainOrHostname):
        return True
    if alertUser:
        alert("Invalid Domain, Hostname, or IP Address")
    return False

def portValidator(port:int, alertUser:bool=True)->bool:
    validPort = validators.between(port, min_val=0, max_val=65535)
    definedPort = validators.between(port, min_val=0, max_val=1023)
    if not validPort:
        if alertUser:
            alert("Ports must be in the range 0-65535")
        return False
    elif definedPort:
        warning("Ports in the range 0-1023 are typically reserved. Make sure you know what you are doing.")
    return True

def urlValidator(url:str, alertUser:bool=True)->bool:
    if validators.url(url):
        return True
    if alertUser:
        alert("You did not provide a valid URL")
    return False

def uniqueValidator(items:list, invalidMsg:tuple[str,Callable[[str],None]]|None=None,
                    processMethod:Callable[[...,Any],list]|None=None, abort:bool=True) -> bool:
    if processMethod is not None:
        items = list(map(processMethod, items))
    itemSet = set(items)
    if len(itemSet) != len(items):
        if invalidMsg is not None:
            msgType = invalidMsg[1]
            msg = invalidMsg[0]
            msgType(msg)
        if abort:
            raise typer.Abort()
        return False
    return True

class RemlaBadParameter(typer.BadParameter):

    def __init__(self, message, *args, **kwargs):
        super().__init__(style(f"⚠️ {message} ⚠️ ", fg="yellow"), *args, **kwargs)

