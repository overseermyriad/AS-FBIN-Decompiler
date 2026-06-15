import os
import sys
import json
import subprocess
import shutil
import struct
import re
import uuid
from pathlib import Path
from PIL import Image

# ==========================================
# 1. Flash Binary Parser
# ==========================================
class FlashBinParser:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0

    def read_byte(self) -> int:
        val = self.data[self.offset]
        self.offset += 1
        return val

    def read_short(self) -> int:
        val = struct.unpack_from('<H', self.data, self.offset)[0]
        self.offset += 2
        return val

    def read_float(self) -> float:
        val = struct.unpack_from('<f', self.data, self.offset)[0]
        self.offset += 4
        return val

    def read_string(self) -> str:
        length = self.read_byte()
        string_data = self.data[self.offset : self.offset + length]
        self.offset += length
        return string_data.decode('utf-8', errors='ignore')

    def parse(self):
        output = {"sprites": [], "movieclips": [], "actions": [], "mc_frames": []}

        num_sprites = self.read_short()
        for _ in range(num_sprites):
            output["sprites"].append({
                "name": self.read_string(),
                "x": self.read_float(), "y": self.read_float(),
                "w": self.read_float(), "h": self.read_float(),
                "atlasU1": self.read_float(), "atlasV1": self.read_float(),
                "atlasU2": self.read_float(), "atlasV2": self.read_float()
            })

        num_movieclips = self.read_short()
        for i in range(num_movieclips):
            output["movieclips"].append({"id": i, "name": self.read_string()})

        num_actions = self.read_short()
        for _ in range(num_actions):
            output["actions"].append({
                "name": self.read_string(),
                "start_frame": self.read_short(), "end_frame": self.read_short(),
                "ref_movieclip_id": self.read_short(), "ref_first_frame": self.read_short()
            })

        for mc_idx in range(num_movieclips):
            num_frames = self.read_short()
            unk_short = self.read_short()
            
            mc_timeline = {
                "movieclip_id": mc_idx,
                "movieclip_name": output["movieclips"][mc_idx]["name"],
                "total_frames": num_frames, "flag": unk_short, "frames": []
            }

            for f_idx in range(num_frames):
                frame_node_num = self.read_short()
                num_elements = self.read_short()
                
                frame_data = {"frame_index": f_idx, "node_num": frame_node_num, "elements": []}

                for e_idx in range(num_elements):
                    node_type = self.read_byte()
                    symbol_id = self.read_short()
                    blend_add = self.read_byte()
                    cur_frame = self.read_short()

                    symbol_name = "UNKNOWN"
                    if node_type == 0 and symbol_id < len(output["sprites"]):
                        symbol_name = output["sprites"][symbol_id]["name"]
                    elif node_type == 1 and symbol_id < len(output["movieclips"]):
                        symbol_name = output["movieclips"][symbol_id]["name"]

                    transform = {
                        "a": self.read_float(), "b": self.read_float(), "c": self.read_float(),
                        "d": self.read_float(), "tx": self.read_float(), "ty": self.read_float()
                    }

                    color = {"r": self.read_byte(), "g": self.read_byte(), "b": self.read_byte(), "a": self.read_byte()}
                    color_swap = {"r": self.read_byte(), "g": self.read_byte(), "b": self.read_byte(), "a": self.read_byte()}

                    frame_data["elements"].append({
                        "type": ["img", "mc", "null"][node_type] if node_type <= 2 else str(node_type),
                        "symbol_id": symbol_id, "symbol_name": symbol_name,
                        "blend_additive": bool(blend_add), "nested_frame": cur_frame,
                        "transform": transform, "color_tint": color, "color_swap": color_swap
                    })
                mc_timeline["frames"].append(frame_data)
            output["mc_frames"].append(mc_timeline)
        return output

# ==========================================
# 2. PVR to PNG Converter
# ==========================================
def convert_pvr_to_png(input_pvr_path):
    cli_path = Path(r"C:\Program Files\Imgtec\PowerVR_Tools\PVRTexTool\CLI\Windows_x86_64\PVRTexToolCLI.exe")
    if not cli_path.exists():
        print(f"Error: PVRTexToolCLI.exe not found at {cli_path}")
        return False

    input_path = Path(input_pvr_path).resolve()
    output_path = input_path.with_suffix(".png")

    command = [str(cli_path), "-i", str(input_path), "-ics", "sRGB", "-noout", "-d", str(output_path)]
    try:
        subprocess.run(command, capture_output=True, text=True, check=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"PVR Conversion failed: {e.stderr}")
        return False

