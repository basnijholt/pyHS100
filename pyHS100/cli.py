"""pyHS100 cli tool."""
import asyncio
import logging
import sys
from pprint import pformat as pf

import click

if sys.version_info < (3, 6):
    print("To use this script you need Python 3.6 or newer! got %s" % sys.version_info)
    sys.exit(1)

from pyHS100 import SmartPlug  # noqa: E402
from pyHS100 import Discover, SmartBulb, SmartDevice, SmartStrip


pass_dev = click.make_pass_decorator(SmartDevice)


@click.group(invoke_without_command=True)
@click.option(
    "--ip",
    envvar="PYHS100_IP",
    required=False,
    help="The IP address of the device to connect to. This option "
    "is deprecated and will be removed in the future; use --host "
    "instead.",
)
@click.option(
    "--host",
    envvar="PYHS100_HOST",
    required=False,
    help="The host name or IP address of the device to connect to.",
)
@click.option(
    "--alias",
    envvar="PYHS100_NAME",
    required=False,
    help="The device name, or alias, of the device to connect to.",
)
@click.option(
    "--target",
    default="255.255.255.255",
    required=False,
    help="The broadcast address to be used for discovery.",
)
@click.option("--debug/--normal", default=False)
@click.option("--bulb", default=False, is_flag=True)
@click.option("--plug", default=False, is_flag=True)
@click.option("--strip", default=False, is_flag=True)
@click.version_option()
@click.pass_context
def cli(ctx, ip, host, alias, target, debug, bulb, plug, strip):
    """A cli tool for controlling TP-Link smart home plugs."""  # noqa
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.INFO)

    if ctx.invoked_subcommand == "discover":
        return

    if ip is not None and host is None:
        host = ip

    if alias is not None and host is None:
        click.echo("Alias is given, using discovery to find host %s" % alias)
        host = find_host_from_alias(alias=alias, target=target)
        if host:
            click.echo("Found hostname is {}".format(host))
        else:
            click.echo("No device with name {} found".format(alias))
            return

    if host is None:
        click.echo("No host name given, trying discovery..")
        ctx.invoke(discover)
        return
    else:
        if not bulb and not plug and not strip:
            click.echo("No --strip nor --bulb nor --plug given, discovering..")
            dev = asyncio.run(Discover.discover_single(host))
        elif bulb:
            dev = SmartBulb(host)
        elif plug:
            dev = SmartPlug(host)
        elif strip:
            dev = SmartStrip(host)
        else:
            click.echo("Unable to detect type, use --strip or --bulb or --plug!")
            return
        ctx.obj = dev

    if ctx.invoked_subcommand is None:
        ctx.invoke(state)


@cli.command()
@click.option("--save")
@click.pass_context
def dump_discover(ctx, save):
    """Dump discovery information.

    Useful for dumping into a file with `--save` to be added to the test suite.
    """
    target = ctx.parent.params["target"]
    for dev in Discover.discover(target=target, return_raw=True).values():
        model = dev["system"]["get_sysinfo"]["model"]
        hw_version = dev["system"]["get_sysinfo"]["hw_ver"]
        save_to = "%s_%s.json" % (model, hw_version)
        click.echo("Saving info to %s" % save_to)
        with open(save_to, "w") as f:
            import json

            json.dump(dev, f, sort_keys=True, indent=4)


@cli.command()
@click.option("--timeout", default=3, required=False)
@click.option("--discover-only", default=False)
@click.option("--dump-raw", is_flag=True)
@click.pass_context
def discover(ctx, timeout, discover_only, dump_raw):
    """Discover devices in the network."""
    target = ctx.parent.params["target"]
    click.echo("Discovering devices for %s seconds" % timeout)
    found_devs = Discover.discover(
        target=target, timeout=timeout, return_raw=dump_raw
    ).items()
    if not discover_only:
        for ip, dev in found_devs:
            if dump_raw:
                click.echo(dev)
                continue
            ctx.obj = dev
            ctx.invoke(state)
            print()

    return found_devs


def find_host_from_alias(alias, target="255.255.255.255", timeout=1, attempts=3):
    """Discover a device identified by its alias."""
    host = None
    click.echo(
        "Trying to discover %s using %s attempts of %s seconds"
        % (alias, attempts, timeout)
    )
    for attempt in range(1, attempts):
        click.echo("Attempt %s of %s" % (attempt, attempts))
        found_devs = Discover.discover(target=target, timeout=timeout).items()
        for ip, dev in found_devs:
            if dev.sync.get_alias().lower() == alias.lower():
                host = dev.host
                return host
    return None


@cli.command()
@pass_dev
def sysinfo(dev):
    """Print out full system information."""
    click.echo(click.style("== System info ==", bold=True))
    click.echo(pf(dev.sync.get_sys_info()))


@cli.command()
@pass_dev
@click.pass_context
def state(ctx, dev: SmartDevice):
    """Print out device state and versions."""
    click.echo(
        click.style(
            "== %s - %s ==" % (dev.sync.get_alias(), dev.sync.get_model()), bold=True
        )
    )

    click.echo(
        click.style(
            "Device state: %s" % ("ON" if dev.sync.is_on() else "OFF"),
            fg="green" if dev.sync.is_on() else "red",
        )
    )
    if dev.num_children > 0:
        is_on = dev.sync.get_is_on()
        aliases = dev.sync.get_alias()
        for plug in range(dev.plugs):
            click.echo(
                click.style(
                    "  * %s state: %s" % (plug.alias, ("ON" if plug.is_on else "OFF")),
                    fg="green" if plug.is_on else "red",
                )
            )

    click.echo("Host/IP: %s" % dev.host)
    for k, v in dev.sync.get_state_information().items():
        click.echo("%s: %s" % (k, v))
    click.echo(click.style("== Generic information ==", bold=True))
    click.echo("Time:         %s" % dev.sync.get_time())
    click.echo("Hardware:     %s" % dev.sync.get_hw_info()["hw_ver"])
    click.echo("Software:     %s" % dev.sync.get_hw_info()["sw_ver"])
    click.echo("MAC (rssi):   %s (%s)" % (dev.sync.get_mac(), dev.sync.get_rssi()))
    click.echo("Location:     %s" % dev.sync.get_location())

    ctx.invoke(emeter)


