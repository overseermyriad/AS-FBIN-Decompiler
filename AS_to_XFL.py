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

def is_valid_png(filepath):
    try:
        with open(filepath, 'rb') as f:
            return f.read(8) == b'\x89PNG\r\n\x1a\n'
    except Exception:
        return False

# ==========================================
# 1. Flash Binary Parser
# ==========================================
class FlashBinParser:
    def __init__(self, data: bytes):
        self.data = data
        self.offset = 0
        self.is_padded = False
        self.header_float = 1.0
        
        if self.data[0:4] == b"FBIN":
            self.format = "FBIN"
            if len(self.data) > 13 and all(b == 0 for b in self.data[5:13]):
                self.offset = 16
                self.header_float = self.read_fbin_float(100.0) 
                self.is_padded = True
            else:
                self.offset = 8
            print(f"-> Detected FBIN. Header scale: {self.header_float:.5f}")
        elif len(self.data) >= 12 and all(b == 0 for b in self.data[0:8]):
            self.format = "OLD"
            self.offset = 8
            self.header_float = self.read_float()
            self.is_padded = True
            print(f"-> Detected RAWBIN_PADDED. Header scale: {self.header_float:.5f}")
        else:
            self.format = "OLD"
            self.offset = 0
            print("-> Detected RAWBIN.")

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

    def read_fbin_float(self, divisor: float) -> float:
        type_flag = self.read_byte()
        if type_flag == 4:
            val = struct.unpack_from('<i', self.data, self.offset)[0]
            self.offset += 4
        elif type_flag == 2:
            val = struct.unpack_from('<h', self.data, self.offset)[0]
            self.offset += 2
        elif type_flag == 1:
            val = struct.unpack_from('<b', self.data, self.offset)[0]
            self.offset += 1
        else:
            val = 0
        return float(val) / divisor

    def read_string(self) -> str:
        length = self.read_byte()
        string_data = self.data[self.offset : self.offset + length]
        self.offset += length
        return string_data.decode('utf-8', errors='ignore')

    def parse(self):
        output = {"sprites": [], "movieclips": [], "actions": [], "mc_frames": []}

        num_sprites = self.read_short()
        print(f"-> Parsing {num_sprites} sprites...")
        for _ in range(num_sprites):
            name = self.read_string()
            if self.format == "FBIN":
                x = self.read_fbin_float(100.0)
                y = self.read_fbin_float(100.0)
                w = self.read_fbin_float(100.0)
                h = self.read_fbin_float(100.0)
                u1 = self.read_fbin_float(100.0)
                v1 = self.read_fbin_float(100.0)
                u2 = self.read_fbin_float(100.0)
                v2 = self.read_fbin_float(100.0)
            else:
                x = self.read_float()
                y = self.read_float()
                w = self.read_float()
                h = self.read_float()
                u1 = self.read_float()
                v1 = self.read_float()
                u2 = self.read_float()
                v2 = self.read_float()

            output["sprites"].append({
                "name": name, "x": x, "y": y, "w": w, "h": h,
                "atlasU1": u1, "atlasV1": v1, "atlasU2": u2, "atlasV2": v2
            })

        num_movieclips = self.read_short()
        print(f"-> Parsing {num_movieclips} movieclips...")
        for i in range(num_movieclips):
            output["movieclips"].append({"id": i, "name": self.read_string()})

        num_actions = self.read_short()
        print(f"-> Parsing {num_actions} actions...")
        for _ in range(num_actions):
            output["actions"].append({
                "name": self.read_string(),
                "start_frame": self.read_short(), "end_frame": self.read_short(),
                "ref_movieclip_id": self.read_short(), "ref_first_frame": self.read_short()
            })

        for mc_idx in range(num_movieclips):
            num_frames = self.read_short()
            unk_short = self.read_short()
            
            if self.is_padded:
                self.read_short()
            
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
                    if self.format == "FBIN":
                        flags = self.read_byte()
                        node_type = self.read_byte()
                        symbol_id = self.read_short()
                        blend_add = (flags & 1) != 0
                        cur_frame = self.read_short() if (flags & 2) != 0 else 65535
                        
                        a = self.read_fbin_float(10000.0) if (flags & 4) != 0 else 1.0
                        b = self.read_fbin_float(10000.0) if (flags & 8) != 0 else 0.0
                        c = self.read_fbin_float(10000.0) if (flags & 16) != 0 else 0.0
                        d = self.read_fbin_float(10000.0) if (flags & 32) != 0 else 1.0
                        
                        if (flags & 64) != 0:
                            tx = self.read_fbin_float(100.0)
                            ty = self.read_fbin_float(100.0)
                        else:
                            tx = 0.0
                            ty = 0.0
                            
                        if (flags & 128) != 0:
                            color = {"r": self.read_byte(), "g": self.read_byte(), "b": self.read_byte(), "a": self.read_byte()}
                            color_swap = {"r": self.read_byte(), "g": self.read_byte(), "b": self.read_byte(), "a": self.read_byte()}
                        else:
                            color = {"r": 255, "g": 255, "b": 255, "a": 255}
                            color_swap = {"r": 0, "g": 0, "b": 0, "a": 0}
                    else:
                        node_type = self.read_byte()
                        symbol_id = self.read_short()
                        blend_add = bool(self.read_byte())
                        cur_frame = self.read_short()
                        a = self.read_float()
                        b = self.read_float()
                        c = self.read_float()
                        d = self.read_float()
                        tx = self.read_float()
                        ty = self.read_float()
                        color = {"r": self.read_byte(), "g": self.read_byte(), "b": self.read_byte(), "a": self.read_byte()}
                        color_swap = {"r": self.read_byte(), "g": self.read_byte(), "b": self.read_byte(), "a": self.read_byte()}

                    symbol_name = "UNKNOWN"
                    item_type = "null"
                    
                    if node_type == 1:
                        if 0 <= symbol_id < len(output["movieclips"]):
                            symbol_name = output["movieclips"][symbol_id]["name"]
                            item_type = "mc"
                    else:
                        if 0 <= symbol_id < len(output["sprites"]):
                            symbol_name = output["sprites"][symbol_id]["name"]
                            item_type = "img"

                    transform = {"a": a, "b": b, "c": c, "d": d, "tx": tx, "ty": ty}

                    frame_data["elements"].append({
                        "type": item_type,
                        "symbol_id": symbol_id, "symbol_name": symbol_name,
                        "blend_additive": blend_add, "nested_frame": cur_frame,
                        "transform": transform, "color_tint": color, "color_swap": color_swap
                    })
                mc_timeline["frames"].append(frame_data)
            output["mc_frames"].append(mc_timeline)
        
        print("-> Binary parsing complete.")
        return output

