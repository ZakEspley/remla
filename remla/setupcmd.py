import shutil

import typer
from .systemHelpers import getSettings, clearDirectory, promptForNumericFile, updateRemlaNginxConf
from rich import print as rprint
from rich.prompt import Prompt, Confirm
from remla.settings import *
from remla.typerHelpers import *
import validators
from remla.customvalidators import domainOrHostnameValidtor, portValidator
from remla.systemHelpers import *
from typing_extensions import Annotated
from remla.yaml import yaml
from typing import Optional


app = typer.Typer(no_args_is_help=False)

@app.command(name="int")
def interactive():
    """
    Runs an interactive setup that searches files and prompts users which one they want to use.
    """
    remlaSettings = getSettings()
    rprint(f"Searching {remoteLabsDirectory} for files.")
    labSelection = promptForNumericFile("Which lab file do you want to use:",
                                        remoteLabsDirectory,
                                 "*.yml",
                                 f"You don't have any labs setup. Please run `remla new` or put lab yml in the {remoteLabsDirectory} directory.")

    rprint(f"Setting up {labSelection.name}")
    labSettings = yaml.load(labSelection)
    remlaSettings["currentLab"] = labSelection.relative_to()
    #TODO: Add Validation Function to check it labSettings make sense.
    networkSettings = labSettings["network"]
    websiteSettings = labSettings["website"]
    networkUpdate = False
    if None in networkSettings.values():
        rprint("It looks like your network isn't fully configured. Let me help.")
        networkUpdate = True
    else:
        networkUpdate = Confirm.ask("Do you want to change your network settings?")

    if networkUpdate:
        port = IntPrompt.ask("Which port do you want your website to be accessible on?", default="8080")
        validDomain = False
        while not validDomain:
            domain = Prompt.ask("What domain name do you want to use? e.g. example.com, 127.0.0.1, hostname")
            validDomain = domainOrHostnameValidtor(domain)

        networkSettings["port"] = port
        networkSettings["domain"] = domain


    websiteUpdate = False
    if websiteSettings["index"] is None:
        rprint("It looks like your website isn't fully configured. Let me help.")
        websiteUpdate = True
    else:
        websiteUpdate = Confirm.ask("Do you want to change your website settings?")
    if websiteUpdate:
        question = "Which file is should act as your index.html page? (The labs main webpage)"
        indexSelection = promptForNumericFile(question,
                                              remoteLabsDirectory,
                                              "*.html",
                                              f"There are no HTML files in your {remoteLabsDirectory} directory."
                                              )
        rprint(f"You have selected {indexSelection.name}")
        websiteSettings["index"] = indexSelection



    staticFolderDesire = Confirm.ask("Do you have a static folder for your website?")
    staticUpdate = False
    if staticFolderDesire:
        staticExist =  (remoteLabsDirectory/"static").exists()
        if not staticExist:
            alert(f"You don't currently have a static folder in {remoteLabsDirectory} to copy. Will not update.")
            websiteSettings["staticFolder"] =  False
        else:
            websiteSettings["staticFolder"] = True
            #TODO: There may be some text substitution that we need to do here, depending on lab choice.
    else:
        websiteSettings["staticFolder"] = False

    _setup(labSettings)
    yaml.dump(remlaSettings, settingsDirectory/"settings.yml")
    yaml.dump(labSettings, remlaSettings["currentLab"])

def _setup(labSettings:dict)->None:
    networkSettings = labSettings["network"]
    websiteSettings = labSettings["website"]
    updateRemlaNginxConf(networkSettings["port"], networkSettings["domain"])
    clearDirectory(websiteDirectory)
    shutil.copy(websiteSettings["index"], websiteDirectory / "index.html")
    if websiteSettings["staticFolder"]:
        shutil.copytree(remoteLabsDirectory / "static", websiteDirectory / "static", dirs_exist_ok=True)


@app.command()
def lab(labfile: Annotated[str, typer.Argument()],
        port: Annotated[int, typer.Option()]=None,
        domain: Annotated[str, typer.Option()]=None,
        staticon: Annotated[bool, typer.Option()]=False,
        staticoff: Annotated[bool,typer.Option()]=False
        ):
    labFileSuffix = Path(labfile).suffix

    if not labFileSuffix == ".yml":
        alert("The lab file you provided is not a yml file.")
        raise typer.Abort()
    labfile = labfile.strip("/")


    alertMsg = f"No files with name {labfile} exist in {remoteLabsDirectory}"
    potentialLabs = searchForFilePattern(remoteLabsDirectory, labfile, (alertMsg, alert))
    warnMsg = f"You have duplicate files with name {labfile} within {remoteLabsDirectory}."
    if not uniqueValidator(potentialLabs, (warnMsg,warning), processMethod=lambda x: x.name, abort=False):
        labFilePath = promptForNumericFile("Select which version you want.", remoteLabsDirectory, labfile)
    else:
        labFilePath = remoteLabsDirectory / labfile

    remlaSettings = getSettings()
    remlaSettings["currentLab"] = labFilePath.relative_to(remoteLabsDirectory)
    labSettings = yaml.load(labFilePath)


    if port is None:
        port = labSettings["network"]["port"]
    if domain is None:
        domain = labSettings["network"]["domain"]
    if not staticon and not staticoff:
        staticFolder = labSettings["website"]["staticFolder"]
    elif staticon:
        staticFolder = True
    else:
        staticFolder = False

    if not portValidator(port):
        raise typer.Abort()
    if not domainOrHostnameValidtor(domain):
        raise typer.Abort()
    labSettings["network"]["port"] = port
    labSettings["network"]["domain"] = domain
    labSettings["website"]["index"] = labFilePath
    labSettings["website"]["staticFolder"] = staticFolder

    _setup(labSettings)
    yaml.dump(labSettings, labFilePath)
    yaml.dump(remlaSettings, settingsDirectory/"settings.yml")





if __name__=="__main__":
    app()