@cli.command()
@pass_dev
@click.argument("new_alias", required=False, default=None)
def alias(dev, new_alias):
    """Get or set the device alias."""
    if new_alias is not None:
        click.echo("Setting alias to %s" % new_alias)
        dev.sync.set_alias(new_alias)

    click.echo("Alias: %s" % dev.sync.get_alias())


@cli.command()
@pass_dev
@click.argument("module")
@click.argument("command")
@click.argument("parameters", default=None, required=False)
def raw_command(dev: SmartDevice, module, command, parameters):
    """Run a raw command on the device."""
    import ast

    if parameters is not None:
        parameters = ast.literal_eval(parameters)
    res = dev.sync._query_helper(module, command, parameters)
    click.echo(res)


@cli.command()
@pass_dev
@click.option("--year", type=click.DateTime(["%Y"]), default=None, required=False)
@click.option("--month", type=click.DateTime(["%Y-%m"]), default=None, required=False)
@click.option("--erase", is_flag=True)
def emeter(dev, year, month, erase):
    """Query emeter for historical consumption."""
    click.echo(click.style("== Emeter ==", bold=True))
    if not dev.sync.get_has_emeter():
        click.echo("Device has no emeter")
        return

    if erase:
        click.echo("Erasing emeter statistics..")
        dev.sync.erase_emeter_stats()
        return

    if year:
        click.echo("== For year %s ==" % year.year)
        emeter_status = dev.sync.get_emeter_monthly(year.year)
    elif month:
        click.echo("== For month %s of %s ==" % (month.month, month.year))
        emeter_status = dev.sync.get_emeter_daily(year=month.year, month=month.month)
    else:
        emeter_status = dev.sync.get_emeter_realtime()
        click.echo("== Current State ==")

    if isinstance(emeter_status, list):
        for plug in emeter_status:
            click.echo("Plug %d: %s" % (emeter_status.index(plug) + 1, plug))
    else:
        click.echo("%s" % emeter_status)


@cli.command()
@click.argument("brightness", type=click.IntRange(0, 100), default=None, required=False)
@pass_dev
def brightness(dev, brightness):
    """Get or set brightness."""
    if not dev.sync.is_dimmable():
        click.echo("This device does not support brightness.")
        return
    if brightness is None:
        click.echo("Brightness: %s" % dev.sync.get_brightness())
    else:
        click.echo("Setting brightness to %s" % brightness)
        dev.sync.set_brightness(brightness)


@cli.command()
@click.argument(
    "temperature", type=click.IntRange(2500, 9000), default=None, required=False
)
@pass_dev
def temperature(dev: SmartBulb, temperature):
    """Get or set color temperature."""
    if temperature is None:
        click.echo("Color temperature: %s" % dev.sync.get_color_temp())
        valid_temperature_range = dev.sync.get_valid_temperature_range()
        if valid_temperature_range != (0, 0):
            click.echo("(min: %s, max: %s)" % valid_temperature_range)
        else:
            click.echo(
                "Temperature range unknown, please open a github issue"
                " or a pull request for model '%s'" % dev.sync.get_model()
            )
    else:
        click.echo("Setting color temperature to %s" % temperature)
        dev.sync.set_color_temp(temperature)


@cli.command()
@click.argument("h", type=click.IntRange(0, 360), default=None, required=False)
@click.argument("s", type=click.IntRange(0, 100), default=None, required=False)
@click.argument("v", type=click.IntRange(0, 100), default=None, required=False)
@click.pass_context
@pass_dev
def hsv(dev, ctx, h, s, v):
    """Get or set color in HSV. (Bulb only)."""
    if h is None or s is None or v is None:
        click.echo("Current HSV: %s %s %s" % dev.sync.get_hsv())
    elif s is None or v is None:
        raise click.BadArgumentUsage("Setting a color requires 3 values.", ctx)
    else:
        click.echo("Setting HSV: %s %s %s" % (h, s, v))
        dev.sync.set_hsv(h, s, v)


@cli.command()
@click.argument("state", type=bool, required=False)
@pass_dev
def led(dev, state):
    """Get or set (Plug's) led state."""
    if state is not None:
        click.echo("Turning led to %s" % state)
        dev.sync.set_led(state)
    else:
        click.echo("LED state: %s" % dev.sync.get_led())


@cli.command()
@pass_dev
def time(dev):
    """Get the device time."""
    click.echo(dev.sync.get_time())


@cli.command()
@click.argument("index", type=int, required=False)
@pass_dev
def on(plug, index):
    """Turn the device on."""
    click.echo("Turning on..")
    if index is None:
        plug.turn_on()
    else:
        plug.turn_on(index=(index - 1))


@cli.command()
@click.argument("index", type=int, required=False)
@pass_dev
def off(plug, index):
    """Turn the device off."""
    click.echo("Turning off..")
    if index is None:
        plug.turn_off()
    else:
        plug.turn_off(index=(index - 1))


@cli.command()
@click.option("--delay", default=1)
@pass_dev
def reboot(plug, delay):
    """Reboot the device."""
    click.echo("Rebooting the device..")
    plug.reboot(delay)


if __name__ == "__main__":
    cli()