# ==========================================
# 2. Geometry Tracker
# ==========================================
def merge_limits(limit1, limit2):
    if not limit1: return limit2
    if not limit2: return limit1
    return (
        min(limit1[0], limit2[0]),
        min(limit1[1], limit2[1]),
        max(limit1[2], limit2[2]),
        max(limit1[3], limit2[3])
    )

def extract_physical_bounds(mc_id, target_frame, sprite_list, mc_list, scale, current_transform=(1.0, 0.0, 0.0, 1.0, 0.0, 0.0), depth=0, scan_history=None):
    if scan_history is None:
        scan_history = set()
        
    if depth > 30 or mc_id in scan_history:
        return None
        
    scan_history.add(mc_id)
    
    active_mc = next((m for m in mc_list if m["movieclip_id"] == mc_id), None)
    if not active_mc or not active_mc.get("frames"):
        return None
        
    f_idx = max(0, min(target_frame, len(active_mc["frames"]) - 1))
    
    oa, ob, oc, od, otx, oty = current_transform
    global_extents = None
    
    for element in active_mc["frames"][f_idx].get("elements", []):
        e_type = element["type"]
        s_id = element["symbol_id"]
        
        t = element["transform"]
        xa, xb, xc, xd = float(t["a"]), -float(t["b"]), -float(t["c"]), float(t["d"])
        xtx, xty = float(t["tx"]) * scale, -float(t["ty"]) * scale
        
        va = oa*xa+oc*xb
        vb = ob*xa+od*xb
        vc = oa*xc+oc*xd
        vd = ob*xc+od*xd
        vtx = oa*xtx+oc*xty+otx
        vty = ob*xtx+od*xty+oty
        
        new_transform = (va, vb, vc, vd, vtx, vty)
        
        if e_type == "mc":
            nest_frame = element.get("nested_frame", 0)
            if nest_frame in (-1, 65535): nest_frame = 0
            
            child_bounds = extract_physical_bounds(s_id, nest_frame, sprite_list, mc_list, scale, new_transform, depth + 1, set(scan_history))
            global_extents = merge_limits(global_extents, child_bounds)
            
        elif e_type == "img":
            if 0 <= s_id < len(sprite_list):
                img_data = sprite_list[s_id]
                w = float(img_data["w"]) * scale
                h = float(img_data["h"]) * scale
                x = float(img_data["x"]) * scale
                y = float(img_data["y"]) * scale
                
                corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
                
                for (cx, cy) in corners:
                    mapped_x = va * cx + vc * cy + vtx
                    mapped_y = vb * cx + vd * cy + vty
                    
                    if not global_extents:
                        global_extents = (mapped_x, mapped_y, mapped_x, mapped_y)
                    else:
                        global_extents = (
                            min(global_extents[0], mapped_x),
                            min(global_extents[1], mapped_y),
                            max(global_extents[2], mapped_x),
                            max(global_extents[3], mapped_y)
                        )
                        
    return global_extents

