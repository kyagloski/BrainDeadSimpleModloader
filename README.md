# BrainDead Simple Modloader
<img width="972" height="845" alt="splash" src="https://github.com/user-attachments/assets/1785423d-453e-4258-b035-4b5649424f54" />

## Overview
A Python-based mod management tool designed as an alternative to Mod Organizer 2 for Linux and Windows platforms. This application enables efficient management of mod collections for Bethesda games, including Skyrim, Fallout 3, Fallout 4, and Fallout: New Vegas.
Multiple instances for one or many games can all be managed at the same time by this powerful mod tool.

Currently this tool is supported on both Linux and Windows. Its primary maintenance focus will be on Linux, however.

## Supported Games

### Currently Supported
- Fallout 3 GOTY
- Fallout 3 (non-GOTY)
- Fallout New Vegas
- Fallout 4
- Fallout 4 VR
- Oblivion
- Skyrim Special Edition
- Skyrim (Legacy Version)
- Skyrim VR

*You can try your luck with other games, as arbitary folder choices are acceptable, but more work needs to be done to fully support this*

## Features
- **Multi-File Drag-and-Drop Installation**: Install multiple mods simultaneously with intuitive drag-and-drop functionality
- **Multi Instance Management**: Manage multiple BDSM instances for one or many games, separating your mod list and configuration
- **INI Editor and Backup System**: Edit configuration files with built-in backup protection
- **Game Executable Management**: Launch game executables directly from the application
- **Multiple Preset Support**: Create and manage different mod configurations
- **Mod File Explorer**: Browse and manage mod files with ease
- **FOMOD Installer Support**: Guided installation for mods with FOMOD installers

## Initial Setup

Upon launching the application for the first time, you will be prompted to specify your game's target directory. This should be the root directory of your game installation (e.g., `/steam_games/Fallout 4/`).

The tool will install mods to the `Data` folder within your game directory. While you can manually select the `Data` folder during setup, the application will automatically append it to your specified path if not already included.

After configuring your target path you should be greeted with a screen such as this:
<img width="1214" height="770" alt="sky" src="https://github.com/user-attachments/assets/c5e1059c-1f16-4bf1-a2a1-05d8be83c824" />

There are many themes to choose from and now resources are pulled from the Steam API for things like backgrounds and game icons. There a few more themes not listed here and you can create more yourself, the are located in the `/resources/stylesheets` directory, based on the qss file format.

<table style="border:none; border-collapse:collapse;">
  <tr>
    <td style="border:none; padding:4px;"><img src="https://github.com/user-attachments/assets/1baadc22-d7f6-42ee-9171-56510d65dc1f" width="250"/></td>
    <td style="border:none; padding:4px;"><img src="https://github.com/user-attachments/assets/19cacaa7-9642-499a-9460-8c645c3edeac" width="250"/></td>
    <td style="border:none; padding:4px;"><img src="https://github.com/user-attachments/assets/65d6bc02-0299-4d9b-9a75-053bd93e0cb1" width="250"/></td>
  </tr>
  <tr>
    <td style="border:none; padding:4px;"><img src="https://github.com/user-attachments/assets/43e05b8b-14b9-4f59-8fe1-8e15675c38a5" width="250"/></td>
    <td style="border:none; padding:4px;"><img src="https://github.com/user-attachments/assets/efe764d1-173f-41c0-8385-e15705b7bc2a" width="250"/></td>
    <td style="border:none; padding:4px;"><img src="https://github.com/user-attachments/assets/1b2f13a0-94ec-497d-9dfe-0bb93b406bba" width="250"/></td>
  </tr>
</table>


## Installing Mods

After initial setup, you can install mods using either of the following methods:
- Click the **"+"** button on the bottom toolbar
- Drag and drop one or more mod files into the center window
  
Acceptable File Formats
- 7z, RAR, Zip, Directories
  
Installed mods are stored in a staging directory located at `./BrainDeadSimpleModloader/mods/` within the application's root folder (default configuration).

Example of multiple mod install by dragging and dropping files
(install order is based off timestamp)
![test](https://github.com/user-attachments/assets/98c2e6e1-e909-4022-aa74-aecdb13d2045)
                                  (50+ mods installed in <15s! let's see mo2 do that!)

## Launching Games

1. Select your desired game executable from the dropdown menu in the top-right corner
2. Click the **Play** button to launch the game

The listed binaries can be configured by the user by clicking the button next to the drop down.

<img width="678" height="304" alt="em" src="https://github.com/user-attachments/assets/ba489aef-f7be-44aa-b759-17801b28c088" />


## Instance Manager
Add multiple instances for a game or multiple games. You can also duplicate instances to have a known starting point for a new instance configuration.

<img width="408" height="594" alt="im" src="https://github.com/user-attachments/assets/96248692-7552-4daf-8973-5593bc10664d" /><img width="508" height="254" alt="ie" src="https://github.com/user-attachments/assets/898940cc-4c8a-4e0c-bbaa-28187059a716" />

## INI Manager
The INI Manager can manage backups for your INI files because Bethesda is really good at breaking INI configurations. Upon opening you'll find two columns, your backups, and your current game files. By clicking `Backup` it will create a timestamped backup in the root folder of your instance under the `./BrainDeadSimpleModloader/inis/` directory.

<img width="1746" height="1031" alt="aaa" src="https://github.com/user-attachments/assets/5650c9e0-b9d0-4bf9-a9a6-d23f8255209b" />
(Soon there will be a diff mode to view changes across files)

## Technical Details

### How It Works

The technical workflow for how mods are injected is as follows:

1. **Mod Installation**: Mods are placed in a staging directory upon installation
2. **Mod Loading**: When launching the game or clicking the **"Load Mods"** button, all files from the staging directory are symlinked to your game's `Data` directory. Symlinking is key here because it is orders of mangitude faster than copying files around (on Windows hard links are used).
3. **File Management**: The tool maintains a manifest of all file operations, ensuring that overwritten files are tracked and all load/restore operations are idempotent (can be repeated safely without unintended effects)

This approach ensures clean mod management while preserving your original game files.

