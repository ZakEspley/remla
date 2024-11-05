from remla.labcontrol.Controllers import gpio
import typer
from remla.systemHelpers import *
from rich.prompt import Prompt
from remla.settings import *
from remla.typerHelpers import *
from remla.systemHelpers import *
from typing_extensions import Annotated
from typing import Union
import re

app = typer.Typer(no_args_is_help=False)

addOverlayCmd = "sudo dtoverlay i2c-gpio bus=<bus> i2c_gpio_sda=<sda> i2c_gpio_scl=<scl>"
removeOverlayCmd = "sudo dtoverlay -r <index>"
armI2CCmd = "sudo dtparam i2c_arm=<state>"

@app.command()
def new(
        bus: Annotated[Union[str, None], typer.Option("--bus", "-b", help="The bus number you want." )]=None,
        sda: Annotated[Union[str,None], typer.Option("--sda", "-d", help="SDA Data Line GPIO number in BCM.")]=None,
        scl: Annotated[Union[str,None], typer.Option("--scl", "-c", help="SCL Clock Line GPIO Number in BCM")]=None,
        arm: Annotated[Union[bool,None], typer.Option("--arm", "-a", help="Turns on the builtin I2C on GPIO 2 & 3")]=False
        ):

    """
    MUST BE RUN AS ROOT. (use sudo)
    
    This command sets up a new i2c bus by writing right to the /boot/firmware/config.txt file.
    It will then try to load an overlay so that you can use it before reboot.
    
    It works in two methods you can just run `sudo remla i2c new` to get an interactive prompt for how to add a new i2c bus to the 
    system (this is the preferred method). Additionally you can use the the -b, -d, -s flags to provide 
    your own bus, sda, and scl respectively. Just put the flag followed by a number, i.e. -b 11 for bus 11

    You must provide a bus if you do it this way. You must also provide both an sda and scl pin or provide neither. If neither is provided 
    then the defaults of GPIO 23 and 24 are selected.

    Finally, you can use the -a flag to turn on the default i2c-1 bus if it is not on.
    
    Note: All pin numbers should use the BCM convention.
    """
        ####### Verify that we are running as sudo ######
    if os.geteuid() != 0:
        alert("This script must be run as root.")
        typer.echo("Try running with sudo")
        raise typer.Abort()
        # Check if running interactive mode
    if bus is None and sda is None and scl is None and not arm:
        _i2cInteractive()
    elif arm:
        config = bootConfigPath.read_text()
        arm_line = "dtparam=i2c_arm=<state>"
        i2c_arm, i2c_arm_line_no, i2c_overalys = getI2COverlays()
        if i2c_arm:
            warning("I2C arm is already in config.txt. If you don't see it when you think you should try a reboot")
            return
        if i2c_arm_line_no < 0:
            bootConfigPath.write_text(config + "\n" + arm_line.replace("<state>", "on"))
        else:
            bootConfigPath.write_text( config.replace(arm_line.replace("<state>", "off"), arm_line.replace("<state>", "on")) )
        success("Added i2c_arm to config.txt. It will now be automatically loaded on reboot")
        cmd = armI2CCmd.replace("<state>", "on")
        try:
            subprocess.run(cmd.split(), check=True)
            success("Also loaded in i2c_arm right now, so you can use it before reboot.\nTo test it out, run `i2cdetect -y 1`")
        except subprocess.CalledProcessError as e:
            warning(f"We tried to load I2C right now but something went wrong. You likely need to reboot to have access to I2C. The error message was\n\n{e}")
            
    else:
        #Check if bus is given
        try:
            int(bus)
            if bus is None or int(bus) <= 2:
                    raise ValueError
        except ValueError:
            alert("Bus must be an integer greater than or equal to 2, and probably less than 16")
            raise typer.Abort()
        except TypeError:
            alert("You must provide a bus argument with `-b` flag followed by an integer from 2-16")
            raise typer.Abort()

        # Check if SDA and SCL are both none, or provided.
        if not bothOrNoneAssigned(sda, scl):
                alert("You need to do one of the following:\n\
        1. Assign both SDA and SCL to numbers on your representing GPIO pins in BCM format\n\
        2. Not assign either SDA or SCL in which case BCM pins 23, and 24 will be used.")
                raise typer.Abort()

        sda = sda or "23"
        scl = scl or "24"
        
        if sda==scl:
                alert("SDA and SCL must be different GPIO pins")
                raise typer.Abort()
                
        i2c_arm, i2c_arm_line_no, i2c_overlays = getI2COverlays()
        forbidden_gpios = {0,1,2,3}
        preferred_gpios = {17,27,22,23,24,25,5,6,16,26}

        if {int(sda), int(scl)} & forbidden_gpios:
            alert(f"You can't use any of the GPIOs in the the following {forbidden_gpios}")
            raise typer.Abort()

        if not ({int(sda), int(scl)} & preferred_gpios):
            warning(f"If you can, try to use one of the following GPIO's as they have no other uses:\n{preferred_gpios}")
        
        conflicts = []
        for overlay in i2c_overlays:
            in_use = f""
            if overlay["bus"] == bus:
                in_use += f"BUS: {bus}\t"
                #alert(f"Bus {bus} is already in use. Consider using a different bus number or using `remla i2c update` to update that bus")
            if overlay["sda"] == sda:
                in_use += f"GPIO_SDA: {sda}\t"
            if overlay["scl"] == scl:
                in_use += f"GPIO_SCL: {scl}"
            if in_use != "":
                line = _createI2CLine(overlay['bus'], overlay['sda'], overlay['scl'])
                conflicts.append(line)

        if len(conflicts) != 0:
            message = "\nYou should run `remla i2c delete` to remove conflicting i2c conditions"
            message += "\n".join(conflicts)
            alert(message)
            raise typer.Abort()
        line = _createI2CLine(bus, sda, scl)
        with open(bootConfigPath, "a") as config:
            config.write("\n"+line)
        success(f"Updated {bootConfigPath} with new overlay:\n\t{line}\n Overlay will automatically be activated on next reboot. Loading in overlay right now as well...")
        

        cmd = addOverlayCmd.replace("<bus>", bus).replace("<sda>", sda).replace("<scl>", scl).strip()
        try:
            subprocess.run(cmd.split(), check=True)
            success(f"Added new i2c bus. You can check by running the command `i2cdetect -y {bus}`")
        except subprocess.CalledProcessError as e:
            alert(f"There was an error loading the overlay. Error read:\n {e}")

