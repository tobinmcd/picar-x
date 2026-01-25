# Picar-X

Picar-X Python library for Raspberry Pi.

## Links

- Docs: <https://docs.sunfounder.com/projects/picar-x-v20/en/latest/>
- Robot Hat: <https://docs.sunfounder.com/projects/robot-hat-v4/en/latest/>
- Forum: <https://forum.sunfounder.com/>
- Sunfounder: <https://www.sunfounder.com/>

## Installation

 > **Note**
  You also need to install robot_hat, vilib, sunfounder_controller and other dependent libraries.\
  <https://docs.sunfounder.com/projects/picar-x-v20/en/latest/python/python_start/install_all_modules.html>

## UV-based setup (recommended for this fork)

This fork uses `uv` to manage dependencies and includes the `gerg_driver` FastAPI server.
Robot-only libraries are grouped so development machines can install without hardware
dependencies.

```bash
# Local development (no robot-only deps)
uv sync

# Robot environment (includes robot-hat, vilib, smbus2 via git URLs)
uv sync --group robot
```

The robot-only dependencies are pulled from the SunFounder GitHub repos, so you do
not need local checkouts for `robot-hat` or `vilib`.

To run the FastAPI control server (`gerg_driver`):

```bash
uv run picarx-serve --host 0.0.0.0 --port 8000
```

You can also sync robot dependencies with `poe`:

```bash
poe robot-sync
```

```bash
# Install robot_hat
git clone --depth 1 -b 2.5.x https://github.com/sunfounder/robot-hat.git
cd robot-hat
sudo python3 install.py

# Install vilib
git clone --depth 1 https://github.com/sunfounder/vilib.git
cd vilib
sudo python3 install.py

# Install picar-x
git clone -b 2.1.x https://github.com/sunfounder/picar-x.git
cd picar-x
sudo pip3 install . --break
```

## Debug

Debug command records

```bash
cd ~/picar-x && sudo pip3 install . --break --no-deps --no-build-isolation
```

## Debug records

```bash
sudo pip3 uninstall picar-x --break -y && cd ~/picar-x && sudo pip3 install . --break --no-deps --no-build-isolation
sudo pip3 uninstall robot_hat --break -y && cd ~/robot-hat && sudo pip3 install . --break --no-deps --no-build-isolation
sudo python3 ~/picar-x/examples/14_voice_active_car_gpt.py
```

----------------------------------------------

## About SunFounder

SunFounder is a technology company focused on Raspberry Pi and Arduino open source community development. Committed to the promotion of open source culture, we strives to bring the fun of electronics making to people all around the world and enable everyone to be a maker. Our products include learning kits, development boards, robots, sensor modules and development tools. In addition to high quality products, SunFounder also offers video tutorials to help you make your own project. If you have interest in open source or making something cool, welcome to join us!

----------------------------------------------

## License

This program is free software; you can redistribute it and/or modify it under the terms of the GNU General Public License as published by the Free Software Foundation; either version 2 of the License, or (at your option) any later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY; without even the implied wa rranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

You should have received a copy of the GNU General Public License along with this program; if not, write to the Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

{Repository Name} comes with ABSOLUTELY NO WARRANTY; for details run ./show w. This is free software, and you are welcome to redistribute it under certain conditions; run ./show c for details.

SunFounder, Inc., hereby disclaims all copyright interest in the program '{Repository Name}' (which makes passes at compilers).

Mike Huang, 21 August 2015

Mike Huang, Chief Executive Officer

Email: service@sunfounder.com, support@sunfounder.com

----------------------------------------------

## Contact us

website:
    www.sunfounder.com

E-mail:
    service@sunfounder.com, support@sunfounder.com