# ==========================================
# 3. PVR Converter
# ==========================================
def convert_pvr_to_png(input_pvr_path, output_png_path):
    cli_path = Path(r"C:\Program Files\Imgtec\PowerVR_Tools\PVRTexTool\CLI\Windows_x86_64\PVRTexToolCLI.exe")
    if not cli_path.exists():
        print(f"[ERROR] PVRTexToolCLI.exe not found at {cli_path}")
        return False
        
    temp_pvr_path = Path(input_pvr_path).with_name(f"temp_patched_{uuid.uuid4().hex[:8]}.pvr")

    try:
        with open(input_pvr_path, "rb") as f:
            data = bytearray(f.read())
        
        with open(temp_pvr_path, "wb") as f:
            f.write(data)

        command = [str(cli_path), "-i", str(temp_pvr_path), "-ics", "sRGB", "-noout", "-d", str(output_png_path)]
        print(f"-> Executing PVRTexToolCLI conversion...")
        subprocess.run(command, capture_output=True, text=True, check=True)
        print(f"-> Successfully converted texture atlas to PNG.")
        
        if temp_pvr_path.exists():
            os.remove(temp_pvr_path)
            
        return True

    except subprocess.CalledProcessError as e:
        print(f"[ERROR] Atlas Conversion failed. CLI Output:\n{e.stderr}")
        if temp_pvr_path.exists(): os.remove(temp_pvr_path)
        return False
    except Exception as e:
        print(f"[ERROR] Processing failed: {e}")
        if temp_pvr_path.exists(): os.remove(temp_pvr_path)
        return False

# ==========================================
# 4. Atlas Slicer
# ==========================================
def clean_sprite_dust(image):
    if image.mode != 'RGBA':
        image = image.convert('RGBA')
    pixels = image.load()
    width, height = image.size
    for y in range(height):
        for x in range(width):
            if pixels[x, y][3] < 15:
                pixels[x, y] = (0, 0, 0, 0)
    return image

def slice_texture_atlas(json_data, image_path, output_dir, clean_dust=False):
    print(f"-> Loading atlas image: {Path(image_path).name}")
    try:
        atlas_image = Image.open(image_path).convert("RGBA")
    except Exception as e:
        print(f"[ERROR] Failed to load atlas image: {e}")
        return False

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    total_sprites = len(json_data.get("sprites", []))
    success_count = 0
    
    print(f"-> Slicing {total_sprites} sprites...")
    for sprite in json_data.get("sprites", []):
        try:
            name = sprite["name"]
            left = int(round(float(sprite["atlasU1"])))
            top = int(round(float(sprite["atlasV1"])))
            right = left + int(round(float(sprite["atlasU2"])))
            bottom = top + int(round(float(sprite["atlasV2"])))
            box = (left, top, right, bottom)

            if box[2] <= box[0] or box[3] <= box[1]:
                continue

            cropped_sprite = atlas_image.crop(box)
            if clean_dust:
                cropped_sprite = clean_sprite_dust(cropped_sprite)

            clean_sprite = Image.new("RGBA", cropped_sprite.size)
            clean_sprite.putdata(list(cropped_sprite.get_flattened_data()))
            safe_name = re.sub(r'[^a-zA-Z0-9_\-]', '', name)
            clean_sprite.save(os.path.join(output_dir, f"{safe_name}.png"), "PNG")
            success_count += 1
        except Exception as e:
            print(f"-> [WARNING] Failed to extract sprite '{name}': {e}")
            
    print(f"-> Successfully extracted {success_count}/{total_sprites} sprites.")
    return True

def gen_id():
    u = uuid.uuid4().hex
    return f"{u[:8]}-{u[8:16]}"

def safe_str(name):
    return re.sub(r'[^a-zA-Z0-9_\-]', '', name)

