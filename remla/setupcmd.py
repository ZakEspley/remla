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
    numNetworkSettings = 3
    numWebsiteSettings = 3 # Change these if more settings are required.
    remlaSettings = getSettings()
    rprint(f"Searching {remoteLabsDirectory} for files.")
    labSelection = promptForNumericFile("Which lab file do you want to use:",
                                        remoteLabsDirectory,
                                 "*.yml",
                                 f"You don't have any labs setup. Please run `remla new` or put lab yml in the {remoteLabsDirectory} directory.")

    rprint(f"Setting up {labSelection.name}")
    labSettings = yaml.load(labSelection)
    remlaSettings["currentLab"] = labSelection.relative_to(remoteLabsDirectory)
    #TODO: Add Validation Function to check it labSettings make sense.
    networkSettings = labSettings.get("network", {})
    websiteSettings = labSettings.get("website", {})
    networkUpdate = False
    if None in networkSettings.values() or len(networkSettings) < 3:
        rprint("It looks like your network isn't fully configured. Let me help.")
        networkUpdate = True
    else:
        networkUpdate = Confirm.ask("Do you want to change your network settings?")

    if networkUpdate:
        validPort = False
        while not validPort:
            port = IntPrompt.ask("Which http port do you want your website to be accessible on?", default=8080)
            validPort = portValidator(port)
        validwsPort = False
        while not validwsPort:
            wsPort = IntPrompt.ask("Which websocket port do you want to communicate on?", default=8675)
            validwsPort = portValidator(wsPort)
            if validwsPort and port == wsPort:
                validwsPort = False
                warning("You can't use the same port as the HTTP port.")
        validDomain = False
        while not validDomain:
            domain = Prompt.ask("What domain name do you want to use? e.g. example.com, 127.0.0.1, hostname")
            validDomain = domainOrHostnameValidtor(domain)

        networkSettings["port"] = port
        networkSettings["domain"] = domain
        networkSettings["wsPort"] = wsPort


    websiteUpdate = False
    if websiteSettings.get("index") is None:
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
        rprint(f"You have selected {indexSelection.relative_to(remoteLabsDirectory)}")
        websiteSettings["index"] = indexSelection.relative_to(remoteLabsDirectory)


    commonStaticFolderDesire = Confirm.ask("Do you have a common static folder for all your websites?", default=False)
    commonStaticUpdate = False
    if commonStaticFolderDesire:
        staticExist =  (remoteLabsDirectory/"static").exists()
        if not staticExist:
            alert(f"You don't currently have a static folder in {remoteLabsDirectory} to copy. Will not update.")
            websiteSettings["commonStaticFolder"] =  False
        else:
            websiteSettings["commonStaticFolder"] = True
            #TODO: There may be some text substitution that we need to do here, depending on lab choice.
    else:
        websiteSettings["commonStaticFolder"] = False

    staticUpdate = Confirm.ask("Do you have a specific static folder for your labs website?", default=True)
    if staticUpdate:
        question = "Which static folder is the one for the lab you want to setup?"
        staticSelection = promptForNumericFile(question,
                                              remoteLabsDirectory,
                                              "static",
                                              f"There are no static Directories in your {remoteLabsDirectory} directory."
                                              )
        rprint(f"You have selected {staticSelection.relative_to(remoteLabsDirectory)}")
        websiteSettings["staticFolder"] = staticSelection.relative_to(remoteLabsDirectory)
    elif  websiteSettings["staticFolder"] is not None and not websiteSettings["staticFolder"].exists():
        alert(f"Your provided static folder {websiteSettings['staticFolder']} doesn't exist")
        raise typer.Abort()

    labSettings["network"] = networkSettings
    labSettings["website"] = websiteSettings
    _setup(labSettings)
    yaml.dump(remlaSettings, settingsDirectory/"settings.yml")
    yaml.dump(labSettings, remoteLabsDirectory/remlaSettings["currentLab"])

def _setup(labSettings:dict)->None:
    createServiceFile(False)
    networkSettings = labSettings["network"]
    websiteSettings = labSettings["website"]
    updateRemlaNginxConf(networkSettings["port"], networkSettings["domain"], networkSettings["wsPort"])
    clearDirectory(websiteDirectory)
    shutil.copy(remoteLabsDirectory / websiteSettings["index"], websiteDirectory / "index.html")
    if websiteSettings["commonStaticFolder"]:
        shutil.copytree(remoteLabsDirectory / "static", websiteDirectory / "static", dirs_exist_ok=True)
    if websiteSettings["staticFolder"] is not None:
        shutil.copytree(remoteLabsDirectory/websiteSettings["staticFolder"], websiteDirectory / "static", dirs_exist_ok=True)
    requiredFiles = ["reader.js", "mediaMTXGetFeed.js", "remlaSocket.js"]
    for file in requiredFiles:
        shutil.copy(setupDirectory / file, websiteJSDirectory)

    shutil.copytree(websiteDirectory, nginxWebsitePath, dirs_exist_ok=True)

@app.command()
def lab(labfile: Annotated[str, typer.Argument()],
        port: Annotated[int, typer.Option()]=None,
        wsport: Annotated[int,typer.Option()]=None,
        domain: Annotated[str, typer.Option()]=None,
        cstaticon: Annotated[bool, typer.Option()]=False,
        cstaticoff: Annotated[bool,typer.Option()]=False,
        staticfolder: Annotated[str, typer.Option()]=None,
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
        labFilePath = remoteLabsDirectory / potentialLabs[0]

    remlaSettings = getSettings()
    remlaSettings["currentLab"] = labFilePath.relative_to(remoteLabsDirectory)
    labSettings = yaml.load(labFilePath)

    # If the user doesn't provide changes to the settings when setting up the lab
    # then load them in from the settings file.
    if port is None:
        port = labSettings["network"]["port"]
    if wsport is None:
        wsPort = labSettings["network"]["wsPort"]
    else:
        wsPort = wsport
    if domain is None:
        domain = labSettings["network"]["domain"]
    if not cstaticon and not cstaticoff:
        commonStaticFolder = labSettings["website"]["commonStaticFolder"]
    elif cstaticon:
        commonStaticFolder = True
    else:
        commonStaticFolder = False
    if staticfolder is None:
        staticFolder = labSettings["website"]["staticFolder"]
    else:
        staticFolder = staticfolder

    if not portValidator(port):
        raise typer.Abort()
    if not portValidator(wsPort):
        raise typer.Abort()
    elif wsPort == port:
        alert("The http port and the websocket port can't be the same!")
        raise typer.Abort()
    if not domainOrHostnameValidtor(domain):
        raise typer.Abort()

    if labSettings["website"]["index"] is None:
        alert("You haven't send an index.html file in your settings file. Please update before continuing or run `remla setup int` for guidance through a set up.")
        raise typer.Abort()
    elif not (remoteLabsDirectory/labSettings["website"]["index"]).exists():
        alert(f"Your index file in your settings doesn't exist at {labSettings['website']['index']}. Please update before continuing or run `remla setup int` for guidance through a set up.")
        raise typer.Abort()

    labSettings["network"]["port"] = port
    labSettings["network"]["wsPort"] = wsPort
    labSettings["network"]["domain"] = domain
    labSettings["website"]["commonStaticFolder"] = commonStaticFolder
    labSettings["website"]["staticFolder"] = staticFolder

    _setup(labSettings)
    yaml.dump(labSettings, labFilePath)
    yaml.dump(remlaSettings, settingsDirectory/"settings.yml")





if __name__=="__main__":
    app()