# ==========================================
# 3. Atlas Slicer
# ==========================================
def slice_texture_atlas(json_path, image_path, output_dir):
    try:
        with open(json_path, 'r') as f:
            data = json.load(f)
        atlas_image = Image.open(image_path).convert("RGBA")
    except Exception as e:
        print(f"Error loading files for slicing: {e}")
        return False

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    success_count = 0
    for sprite in data.get("sprites", []):
        try:
            name = sprite["name"]
            left, top = int(sprite["atlasU1"]), int(sprite["atlasV1"])
            right, bottom = left + int(sprite["atlasU2"]), top + int(sprite["atlasV2"])

            if right <= left or bottom <= top:
                continue

            cropped_sprite = atlas_image.crop((left, top, right, bottom))
            clean_sprite = Image.new("RGBA", cropped_sprite.size)
            clean_sprite.putdata(list(cropped_sprite.get_flattened_data()))

            safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '', name)
            clean_sprite.save(os.path.join(output_dir, f"{safe_name}.png"), "PNG")
            success_count += 1
        except Exception as e:
            print(f"Failed to extract {name}: {e}")
            
    print(f"Successfully sliced {success_count} sprites.")
    return True

# ==========================================
# 4. JSFL/XFL Generator
# ==========================================
def gen_id():
    u = uuid.uuid4().hex
    return f"{u[:8]}-{u[8:16]}"

def safe_str(name):
    return re.sub(r'[^a-zA-Z0-9_\-]', '', name)

