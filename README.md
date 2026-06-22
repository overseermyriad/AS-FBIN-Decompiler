# AS-FBIN-Decompiler
This is a python file that decompiles the animation formats of the popular game Plants vs. Zombies: All Stars (Chinese name: 植物大战僵尸: 全明星) into Adobe Animate XFL format.

The decompiler currently supports all IPA and APK versions publically available. If a version is not supported, please tell me.

The output XFL is in the same format as PvZ2 XFLs to help animators and modders easily read, edit and implement these animations.

Example usage:
AS_to_XFL.py input.bin input.pvr

Supported arguments:
--clean-dust: Attempts to remove PVR file artifacts by removing opaque pixels. Warning: It could break the asset if it relies on opaque pixels.


It comes with 2 batch scripts that process all of the BINs and PVR/PNGs if they have matching names in the folder where the batch file is located. The batch file with --clean-dust automatically enables artifact removal.

Required Libraries:

Python

pip install Pillow

https://developer.imaginationtech.com/solutions/pvrtextool/

PVRTexToolCLI must be installed to C:\Program Files\Imgtec\PowerVR_Tools\PVRTexTool\CLI\Windows_x86_64\PVRTexToolCLI.exe


Notes:

On IPA assets, the people who compiled these assets for iPhones overcompressed them. Perhaps they did that to save space or performance. As a result, since PVR files are raw graphics data that has premultiplied alpha, converting them bavk to PNGs introduces artifacts. I cannot really do anything to fix this as the tools PowerVR provided us with can only do so much. The only way I have in mind to recover them is by making an OpenGL enviroment to render PVRs and extract the correct data, but it will be extremely difficult since PVRs compiled for Android and iOS cannot be read by PC GPUs. If you find a better method to recover them, please tell me.

This tool can take a raw PNG, a PVR or a file that has a PNG extension but is encoded as a PVR.

This tool is not perfect, so if there are any bugs, please tell me or someone who can contact me. Good luck.
