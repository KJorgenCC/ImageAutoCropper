import bpy
import bmesh
import os
from PIL import Image

class ExportUVInfoOperator(bpy.types.Operator):
    bl_idname = "uv.export_uv_info"
    bl_label = "Export UV Info"
    bl_options = {'REGISTER', 'UNDO'}

    directory: bpy.props.StringProperty(
        name="Output Directory",
        description="Choose directory to export UV data",
        subtype='DIR_PATH'
    )

    crop_images: bpy.props.BoolProperty(
        name="Crop",
        description="Crop images based on UV bounds",
        default=False
    )

    remap_model: bpy.props.BoolProperty(
        name="Remap with Cropped Images",
        description="Assign cropped textures to faces",
        default=False
    )

    def execute(self, context):
        obj = context.object
        if not obj or obj.type != 'MESH':
            self.report({'WARNING'}, "Selecciona un mesh en modo Edición.")
            return {'CANCELLED'}

        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.active
        if not uv_layer:
            self.report({'WARNING'}, "No se encontraron UVs.")
            return {'CANCELLED'}

        base = self.directory
        coord_file = os.path.join(base, "uv_coordinates.txt")
        name_file = os.path.join(base, "image_names.txt")
        crop_file = os.path.join(base, "image_names_to_crop.txt")
        size_file = os.path.join(base, "image_sizes.txt")

        coord_data = []
        name_data = []
        crop_data = []
        unique = {}
        dimensions = {}
        count = {}
        bounds_per_image = {}
        face_assignments = []

        for face in bm.faces:
            image = self.get_image_from_face(face)
            if not image:
                continue
            name = bpy.path.basename(image.filepath)
            path = bpy.path.abspath(image.filepath)
            w, h = image.size
            uvs = [(loop[uv_layer].uv.x * w, loop[uv_layer].uv.y * h) for loop in face.loops]
            xs, ys = zip(*uvs)
            xmin, xmax = min(xs), max(xs)
            ymin, ymax = min(ys), max(ys)
            xmin, ymin, xmax, ymax = self.convert_coords((xmin, ymin, xmax, ymax), h)
            bounds = tuple(map(int, (xmin, ymin, xmax, ymax)))

            if bounds not in unique.setdefault(name, []):
                unique[name].append(bounds)
            variant = unique[name].index(bounds) + 1

            name_data.append(f'"{name}_variant{variant}",')
            crop_data.append(f'"{name}",')
            coord_data.append(f"{bounds},    # coords for '{name}_variant{variant}'")

            dimensions.setdefault(name, (w, h))
            count[name] = count.get(name, 0) + 1
            bounds_per_image.setdefault(name, []).append((bounds, path, variant))

            face_assignments.append((face.index, name, variant, bounds))

        with open(coord_file, "w") as f: f.write("\n".join(coord_data))
        with open(name_file, "w") as f: f.write("\n".join(name_data))
        with open(crop_file, "w") as f: f.write("\n".join(crop_data))
        with open(size_file, "w") as f:
            for name, (w, h) in dimensions.items():
                for _ in range(count[name]):
                    f.write(f'("{name}", {w}, {h}),\n')

        image_map = {}

        # Crop images if needed
        if self.crop_images:
            for name, bounds_list in bounds_per_image.items():
                for (xmin, ymin, xmax, ymax), path, variant in bounds_list:
                    if not os.path.exists(path):
                        self.report({'WARNING'}, f"No se encontró la imagen: {path}")
                        continue
                    try:
                        with Image.open(path) as im:
                            cropped = im.crop((xmin, ymin, xmax, ymax))
                            new_name = f"{name}_variant{variant}.png"
                            save_path = os.path.join(self.directory, new_name)
                            cropped.save(save_path)
                            image_map[(name, variant)] = (save_path, new_name)
                    except Exception as e:
                        self.report({'WARNING'}, f"Error al recortar {name}: {e}")

        # Remap materials and fill UVs
        if self.remap_model and self.crop_images:
            mat_lookup = {}

            for (face_idx, orig_name, variant, bounds) in face_assignments:
                image_path, image_filename = image_map.get((orig_name, variant), (None, None))
                if not image_path:
                    continue

                image = bpy.data.images.load(image_path, check_existing=True)
                mat_key = f"{orig_name}_variant{variant}"
                if mat_key not in mat_lookup:
                    mat = bpy.data.materials.new(name=mat_key)
                    mat.use_nodes = True
                    bsdf = mat.node_tree.nodes.get("Principled BSDF")
                    tex_node = mat.node_tree.nodes.new("ShaderNodeTexImage")
                    tex_node.image = image
                    mat.node_tree.links.new(bsdf.inputs['Base Color'], tex_node.outputs['Color'])
                    obj.data.materials.append(mat)
                    mat_lookup[mat_key] = len(obj.data.materials) - 1
                mat_index = mat_lookup[mat_key]

                face = bm.faces[face_idx]
                face.material_index = mat_index

                # ---- UV FILL ----
                uvs = [loop[uv_layer].uv for loop in face.loops]
                min_u = min(uv[0] for uv in uvs)
                max_u = max(uv[0] for uv in uvs)
                min_v = min(uv[1] for uv in uvs)
                max_v = max(uv[1] for uv in uvs)
                width = max_u - min_u
                height = max_v - min_v
                if width > 0 and height > 0:
                    for uv in uvs:
                        uv[0] = (uv[0] - min_u) / width
                        uv[1] = (uv[1] - min_v) / height

        bmesh.update_edit_mesh(obj.data)
        self.report({'INFO'}, f"Exportación, remapeo y ajuste UV completados en {self.directory}")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def convert_coords(self, coords, h):
        xmin, ymin, xmax, ymax = coords
        return xmin, h - ymax, xmax, h - ymin

    def get_image_from_face(self, face):
        for loop in face.loops:
            idx = loop.face.material_index
            mats = bpy.context.object.data.materials
            if idx < len(mats):
                mat = mats[idx]
                if mat and mat.use_nodes:
                    for node in mat.node_tree.nodes:
                        if node.type == 'TEX_IMAGE' and node.image:
                            return node.image
        return None

def menu_func(self, context):
    self.layout.operator(ExportUVInfoOperator.bl_idname, icon='EXPORT')

def register():
    bpy.utils.register_class(ExportUVInfoOperator)
    bpy.types.IMAGE_MT_uvs.append(menu_func)

def unregister():
    bpy.utils.unregister_class(ExportUVInfoOperator)
    bpy.types.IMAGE_MT_uvs.remove(menu_func)

if __name__ == "__main__":
    register()