# ==========================================
# 5. Animation Builder
# ==========================================
def build_timeline_layers(mc_data, scale_factor, is_root_mc, shift_x, shift_y, anim_mc_ids):
    frames = mc_data.get("frames", [])
    if not frames:
        return '        <DOMLayer name="Layer 1" color="#4F80FF">\n          <frames>\n            <DOMFrame index="0" keyMode="9728"><elements/></DOMFrame>\n          </frames>\n        </DOMLayer>'
        
    max_slots = max((len(f.get("elements", [])) for f in frames), default=0)
    if max_slots == 0:
        return f'        <DOMLayer name="Layer 1" color="#4F80FF">\n          <frames>\n            <DOMFrame index="0" duration="{len(frames)}" keyMode="9728"><elements/></DOMFrame>\n          </frames>\n        </DOMLayer>'
        
    layer_xmls = []
    
    for slot in range(max_slots - 1, -1, -1):
        layer_frames_xml = []
        
        current_sig = None
        current_xml_data = None
        start_idx = 0
        duration = 0
        
        def emit_frame(s_idx, dur, sig, xml_data):
            dur_str = f' duration="{dur}"' if dur > 1 else ''
            if sig is None:
                layer_frames_xml.append(f'            <DOMFrame index="{s_idx}"{dur_str} keyMode="9728">\n              <elements/>\n            </DOMFrame>')
            else:
                _, lib_path, a, b, c, d, tx, ty, ca, cr, cg, cb, blend_add, nested_attr = xml_data
                
                mat_attrs = []
                if a != 1.0: mat_attrs.append(f'a="{a}"')
                if b != 0.0: mat_attrs.append(f'b="{b}"')
                if c != 0.0: mat_attrs.append(f'c="{c}"')
                if d != 1.0: mat_attrs.append(f'd="{d}"')
                if tx != 0.0: mat_attrs.append(f'tx="{tx}"')
                if ty != 0.0: mat_attrs.append(f'ty="{ty}"')
                mat_str = " ".join(mat_attrs)
                mat_xml = f'<matrix><Matrix {mat_str}/></matrix>' if mat_str else ""
                
                color_xml = ""
                if ca < 255 or cr < 255 or cg < 255 or cb < 255:
                    color_xml = f'\n                  <color>\n                    <Color alphaMultiplier="{round(ca/255.0, 3)}" redMultiplier="{round(cr/255.0, 3)}" greenMultiplier="{round(cg/255.0, 3)}" blueMultiplier="{round(cb/255.0, 3)}"/>\n                  </color>'

                blend_xml = '\n                  <blendMode>add</blendMode>' if blend_add else ""
                
                elem_str = f'<DOMSymbolInstance libraryItemName="{lib_path}" symbolType="graphic" loop="loop"{nested_attr}>\n                  {mat_xml}{color_xml}{blend_xml}\n                </DOMSymbolInstance>'
                
                layer_frames_xml.append(f'            <DOMFrame index="{s_idx}"{dur_str} keyMode="9728">\n              <elements>\n                {elem_str}\n              </elements>\n            </DOMFrame>')

        for f_idx in range(len(frames)):
            el_list = frames[f_idx].get("elements", [])
            
            if slot >= len(el_list):
                sig = None
                xml_data = None
            else:
                el = el_list[slot]
                sym_name, item_type = safe_str(el["symbol_name"]), el["type"]
                sym_id = el["symbol_id"]
                
                if sym_name == "UNKNOWN" or item_type not in ["img", "mc"]:
                    lib_path = "sprite/EmptyAnchor"
                elif item_type == "img":
                    lib_path = f"image/{sym_name}"
                else:
                    is_el_label = sym_id in anim_mc_ids
                    lib_path = f"label/{sym_name}" if is_el_label else f"sprite/{sym_name}"
                
                t = el["transform"]
                a = round(float(t["a"]), 6)
                b = round(-float(t["b"]), 6)
                c = round(-float(t["c"]), 6)
                d = round(float(t["d"]), 6)
                tx = round(float(t["tx"]) * scale_factor, 4)
                ty = round(-float(t["ty"]) * scale_factor, 4)
                
                if is_root_mc:
                    tx = round(tx + shift_x, 4)
                    ty = round(ty + shift_y, 4)
                    
                c_tint = el.get("color_tint", {})
                ca = c_tint.get("a", 255)
                cr = c_tint.get("r", 255)
                cg = c_tint.get("g", 255)
                cb = c_tint.get("b", 255)
                
                blend_add = el.get("blend_additive", False)
                nested_attr = f' firstFrame="{el.get("nested_frame")}"' if item_type == "mc" and el.get("nested_frame", -1) not in [-1, 65535] else ""
                
                sig = (lib_path, a, b, c, d, tx, ty, ca, cr, cg, cb, blend_add, nested_attr)
                xml_data = (sig, lib_path, a, b, c, d, tx, ty, ca, cr, cg, cb, blend_add, nested_attr)
            
            if f_idx == 0:
                current_sig = sig
                current_xml_data = xml_data
                start_idx = 0
                duration = 1
            else:
                if sig == current_sig:
                    duration += 1
                else:
                    emit_frame(start_idx, duration, current_sig, current_xml_data)
                    current_sig = sig
                    current_xml_data = xml_data
                    start_idx = f_idx
                    duration = 1
        
        if duration > 0:
            emit_frame(start_idx, duration, current_sig, current_xml_data)
            
        layer_name = f"Layer {slot + 1}"
        
        is_completely_empty = (current_sig is None and start_idx == 0)
        if not is_completely_empty:
            layer_xmls.append(f'        <DOMLayer name="{layer_name}" color="#4F80FF">\n          <frames>\n{"".join(layer_frames_xml)}\n          </frames>\n        </DOMLayer>')

    if not layer_xmls:
        return f'        <DOMLayer name="Layer 1" color="#4F80FF">\n          <frames>\n            <DOMFrame index="0" duration="{len(frames)}" keyMode="9728"><elements/></DOMFrame>\n          </frames>\n        </DOMLayer>'
        
    return "\n".join(layer_xmls)

