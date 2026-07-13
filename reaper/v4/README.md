# H10 V4 REAPER assets

Source-controlled JSFX and setup script for the parallel V4 performance rig.

Installed locations:

- `~/Library/Application Support/REAPER/Effects/H10/V4/`
- `~/Library/Application Support/REAPER/Scripts/H10/V4/`

The setup script creates a new project tab, resolves MIDI input names instead
of hard-coding device numbers, builds the seven-track routing graph, installs
the master guard, and saves:

`/Users/taichengwong/Projects/H10/reaper_projects/H10 Live Performance V4.RPP`

It never edits the V3 project tab.

REAPER's MIDI inputs are global, not project-local. Enable `H10 Performance
V4` and `Arturia - Minilab3 - MIDI` once under Preferences > Audio > MIDI
Inputs. The setup script resolves their current names/IDs and warns when a
resolved device is disabled.
