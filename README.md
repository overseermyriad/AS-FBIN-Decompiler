# AS-FBIN-Decompiler
This is a python file that decompiles the animation formats of the popular game Plants vs. Zombies: All Stars (Chinese name: 植物大战僵尸: 全明星).

The decompiler currently supports IPA versions 1.0.16-1 or lower. It does not support later versions yet.

Example usage:
AS_to_XFL.py input.bin input.pvr

It comes with a batch script that processes all of the bins and pvrs if they have matching names.

Required Libraries:

Python

pip install Pillow

https://developer.imaginationtech.com/solutions/pvrtextool/

PVRTexToolCLI must be installed to C:\Program Files\Imgtec\PowerVR_Tools\PVRTexTool\CLI\Windows_x86_64\PVRTexToolCLI.exe
