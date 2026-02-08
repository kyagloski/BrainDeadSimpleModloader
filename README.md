# BrainDead Simple Modloader
<img width="972" height="845" alt="splash" src="https://github.com/user-attachments/assets/45e7377a-77ca-47a2-9c40-14b3f2a28cbb" />

## Overview
A Python-based mod management tool designed as an alternative to Mod Organizer 2 for Linux and Windows platforms. This application enables efficient management of mod collections for Bethesda games, including Skyrim, Fallout 3, Fallout 4, and Fallout: New Vegas.

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

### In Development
- Oblivion Remastered

## Features
- **Multi-File Drag-and-Drop Installation**: Install multiple mods simultaneously with intuitive drag-and-drop functionality
- **INI Editor and Backup System**: Edit configuration files with built-in backup protection
- **Game Executable Management**: Launch game executables directly from the application
- **Multiple Preset Support**: Create and manage different mod configurations
- **Mod File Explorer**: Browse and manage mod files with ease
- **FOMOD Installer Support**: Guided installation for mods with FOMOD installers

## Initial Setup

Upon launching the application for the first time, you will be prompted to specify your game's target directory. This should be the root directory of your game installation (e.g., `/steam_games/Fallout 4/`).

The tool will install mods to the `Data` folder within your game directory. While you can manually select the `Data` folder during setup, the application will automatically append it to your specified path if not already included.

After configuring your target path you should be greeted with a screen such as this:
<img width="1249" height="782" alt="test" src="https://github.com/user-attachments/assets/0d86590c-72a6-4df7-b277-e2ddf318ac32" />

## Installing Mods

After initial setup, you can install mods using either of the following methods:
- Click the **"+"** button on the bottom toolbar
- Drag and drop one or more mod files into the center window
  
Acceptable File Formats
- 7z, RAR, Zip, Directories
  
Installed mods are stored in a staging directory located at `./BrainDeadSimpleModloader/mods/` within the application's root folder (default configuration).

Example of multiple mod install by dragging and dropping files
(install order is based off timestamp)
![test2(2)](https://github.com/user-attachments/assets/7cbfc76e-adf8-4f71-9bd2-2164b78726a0)
                                  (50+ mods installed in <15s! let's see mo2 do that!)

## Launching Games

1. Select your desired game executable from the dropdown menu in the top-right corner
2. Click the **Play** button to launch the game

The listed binaries can be configured by the user by clicking the button next to the drop down.

Example of Executable Manager
<img width="1248" height="785" alt="testaaaa" src="https://github.com/user-attachments/assets/e71b17a4-0611-4c4c-9f3b-279a12de004a" />


## INI Manager
The INI Manager can manage backups for your INI files because Bethesda is really good at breaking INI configurations. Upon opening you'll find two columns, your backups, and your current game files. By clicking `Backup` it will create a timestamped backup in the root folder of your instance under the `./BrainDeadSimpleModloader/inis/` directory.

Example of INI Manager
<img width="1746" height="1031" alt="aaa" src="https://github.com/user-attachments/assets/5650c9e0-b9d0-4bf9-a9a6-d23f8255209b" />
(Soon there will be a diff mode to view changes across files)

## Technical Details

### How It Works

The modloader operates similarly to Mod Organizer 2's portable mode, with each instance managing a single game installation. The workflow is as follows:

1. **Mod Installation**: Mods are placed in a staging directory upon installation
2. **Mod Loading**: When launching the game or clicking the **"Load Mods"** button, all files from the staging directory are symlinked to your game's `Data` directory. Symlinking is key here because it is orders of mangitude faster than copying files around (on Windows hard links are used).
3. **File Management**: The tool maintains a manifest of all file operations, ensuring that overwritten files are tracked and all load/restore operations are idempotent (can be repeated safely without unintended effects)

This approach ensures clean mod management while preserving your original game files.