def generate_xfl(json_data, png_folder, output_dir):
    lib_dir = os.path.join(output_dir, "LIBRARY")
    sprites_dir = os.path.join(lib_dir, "Sprites")
    mc_dir = os.path.join(lib_dir, "MovieClips")
    
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(sprites_dir)
    os.makedirs(mc_dir)

    with open(os.path.join(output_dir, "main.xfl"), "w", encoding="utf-8") as f:
        f.write("PROXY-CS5")

    include_tags, media_tags = [], []
    anchor_id = gen_id()
    include_tags.append(f'          <Include href="MovieClips/EmptyAnchor.xml" loadImmediate="false" itemID="{anchor_id}" />')
    
    anchor_xml = f"""<DOMSymbolItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" name="MovieClips/EmptyAnchor" itemID="{anchor_id}" symbolType="movie clip">\n  <timeline>\n    <DOMTimeline name="EmptyAnchor">\n      <layers>\n        <DOMLayer name="Layer 1" color="#4F80FF">\n          <frames>\n            <DOMFrame index="0" keyMode="9728"><elements/></DOMFrame>\n          </frames>\n        </DOMLayer>\n      </layers>\n    </DOMTimeline>\n  </timeline>\n</DOMSymbolItem>"""
    with open(os.path.join(mc_dir, "EmptyAnchor.xml"), "w", encoding="utf-8") as f:
        f.write(anchor_xml)

    for sprite in json_data.get("sprites", []):
        s_name = safe_str(sprite["name"])
        s_x, s_y = float(sprite["x"]), float(sprite["y"]) 
        sprite_id, bitmap_id = gen_id(), gen_id()
        
        src_png = os.path.join(png_folder, f"{s_name}.png")
        if os.path.exists(src_png):
            shutil.copy(src_png, os.path.join(sprites_dir, f"{s_name}.png"))

        media_tags.append(f'          <DOMBitmapItem name="Sprites/{s_name}.png" itemID="{bitmap_id}" sourceExternalFilepath="./LIBRARY/Sprites/{s_name}.png" sourceLastImported="1" allowSmoothing="true" useImportedJPEGData="false" href="Sprites/{s_name}.png" />')
        include_tags.append(f'          <Include href="Sprites/{s_name}.xml" itemIcon="1" loadImmediate="false" itemID="{sprite_id}" />')

        sprite_xml = f"""<DOMSymbolItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" name="Sprites/{s_name}" itemID="{sprite_id}" symbolType="graphic">\n  <timeline>\n    <DOMTimeline name="{s_name}">\n      <layers>\n        <DOMLayer name="Layer 1" color="#4F80FF" current="true" isSelected="true">\n          <frames>\n            <DOMFrame index="0" keyMode="9728">\n              <elements>\n                <DOMBitmapInstance selected="true" libraryItemName="Sprites/{s_name}.png">\n                  <matrix>\n                    <Matrix tx="{s_x}" ty="{s_y}"/>\n                  </matrix>\n                </DOMBitmapInstance>\n              </elements>\n            </DOMFrame>\n          </frames>\n        </DOMLayer>\n      </layers>\n    </DOMTimeline>\n  </timeline>\n</DOMSymbolItem>"""
        with open(os.path.join(sprites_dir, f"{s_name}.xml"), "w", encoding="utf-8") as f:
            f.write(sprite_xml)

    for mc_data in json_data.get("mc_frames", []):
        mc_name = safe_str(mc_data["movieclip_name"])
        mc_id = gen_id()
        include_tags.append(f'          <Include href="MovieClips/{mc_name}.xml" loadImmediate="false" itemID="{mc_id}" />')

        frame_xmls = []
        for frame in mc_data.get("frames", []):
            f_idx = frame["frame_index"]
            element_xmls = []
            for el in frame.get("elements", []):
                sym_name, item_type = safe_str(el["symbol_name"]), el["type"]
                lib_path = "MovieClips/EmptyAnchor" if sym_name == "UNKNOWN" or item_type not in ["img", "mc"] else (f"Sprites/{sym_name}" if item_type == "img" else f"MovieClips/{sym_name}")
                
                t = el["transform"]
                a, b, c, d, tx, ty = float(t["a"]), -float(t["b"]), -float(t["c"]), float(t["d"]), float(t["tx"]), -float(t["ty"])
                
                mat_attrs = []
                if a != 1.0: mat_attrs.append(f'a="{a}"')
                if b != 0.0: mat_attrs.append(f'b="{b}"')
                if c != 0.0: mat_attrs.append(f'c="{c}"')
                if d != 1.0: mat_attrs.append(f'd="{d}"')
                if tx != 0.0: mat_attrs.append(f'tx="{tx}"')
                if ty != 0.0: mat_attrs.append(f'ty="{ty}"')
                mat_str = " ".join(mat_attrs)
                mat_xml = f'<matrix><Matrix {mat_str}/></matrix>' if mat_str else ""
                
                c_tint = el.get("color_tint", {})
                color_xml = ""
                if c_tint.get("a", 255) < 255 or c_tint.get("r", 255) < 255 or c_tint.get("g", 255) < 255 or c_tint.get("b", 255) < 255:
                    color_xml = f'\n                  <color>\n                    <Color alphaMultiplier="{round(c_tint.get("a", 255)/255.0, 3)}" redMultiplier="{round(c_tint.get("r", 255)/255.0, 3)}" greenMultiplier="{round(c_tint.get("g", 255)/255.0, 3)}" blueMultiplier="{round(c_tint.get("b", 255)/255.0, 3)}"/>\n                  </color>'

                blend_xml = '\n                  <blendMode>add</blendMode>' if el.get("blend_additive") else ""
                nested_attr = f' firstFrame="{el.get("nested_frame")}"' if item_type == "mc" and el.get("nested_frame", -1) not in [-1, 65535] else ""

                element_xmls.append(f"""\n                <DOMSymbolInstance libraryItemName="{lib_path}" symbolType="graphic" loop="loop"{nested_attr}>\n                  {mat_xml}{color_xml}{blend_xml}\n                </DOMSymbolInstance>""")

            elements_block = "\n              <elements>" + "".join(element_xmls) + "\n              </elements>\n            " if element_xmls else "\n              <elements/>\n            "
            frame_xmls.append(f'<DOMFrame index="{f_idx}" keyMode="9728">{elements_block}</DOMFrame>')

        with open(os.path.join(mc_dir, f"{mc_name}.xml"), "w", encoding="utf-8") as f:
            f.write(f"""<DOMSymbolItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" name="MovieClips/{mc_name}" itemID="{mc_id}" symbolType="movie clip">\n  <timeline>\n    <DOMTimeline name="{mc_name}">\n      <layers>\n        <DOMLayer name="Layer 1" color="#4F80FF">\n          <frames>\n            {"".join(frame_xmls)}\n          </frames>\n        </DOMLayer>\n      </layers>\n    </DOMTimeline>\n  </timeline>\n</DOMSymbolItem>""")

    with open(os.path.join(output_dir, "DOMDocument.xml"), "w", encoding="utf-8") as f:
        f.write(f"""<DOMDocument xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" width="390" height="390" frameRate="30" currentTimeline="1" xflVersion="2.6" creatorInfo="Automated Generator" platform="Windows" versionInfo="Saved by Generator" majorVersion="15" buildNumber="173" viewAngle3D="40.5211685505111" nextSceneIdentifier="2" playOptionsPlayLoop="false" playOptionsPlayPages="false" playOptionsPlayFrameActions="false" filetypeGUID="DD0DDBBF-5BEF-45B2-9F24-A3048D2A676F">\n     <folders>\n          <DOMFolderItem name="MovieClips" itemID="{gen_id()}"/>\n          <DOMFolderItem name="Sprites" itemID="{gen_id()}"/>\n     </folders>\n     <media>\n{"\n".join(media_tags)}\n     </media>\n     <symbols>\n{"\n".join(include_tags)}\n     </symbols>\n     <timelines>\n          <DOMTimeline name="Scene 1">\n               <layers>\n                    <DOMLayer name="Layer 1" color="#4F80FF" current="true" isSelected="true">\n                         <frames>\n                              <DOMFrame index="0" keyMode="9728">\n                                   <elements/>\n                              </DOMFrame>\n                         </frames>\n                    </DOMLayer>\n               </layers>\n          </DOMTimeline>\n     </timelines>\n     <PrinterSettings/>\n     <publishHistory/>\n</DOMDocument>""")