@app.command(help="The will list out busses that are avaialble and then remove you selected one from the /boot/firmware/config.txt.\
                    A restart is required for you changes to take effect.\n\
                    This can also be used to turn off the default i2c-1 bus if needed.")
def delete():
    i2c_arm, i2c_arm_line_no, i2c_overlays = getI2COverlays()
    choice_string = ""
    choices = len(i2c_overlays)
    if not i2c_arm and choices == 0:
        warning("No I2C enteries to delete. Exiting...")
        return
    for index, overlay in enumerate(i2c_overlays):
        choice_string += f"  {index+1}. {_createI2CLine(overlay['bus'], overlay['sda'], overlay['scl'])}\n"
    if i2c_arm:
        choice_string += f"  {len(i2c_overlays) + 1}. dtparam=i2c_arm=on"
        choices += 1
    deletionChoice = IntPrompt.ask(f"Which overlay do you want to delete?\n{choice_string}\n", choices=[str(i) for i in range(1, choices+1)])
    if deletionChoice != choices or not i2c_arm:
        config = bootConfigPath.read_text().splitlines()
        del config[i2c_overlays[deletionChoice-1]["line_no"]]
        bootConfigPath.write_text("\n".join(config) + "\n")
    else:
        config = bootConfigPath.read_text()
        config = config.replace("dtparam=i2c_arm=on", "dtparam=i2c_arm=off")
        bootConfigPath.write_text(config)
    success("Successfully updated config.txt.")