# ==========================================
# 6. XFL Generator
# ==========================================
def generate_xfl(json_data, png_folder, output_dir, scale_factor=1.0):
    print(f"-> Initializing XFL directory structure at {Path(output_dir).name}...")
    lib_dir = os.path.join(output_dir, "library")
    image_dir = os.path.join(lib_dir, "image")
    media_dir = os.path.join(lib_dir, "media")
    sprite_dir = os.path.join(lib_dir, "sprite")
    label_dir = os.path.join(lib_dir, "label")
    
    if os.path.exists(output_dir):
        shutil.rmtree(output_dir)
    os.makedirs(image_dir)
    os.makedirs(media_dir)
    os.makedirs(sprite_dir)
    os.makedirs(label_dir)

    # -------------------------------------------------------------
    # STAGE CENTERING CALCULATION
    # -------------------------------------------------------------
    print("-> Calculating optimal stage centering...")
    movieclips = json_data.get("mc_frames", [])
    actions = json_data.get("actions", [])
    sprites = json_data.get("sprites", [])
    anim_mc_ids = set(act["ref_movieclip_id"] for act in actions)
    
    shift_x = 195.0
    shift_y = 195.0
    
    sorted_actions = sorted(actions, key=lambda x: x["start_frame"])
    
    if sorted_actions:
        first_act = sorted_actions[0]
        probe_mc = first_act["ref_movieclip_id"]
        probe_frame = (first_act["start_frame"] + first_act["end_frame"]) // 2
        
        bounds = extract_physical_bounds(probe_mc, probe_frame, sprites, movieclips, scale_factor)
        if bounds:
            shift_x = 195.0 - (bounds[0] + bounds[2]) * 0.5
            shift_y = 195.0 - (bounds[1] + bounds[3]) * 0.5
            shift_x = round(shift_x, 2)
            shift_y = round(shift_y, 2)
    elif movieclips:
        probe_mc = movieclips[-1]["movieclip_id"]
        bounds = extract_physical_bounds(probe_mc, 0, sprites, movieclips, scale_factor)
        if bounds:
            shift_x = 195.0 - (bounds[0] + bounds[2]) * 0.5
            shift_y = 195.0 - (bounds[1] + bounds[3]) * 0.5
            shift_x = round(shift_x, 2)
            shift_y = round(shift_y, 2)

    with open(os.path.join(output_dir, "main.xfl"), "w", encoding="utf-8") as f:
        f.write("PROXY-CS5")

    include_tags, media_tags = [], []
    anchor_id = gen_id()
    include_tags.append(f'          <Include href="sprite/EmptyAnchor.xml" loadImmediate="false" itemID="{anchor_id}" />')
    
    anchor_xml = f"""<DOMSymbolItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" name="sprite/EmptyAnchor" itemID="{anchor_id}" symbolType="graphic">\n  <timeline>\n    <DOMTimeline name="EmptyAnchor">\n      <layers>\n        <DOMLayer name="Layer 1" color="#4F80FF">\n          <frames>\n            <DOMFrame index="0" keyMode="9728"><elements/></DOMFrame>\n          </frames>\n        </DOMLayer>\n      </layers>\n    </DOMTimeline>\n  </timeline>\n</DOMSymbolItem>"""
    with open(os.path.join(sprite_dir, "EmptyAnchor.xml"), "w", encoding="utf-8") as f:
        f.write(anchor_xml)

    print(f"-> Generating XML for {len(sprites)} image definitions...")
    for sprite in sprites:
        s_name = safe_str(sprite["name"])
        s_x = float(sprite["x"]) * scale_factor
        s_y = float(sprite["y"]) * scale_factor 
        sprite_id, bitmap_id = gen_id(), gen_id()
        
        src_png = os.path.join(png_folder, f"{s_name}.png")
        if os.path.exists(src_png):
            shutil.copy(src_png, os.path.join(media_dir, f"{s_name}.png"))

        media_tags.append(f'          <DOMBitmapItem name="media/{s_name}.png" itemID="{bitmap_id}" sourceExternalFilepath="./library/media/{s_name}.png" sourceLastImported="1" allowSmoothing="true" useImportedJPEGData="false" href="media/{s_name}.png" />')
        include_tags.append(f'          <Include href="image/{s_name}.xml" itemIcon="1" loadImmediate="false" itemID="{sprite_id}" />')

        sprite_xml = f"""<DOMSymbolItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" name="image/{s_name}" itemID="{sprite_id}" symbolType="graphic">\n  <timeline>\n    <DOMTimeline name="{s_name}">\n      <layers>\n        <DOMLayer name="Layer 1" color="#4F80FF" current="true" isSelected="true">\n          <frames>\n            <DOMFrame index="0" keyMode="9728">\n              <elements>\n                <DOMBitmapInstance selected="true" libraryItemName="media/{s_name}.png">\n                  <matrix>\n                    <Matrix tx="{s_x}" ty="{s_y}"/>\n                  </matrix>\n                </DOMBitmapInstance>\n              </elements>\n            </DOMFrame>\n          </frames>\n        </DOMLayer>\n      </layers>\n    </DOMTimeline>\n  </timeline>\n</DOMSymbolItem>"""
        with open(os.path.join(image_dir, f"{s_name}.xml"), "w", encoding="utf-8") as f:
            f.write(sprite_xml)


    print(f"-> Generating XML for {len(movieclips)} shape/animation timelines...")
    for mc_data in movieclips:
        mc_name = safe_str(mc_data["movieclip_name"])
        mc_id_num = mc_data["movieclip_id"]
        
        if sorted_actions:
            is_root_mc = mc_id_num in anim_mc_ids
        else:
            is_root_mc = (mc_data == movieclips[-1])
            
        is_label = mc_id_num in anim_mc_ids
        
        mc_id = gen_id()
        folder_name = "label" if is_label else "sprite"
        out_dir = label_dir if is_label else sprite_dir
        
        include_tags.append(f'          <Include href="{folder_name}/{mc_name}.xml" loadImmediate="false" itemID="{mc_id}" />')

        layers_xml = build_timeline_layers(mc_data, scale_factor, is_root_mc, shift_x, shift_y, anim_mc_ids)

        with open(os.path.join(out_dir, f"{mc_name}.xml"), "w", encoding="utf-8") as f:
            f.write(f"""<DOMSymbolItem xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" name="{folder_name}/{mc_name}" itemID="{mc_id}" symbolType="graphic">\n  <timeline>\n    <DOMTimeline name="{mc_name}">\n      <layers>\n{layers_xml}\n      </layers>\n    </DOMTimeline>\n  </timeline>\n</DOMSymbolItem>""")

    # -------------------------------------------------------------
    # ROOT TIMELINE COMPILATION (SCENE 1)
    # -------------------------------------------------------------
    print("-> Compiling structural layers to root DOMDocument.xml...")
    label_frames = []
    action_frames = []
    instance_frames = []

    if sorted_actions:
        current_frame = 0
        for act in sorted_actions:
            start = act["start_frame"]
            end = act["end_frame"]
            
            if start > current_frame:
                gap_dur = start - current_frame
                label_frames.append(f'<DOMFrame index="{current_frame}" duration="{gap_dur}" keyMode="9728"><elements/></DOMFrame>')
                action_frames.append(f'<DOMFrame index="{current_frame}" duration="{gap_dur}" keyMode="9728"><elements/></DOMFrame>')
                instance_frames.append(f'<DOMFrame index="{current_frame}" duration="{gap_dur}" keyMode="9728"><elements/></DOMFrame>')
            
            duration = end - start + 1
            if duration <= 0: continue
            
            name = safe_str(act["name"])
            ref_id = act["ref_movieclip_id"]
            
            mc_name = "UNKNOWN"
            for mc in movieclips:
                if mc["movieclip_id"] == ref_id:
                    mc_name = safe_str(mc["movieclip_name"])
                    break
                    
            label_frames.append(f'<DOMFrame index="{start}" duration="{duration}" name="{name}" labelType="name" keyMode="9728"><elements/></DOMFrame>')
            
            if duration > 1:
                action_frames.append(f'<DOMFrame index="{start}" duration="{duration - 1}" keyMode="9728"><elements/></DOMFrame>')
            action_frames.append(f'<DOMFrame index="{end}" keyMode="9728"><Actionscript><script><![CDATA[stop();]]></script></Actionscript><elements/></DOMFrame>')
            
            instance_frames.append(f'<DOMFrame index="{start}" duration="{duration}" keyMode="9728"><elements><DOMSymbolInstance libraryItemName="label/{mc_name}" symbolType="graphic" loop="loop"/></elements></DOMFrame>')
            
            current_frame = end + 1
    else:
        if movieclips:
            last_mc = movieclips[-1]
            mc_name = safe_str(last_mc["movieclip_name"])
            duration = last_mc["total_frames"] if last_mc["total_frames"] > 0 else 1
            
            label_frames.append(f'<DOMFrame index="0" duration="{duration}" name="animation" labelType="name" keyMode="9728"><elements/></DOMFrame>')
            if duration > 1:
                action_frames.append(f'<DOMFrame index="0" duration="{duration - 1}" keyMode="9728"><elements/></DOMFrame>')
            action_frames.append(f'<DOMFrame index="{duration - 1}" keyMode="9728"><Actionscript><script><![CDATA[stop();]]></script></Actionscript><elements/></DOMFrame>')
            
            instance_frames.append(f'<DOMFrame index="0" duration="{duration}" keyMode="9728"><elements><DOMSymbolInstance libraryItemName="sprite/{mc_name}" symbolType="graphic" loop="loop"/></elements></DOMFrame>')
        else:
            label_frames.append('<DOMFrame index="0" keyMode="9728"><elements/></DOMFrame>')
            action_frames.append('<DOMFrame index="0" keyMode="9728"><elements/></DOMFrame>')
            instance_frames.append('<DOMFrame index="0" keyMode="9728"><elements/></DOMFrame>')

    folder_tags = f"""
          <DOMFolderItem name="image" itemID="{gen_id()}"/>
          <DOMFolderItem name="label" itemID="{gen_id()}" isExpanded="true"/>
          <DOMFolderItem name="media" itemID="{gen_id()}"/>
          <DOMFolderItem name="sprite" itemID="{gen_id()}" isExpanded="true"/>"""

    scene_layers = f"""
                    <DOMLayer name="label" color="#4F4FFF" current="true" isSelected="true">
                         <frames>
                              {"".join(label_frames)}
                         </frames>
                    </DOMLayer>
                    <DOMLayer name="action" color="#4F4FFF">
                         <frames>
                              {"".join(action_frames)}
                         </frames>
                    </DOMLayer>
                    <DOMLayer name="instance" color="#4F4FFF">
                         <frames>
                              {"".join(instance_frames)}
                         </frames>
                    </DOMLayer>"""

    with open(os.path.join(output_dir, "DOMDocument.xml"), "w", encoding="utf-8") as f:
        f.write(f"""<DOMDocument xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns="http://ns.adobe.com/xfl/2008/" backgroundColor="#999999" gridColor="#FFFFFF" width="390" height="390" frameRate="30" currentTimeline="1" xflVersion="2.6" creatorInfo="Automated Generator" platform="Windows" versionInfo="Saved by Generator" majorVersion="15" buildNumber="173" gridSpacingX="130" gridSpacingY="130" gridVisible="true" vanishingPoint3DX="195" vanishingPoint3DY="195" playOptionsPlayLoop="false" playOptionsPlayPages="false" playOptionsPlayFrameActions="false" filetypeGUID="DD0DDBBF-5BEF-45B2-9F24-A3048D2A676F">\n     <folders>{folder_tags}\n     </folders>\n     <media>\n{"\n".join(media_tags)}\n     </media>\n     <symbols>\n{"\n".join(include_tags)}\n     </symbols>\n     <timelines>\n          <DOMTimeline name="Scene 1">\n               <layers>{scene_layers}\n               </layers>\n          </DOMTimeline>\n     </timelines>\n     <PrinterSettings/>\n     <publishHistory/>\n</DOMDocument>""")
    print("-> XFL project generation complete.")

