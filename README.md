# BrainDead Simple Modloader
<img width="959" height="984" alt="splash" src="https://github.com/user-attachments/assets/44d4af07-9406-464f-a461-9fbf83fa81b7" />

## Overview
A Python-based mod management tool designed as an alternative to Mod Organizer 2 for Linux and Windows platforms. This application enables efficient management of mod collections for Bethesda games, including Skyrim, Fallout 3, Fallout 4, and Fallout: New Vegas.

Currently this tool works on Linux, it is eventually meant to work on Windows but is currently completely untested. Good luck!

## Features
- **Multi-File Drag-and-Drop Installation**: Install multiple mods simultaneously with intuitive drag-and-drop functionality
- **INI Editor and Backup System**: Edit configuration files with built-in backup protection
- **Game Executable Management**: Launch game executables directly from the application
- **Multiple Preset Support**: Create and manage different mod configurations
- **Mod File Explorer**: Browse and manage mod files with ease

## Initial Setup

Upon launching the application for the first time, you will be prompted to specify your game's target directory. This should be the root directory of your game installation (e.g., `/steam_games/Fallout 4/`).

The tool will install mods to the `Data` folder within your game directory. While you can manually select the `Data` folder during setup, the application will automatically append it to your specified path if not already included.

After configuring your target path you should be greeted with a screen such as this:
<img width="1249" height="785" alt="gui" src="https://github.com/user-attachments/assets/ad0ac238-1819-4979-bf6e-a7588cb0cec7" />

## Installing Mods

After initial setup, you can install mods using either of the following methods:
- Click the **"+"** button on the bottom toolbar
- Drag and drop one or more mod files into the center window

Installed mods are stored in a staging directory located at `./mods/staging/` within the application's root folder (default configuration).

## Launching Games

1. Select your desired game executable from the dropdown menu in the top-right corner
2. Click the **Play** button to launch the game

## Technical Details

### How It Works

The modloader operates similarly to Mod Organizer 2's portable mode, with each instance managing a single game installation. The workflow is as follows:

1. **Mod Installation**: Mods are placed in a staging directory upon installation
2. **Mod Loading**: When launching the game or clicking the **"Load Mods"** button, all files from the staging directory are symlinked to your game's `Data` directory
3. **File Management**: The tool maintains a manifest of all file operations, ensuring that overwritten files are tracked and all load/restore operations are idempotent (can be repeated safely without unintended effects)

This approach ensures clean mod management while preserving your original game files.