def getI2COverlays():
    i2c_overlays = []
    i2c_arm = False
    i2c_arm_line_no = -1
    with open(bootConfigPath, "r") as config:
        for index, line in enumerate(config):
            if line.startswith("dtoverlay=i2c-gpio"):
                i2c_overlays.append(_extractI2CInfo(line.strip()))
                i2c_overlays[-1]["line_no"] = index
            elif line.startswith("dtparam=i2c_arm="):
                if line.strip().split("=")[-1] == "on":
                    i2c_arm=True
                i2c_arm_line_no = index

    return (i2c_arm, i2c_arm_line_no, i2c_overlays)

# Function to find matches and extract information with improved flexibility
def _extractI2CInfo(line):
            # Use `findall` to capture all matching parts, regardless of order
    matches = re.findall(r"(bus=(\d+)|i2c_gpio_sda=(\d+)|i2c_gpio_scl=(\d+))", line)
    result = {"bus": None, "sda": None, "scl": None}
        
    for match in matches:
        if match[1]:  # `bus`
            result["bus"] = match[1]
        elif match[2]:  # `sda`
            result["sda"] = match[2]
        elif match[3]:  # `scl`
            result["scl"] = match[3]
        
    return result

def _createI2CLine(bus, sda, scl):
    line = f"dtoverlay=i2c-gpio"
    if bus:
        line += f",bus={bus}"
    if sda:
        line += f",i2c_gpio_sda={sda}"
    if scl:
        line += f",i2c_gpio_scl={scl}"
    return line

def _i2cInteractive():
    i2c_arm, i2c_arm_line_no, i2c_overlays = getI2COverlays()
    preferred_gpios = {"17","27","22","23","24","25","5","6","16","26"}
    other_gpios = {"4", "14", "15", "18", "9", "10", "11", "7", "8", "13", "19", "20", "21"}
    allowed_buses = {"2", "3", "4", "5", "6", "7", "8", "9", "10", "11", "12", "13", "14", "15"}
    
    for overlay in i2c_overlays:
        preferred_gpios.discard(overlay["sda"])
        other_gpios.discard(overlay["sda"])
        preferred_gpios.discard(overlay["scl"])
        other_gpios.discard(overlay["scl"])
        allowed_buses.discard(overlay["bus"])
    
    allowed_gpios = list(preferred_gpios | other_gpios)
    allowed_gpios.sort(key=lambda x: int(x))
    allowed_buses = list(allowed_buses)
    allowed_buses.sort(key = lambda x: int(x))
    available_preferred_gpios = list(preferred_gpios)
    available_preferred_gpios.sort(key=lambda x: int(x))
    bus_num = Prompt.ask("What bus number do you want to use?\n", choices=allowed_buses)
    gpio_prompt = f"""Which GPIO pin do you want to use for your <type>?\n
Note: You are not required to choose from this list, but the preferred list
below are GPIO's that aren't used by any builtin software\n
Preferred List: {available_preferred_gpios}\n
"""
    print(allowed_gpios)
    sda_num = Prompt.ask(gpio_prompt.replace("<type>", "SDA"), choices=allowed_gpios)
    allowed_gpios.remove(sda_num)
    scl_num = Prompt.ask(gpio_prompt.replace("<type>", "SCL"), choices=allowed_gpios)
    
    with open(bootConfigPath, "a") as config:
        config.write("\n" + _createI2CLine(bus_num, sda_num, scl_num))

    success("Added i2c_arm to config.txt. It will now be automatically loaded on reboot")
    cmd = addOverlayCmd.replace("<bus>", bus_num).replace("<sda>", sda_num).replace("<scl>", scl_num).strip()
    try:
        subprocess.run(cmd.split(), check=True)
        success(f"Also loaded in i2c_arm right now, so you can use it before reboot.\nTo test it out, run `i2cdetect -y {bus_num}`")
    except subprocess.CalledProcessError as e:
        warning(f"We tried to load I2C right now but something went wrong. You likely need to reboot to have access to I2C. The error message was\n\n{e}")

if __name__ == "__main__":
    results = getI2COverlays()
    print(results)