# ==========================================
# 7. Master Pipeline Coordinator
# ==========================================
def main():
    if len(sys.argv) < 3:
        print("Usage: python script.py <input.bin> <input_atlas_file> [optional_scale] [--clean-dust]")
        sys.exit(1)

    bin_path = Path(sys.argv[1]).resolve()
    atlas_input_path = Path(sys.argv[2]).resolve()

    if not bin_path.exists():
        print(f"[ERROR] Input BIN file not found: {bin_path}")
        sys.exit(1)
    if not atlas_input_path.exists():
        print(f"[ERROR] Input Atlas file not found: {atlas_input_path}")
        sys.exit(1)

    base_name = bin_path.stem
    work_dir = bin_path.parent
    
    temp_pvr_file = work_dir / f"{base_name}_temp_input.pvr"
    temp_png_file = work_dir / f"{base_name}_temp_converted.png"

    json_file = work_dir / f"{base_name}.json"
    temp_sprites_dir = work_dir / f"{base_name}_temp_sprites"
    output_xfl_dir = work_dir / f"{base_name}_XFL"

    print(f"--- Starting Pipeline for {base_name} ---")

    is_png = is_valid_png(atlas_input_path)

    if is_png:
        print("\n[1/5] Input is already a valid PNG. Skipping conversion...")
        working_png_file = atlas_input_path
    else:
        print("\n[1/5] Converting Texture Atlas to PNG...")
        working_png_file = temp_png_file
        shutil.copy(atlas_input_path, temp_pvr_file)

        if not convert_pvr_to_png(temp_pvr_file, working_png_file):
            print("[ERROR] Failed to convert input texture atlas.")
            if temp_pvr_file.exists(): os.remove(temp_pvr_file)
            sys.exit(1)

        if temp_pvr_file.exists():
            os.remove(temp_pvr_file)

    print("\n[2/5] Parsing Binary to JSON...")
    try:
        with open(bin_path, "rb") as f:
            binary_data = f.read()
        parser = FlashBinParser(binary_data)
        parsed_json = parser.parse()
    except Exception as e:
        print(f"[ERROR] Failed to parse binary file: {e}")
        sys.exit(1)

    raw_scale = getattr(parser, 'header_float', 1.0)
    scale_factor = 1.0
    clean_dust = False
    
    for arg in sys.argv[3:]:
        if arg.lower() in ['--clean-dust', '-c', 'true']:
            clean_dust = True
            print("-> Notice: PVRTC dust cleaning is enabled.")
        else:
            try:
                scale_factor = float(arg)
                print(f"-> Notice: Manual scale factor applied: {scale_factor}x")
            except ValueError:
                pass

    if scale_factor == 1.0 and raw_scale > 0 and abs(raw_scale - 1.0) > 0.001:
        scale_factor = raw_scale
        print(f"-> Notice: Automatically applying internal engine scale: {scale_factor}x")

    try:
        with open(json_file, "w") as f:
            json.dump(parsed_json, f, indent=4)
        print("-> Intermediary JSON data saved.")
    except Exception as e:
        print(f"-> [WARNING] Failed to write intermediary JSON data: {e}")

    print("\n[3/5] Slicing Texture Atlas...")
    if not slice_texture_atlas(parsed_json, working_png_file, temp_sprites_dir, clean_dust):
        print("[ERROR] Failed to slice texture atlas.")
        sys.exit(1)

    print("\n[4/5] Building XFL Project Folder...")
    generate_xfl(parsed_json, temp_sprites_dir, output_xfl_dir, scale_factor)

    print("\n[5/5] Cleaning up temporary files...")
    try:
        if not is_png and working_png_file.exists(): 
            os.remove(working_png_file)
            print("-> Removed temporary converted PNG.")
        if json_file.exists(): 
            os.remove(json_file)
            print("-> Removed intermediary JSON file.")
        if temp_sprites_dir.exists(): 
            shutil.rmtree(temp_sprites_dir)
            print("-> Removed temporary sprite slices folder.")
    except Exception as e:
        print(f" Warning: Cleanup encountered an issue: {e}")

    print(f"\n Pipeline Complete! XFL Project is ready at: {output_xfl_dir}")

if __name__ == "__main__":
    main()