# ==========================================
# 5. Master Pipeline Coordinator
# ==========================================
def main():
    if len(sys.argv) < 3:
        print("Usage: python animate_pipeline.py <input.bin> <input.pvr>")
        sys.exit(1)

    bin_path = Path(sys.argv[1]).resolve()
    pvr_path = Path(sys.argv[2]).resolve()

    if not bin_path.exists() or not pvr_path.exists():
        print("Error: One or both input files do not exist.")
        sys.exit(1)

    base_name = bin_path.stem
    work_dir = bin_path.parent
    
    png_file = pvr_path.with_suffix(".png")
    json_file = work_dir / f"{base_name}.json"
    temp_sprites_dir = work_dir / f"{base_name}_temp_sprites"
    output_xfl_dir = work_dir / f"{base_name}_XFL"

    print(f"--- Starting Pipeline for {base_name} ---")

    # Step 1: PVR to PNG
    print("\n[1/5] Converting PVR to PNG...")
    if not convert_pvr_to_png(pvr_path):
        return

    # Step 2: Binary to JSON
    print("\n[2/5] Parsing Binary to JSON...")
    try:
        with open(bin_path, "rb") as f:
            binary_data = f.read()
        
        parser = FlashBinParser(binary_data)
        parsed_json = parser.parse()
        
        with open(json_file, "w") as f:
            json.dump(parsed_json, f, indent=4)
    except Exception as e:
        print(f"Failed to parse binary: {e}")
        return

    # Step 3: Slice Atlas
    print("\n[3/5] Slicing Texture Atlas...")
    if not slice_texture_atlas(json_file, png_file, temp_sprites_dir):
        return

    # Step 4: Generate XFL
    print("\n[4/5] Building XFL Project Folder...")
    generate_xfl(parsed_json, temp_sprites_dir, output_xfl_dir)

    # Step 5: Cleanup
    print("\n[5/5] Cleaning up temporary files...")
    try:
        if png_file.exists(): os.remove(png_file)
        if json_file.exists(): os.remove(json_file)
        if temp_sprites_dir.exists(): shutil.rmtree(temp_sprites_dir)
        print(" Cleanup complete. Kept original .bin, .pvr, and the final XFL directory.")
    except Exception as e:
        print(f" Warning: Cleanup encountered an issue: {e}")

    print(f"\n Pipeline Complete! XFL Project is ready at: {output_xfl_dir}")

if __name__ == "__main__":
    main()