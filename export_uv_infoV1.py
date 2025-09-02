import bpy
import bmesh
import os
from PIL import Image
from concurrent.futures import ThreadPoolExecutor

class ExportUVInfoOperator(bpy.types.Operator):
    """
    ExportUVInfoOperator
    --------------------
    Exports UV layout information and optionally crops and remaps textures for selected meshes.

    Properties:
        directory (StringProperty): Output directory for UV data and images.
        crop_images (BoolProperty): Crop individual face images.
        crop_per_border (BoolProperty): Crop one image per UV island (connected faces).
        remap_model (BoolProperty): Assign cropped textures back onto mesh faces.
    """
    bl_idname = "uv.export_uv_info"
    bl_label = "Export UV Info (Global Files)"
    bl_options = {'REGISTER', 'UNDO'}

    directory: bpy.props.StringProperty(
        name="Output Directory",
        description="Directory where UV data and images will be saved",
        subtype='DIR_PATH'
    )
    crop_images: bpy.props.BoolProperty(
        name="Crop per Face",
        description="Crop an image for each UV face based on bounds",
        default=False
    )
    crop_per_border: bpy.props.BoolProperty(
        name="Crop per Island",
        description="Crop one image per UV island instead of per face",
        default=False
    )
    remap_model: bpy.props.BoolProperty(
        name="Remap Textures",
        description="Assign cropped textures back to mesh faces",
        default=False
    )

    def execute(self, context):
        # Collect selected mesh objects
        objs = [o for o in context.selected_objects if o.type == 'MESH']
        if not objs:
            self.report({'WARNING'}, "Select at least one mesh.")
            return {'CANCELLED'}

        global_variants = {}
        global_sizes = {}
        face_map = {}

        # Gather UV bounds and image references
        for obj in objs:
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = bm.loops.layers.uv.active
            if not uv_layer:
                self.report({'WARNING'}, f"No UVs found on {obj.name}.")
                bpy.ops.object.mode_set(mode='OBJECT')
                continue
            bm.faces.ensure_lookup_table()

            assignments = []
            if self.crop_per_border:
                # Crop per UV island
                visited = set()
                for face in bm.faces:
                    if face.index in visited:
                        continue
                    stack, group = [face], []
                    while stack:
                        f = stack.pop()
                        if f.index in visited:
                            continue
                        visited.add(f.index)
                        group.append(f)
                        for e in f.edges:
                            for lf in e.link_faces:
                                if lf.index not in visited:
                                    stack.append(lf)
                    coords, img = [], None
                    for f2 in group:
                        for loop in f2.loops:
                            uv = loop[uv_layer].uv
                            im = self.get_image_from_face(f2)
                            if im:
                                img = im
                                w, h = im.size
                                global_sizes[im.name] = (w, h)
                                coords.append((uv.x * w, uv.y * h))
                    if not coords or not img:
                        continue
                    xs, ys = zip(*coords)
                    xmin, xmax = int(min(xs)), int(max(xs))
                    ymin, ymax = int(min(ys)), int(max(ys))
                    bounds = (xmin, h - ymax, xmax, h - ymin)
                    path = bpy.path.abspath(img.filepath)
                    global_variants.setdefault(img.name, []).append((bounds, path, None))
                    for f2 in group:
                        assignments.append((f2.index, img.name, bounds))
            else:
                # Crop per face
                for face in bm.faces:
                    img = self.get_image_from_face(face)
                    if not img:
                        continue
                    w, h = img.size
                    global_sizes[img.name] = (w, h)
                    uvs_px = [(loop[uv_layer].uv.x * w, loop[uv_layer].uv.y * h) for loop in face.loops]
                    xs, ys = zip(*uvs_px)
                    xmin, xmax = int(min(xs)), int(max(xs))
                    ymin, ymax = int(min(ys)), int(max(ys))
                    bounds = (xmin, h - ymax, xmax, h - ymin)
                    path = bpy.path.abspath(img.filepath)
                    global_variants.setdefault(img.name, []).append((bounds, path, None))
                    assignments.append((face.index, img.name, bounds))

            bmesh.update_edit_mesh(obj.data)
            bpy.ops.object.mode_set(mode='OBJECT')
            face_map[obj.name] = assignments

        # Deduplicate UV variants
        for name, lst in global_variants.items():
            unique = []
            seen = {}
            for bounds, path, _ in lst:
                if bounds not in seen:
                    seen[bounds] = len(unique) + 1
                    unique.append((bounds, path, seen[bounds]))
            global_variants[name] = unique

        os.makedirs(self.directory, exist_ok=True)

        # Crop tasks
        image_map = {}
        crop_bounds = {}
        if self.crop_images or self.crop_per_border:
            tasks = [
                (name, path, variant_id, bounds)
                for name, variants in global_variants.items()
                for bounds, path, variant_id in variants
            ]
            def crop_task(args):
                name, src_path, vid, bounds = args
                if not os.path.exists(src_path):
                    return None
                try:
                    with Image.open(src_path) as im:
                        w, h = im.size
                        x0, y0, x1, y1 = bounds
                        x0 = max(0, min(x0, w - 1))
                        y0 = max(0, min(y0, h - 1))
                        x1 = max(x0 + 1, min(x1, w))
                        y1 = max(y0 + 1, min(y1, h))
                        if x1 <= x0 or y1 <= y0:
                            return None
                        cropped = im.crop((x0, y0, x1, y1))
                        filename = f"{name}_variant{vid}.png"
                        out_path = os.path.join(self.directory, filename)
                        cropped.save(out_path)
                        return (name, vid, out_path, (x0, y0, x1, y1))
                except:
                    return None

            with ThreadPoolExecutor(max_workers=4) as executor:
                for result in executor.map(crop_task, tasks):
                    if result:
                        name, vid, out_path, bnds = result
                        image_map[(name, vid)] = out_path
                        crop_bounds[(name, vid)] = bnds

        # Remap textures, fill UVs, separate by material, and rejoin
        for obj in objs:
            assignments = face_map.get(obj.name, [])
            if self.remap_model and image_map:
                mats = {}
                for (name, vid), img_path in image_map.items():
                    mat_name = f"{name}_variant{vid}"
                    img = bpy.data.images.load(img_path, check_existing=True)
                    mat = bpy.data.materials.get(mat_name) or bpy.data.materials.new(mat_name)
                    mat.use_nodes = True
                    bsdf = mat.node_tree.nodes.get('Principled BSDF')
                    tex_node = mat.node_tree.nodes.new('ShaderNodeTexImage')
                    tex_node.image = img
                    mat.node_tree.links.new(bsdf.inputs['Base Color'], tex_node.outputs['Color'])
                    mats[mat_name] = mat

                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode='EDIT')
                bm = bmesh.from_edit_mesh(obj.data)
                uv_layer = bm.loops.layers.uv.active
                bm.faces.ensure_lookup_table()

                for mat_name, mat in mats.items():
                    if mat_name not in obj.data.materials:
                        obj.data.materials.append(mat)
                mat_index_map = {name: obj.data.materials.find(name) for name in mats}

                for face_idx, name, bounds in assignments:
                    face = bm.faces[face_idx]
                    vid = next(v for (bnds, _, v) in global_variants[name] if bnds == bounds)
                    mat_name = f"{name}_variant{vid}"
                    face.material_index = mat_index_map[mat_name]
                    uvs = [loop[uv_layer].uv for loop in face.loops]
                    ow, oh = global_sizes[name]
                    if self.crop_per_border and (name, vid) in crop_bounds:
                        x0, y0, x1, y1 = crop_bounds[(name, vid)]
                        cw, ch = x1 - x0, y1 - y0
                        for uv in uvs:
                            px, py = uv.x * ow, uv.y * oh
                            uv.x = (px - x0) / cw
                            uv.y = (py - y0) / ch
                    else:
                        min_u = min(uv.x for uv in uvs)
                        max_u = max(uv.x for uv in uvs)
                        min_v = min(uv.y for uv in uvs)
                        max_v = max(uv.y for uv in uvs)
                        du, dv = max_u - min_u, max_v - min_v
                        if du > 0 and dv > 0:
                            for uv in uvs:
                                uv.x = (uv.x - min_u) / du
                                uv.y = (uv.y - min_v) / dv

                bmesh.update_edit_mesh(obj.data)
                bpy.ops.object.mode_set(mode='OBJECT')

            # Fill UV islands
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.uv.textools_uv_fill()
            bpy.ops.object.mode_set(mode='OBJECT')

            # Separate by material
            bpy.context.view_layer.objects.active = obj
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.separate(type='MATERIAL')
            bpy.ops.object.mode_set(mode='OBJECT')

            # Fill and rejoin separated parts
            separated = bpy.context.selected_objects[:]
            for part in separated:
                bpy.context.view_layer.objects.active = part
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.uv.textools_uv_fill()
                bpy.ops.object.mode_set(mode='OBJECT')
            for o in bpy.context.selected_objects:
                o.select_set(False)
            for part in separated:
                part.select_set(True)
            bpy.context.view_layer.objects.active = separated[0]
            bpy.ops.object.join()

        # Save metadata files
        coords_lines, names_lines, crops_lines = [], [], []
        for name, variants in global_variants.items():
            for bounds, _, vid in variants:
                coords_lines.append(f"{bounds},    # '{name}_variant{vid}'")
                names_lines.append(f'"{name}_variant{vid}",')
                crops_lines.append(f'"{name}",')
        with open(os.path.join(self.directory, "uv_coordinates.txt"), "w") as f:
            f.write("\n".join(coords_lines))
        with open(os.path.join(self.directory, "image_names.txt"), "w") as f:
            f.write("\n".join(names_lines))
        with open(os.path.join(self.directory, "image_names_to_crop.txt"), "w") as f:
            f.write("\n".join(crops_lines))
        with open(os.path.join(self.directory, "image_sizes.txt"), "w") as f:
            for name, (w, h) in global_sizes.items():
                f.write(f'("{name}", {w}, {h}),\n')

        self.report({'INFO'}, "Export complete: UV data, crops, remapping, fills, separation, and join finished.")
        return {'FINISHED'}

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def get_image_from_face(self, face):
        """
        Returns the first linked image from the face's material using nodes.
        """
        for loop in face.loops:
            mat_index = loop.face.material_index
            mats = bpy.context.object.data.materials
            if mat_index < len(mats) and mats[mat_index].use_nodes:
                for node in mats[mat_index].node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image:
                        return node.image
        return None


class UVIslandFillOperator(bpy.types.Operator):
    """
    UVIslandFillOperator
    ---------------------
    Scales UV islands to fill the 0–1 UV space.
    """
    bl_idname = "uv.textools_uv_fill"
    bl_label = "Fill UV Island"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        objs = [o for o in context.selected_editable_objects if o.type == 'MESH']
        if not objs:
            self.report({'ERROR'}, "No mesh objects in edit mode.")
            return {'CANCELLED'}
        for obj in objs:
            bm = bmesh.from_edit_mesh(obj.data)
            uv_layer = bm.loops.layers.uv.active
            if not uv_layer:
                continue
            all_uvs = [loop[uv_layer].uv for f in bm.faces for loop in f.loops]
            if not all_uvs:
                continue
            us = [uv.x for uv in all_uvs]
            vs = [uv.y for uv in all_uvs]
            min_u, max_u = min(us), max(us)
            min_v, max_v = min(vs), max(vs)
            du, dv = max_u - min_u, max_v - min_v
            if du == 0 or dv == 0:
                continue
            for uv in all_uvs:
                uv.x = (uv.x - min_u) / du
                uv.y = (uv.y - min_v) / dv
            bmesh.update_edit_mesh(obj.data)
        return {'FINISHED'}


class ProcessMultipleOperator(bpy.types.Operator):
    """
    ProcessMultipleOperator
    -----------------------
    Batch imports OBJ/FBX files, applies UV export/remap, then exports fixed OBJ with vertex colors.
    """
    bl_idname = "uv.process_multiple_uv"
    bl_label = "Process Multiple"
    bl_options = {'REGISTER', 'UNDO'}

    directory: bpy.props.StringProperty(
        name="Root Folder",
        description="Main folder containing subfolders with .obj/.fbx files",
        subtype='DIR_PATH'
    )
    crop_images: bpy.props.BoolProperty(
        name="Crop per Face",
        default=False
    )
    crop_per_border: bpy.props.BoolProperty(
        name="Crop per Island",
        default=False
    )
    remap_model: bpy.props.BoolProperty(
        name="Remap Textures",
        default=False
    )

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        root = bpy.path.abspath(self.directory)
        if not os.path.isdir(root):
            self.report({'ERROR'}, f"Invalid folder: {root}")
            return {'CANCELLED'}

        for dirpath, _, filenames in os.walk(root):
            for fname in filenames:
                if not fname.lower().endswith(('.obj', '.fbx')):
                    continue
                fullpath = os.path.join(dirpath, fname)

                # Import
                if fname.lower().endswith('.obj'):
                    bpy.ops.wm.obj_import(filepath=fullpath)
                else:
                    bpy.ops.import_scene.fbx(filepath=fullpath)

                imported = [o for o in context.selected_objects if o.type == 'MESH']
                if not imported:
                    continue

                # Select and export UV info
                bpy.context.view_layer.objects.active = imported[0]
                bpy.ops.object.mode_set(mode='EDIT')
                bpy.ops.mesh.select_all(action='SELECT')
                bpy.ops.object.mode_set(mode='OBJECT')
                bpy.ops.uv.export_uv_info(
                    directory=dirpath,
                    crop_images=self.crop_images,
                    crop_per_border=self.crop_per_border,
                    remap_model=self.remap_model
                )

                # Export fixed OBJ with vertex colors
                out_name = os.path.splitext(fname)[0] + "_Fix.obj"
                out_path = os.path.join(dirpath, out_name)
                bpy.ops.wm.obj_export(
                    filepath=out_path,
                    export_selected_objects=True,
                    export_uv=True,
                    export_normals=True,
                    export_materials=True,
                    export_colors=True,
                    forward_axis='NEGATIVE_Z',
                    up_axis='Y',
                    global_scale=1.0,
                    apply_modifiers=True
                )

                # Delete imported and purge orphans
                bpy.ops.object.select_all(action='DESELECT')
                for o in imported:
                    o.select_set(True)
                bpy.ops.object.delete()
                for area in context.screen.areas:
                    if area.type == 'OUTLINER':
                        area.spaces.active.display_mode = 'ORPHAN_DATA'
                bpy.ops.outliner.orphans_purge(do_recursive=True)

        self.report({'INFO'}, "Batch processing complete.")
        return {'FINISHED'}


def menu_func(self, context):
    self.layout.operator(ExportUVInfoOperator.bl_idname, icon='EXPORT')
    self.layout.operator(ProcessMultipleOperator.bl_idname, icon='FILE_FOLDER')


def register():
    bpy.utils.register_class(ExportUVInfoOperator)
    bpy.utils.register_class(UVIslandFillOperator)
    bpy.utils.register_class(ProcessMultipleOperator)
    bpy.types.IMAGE_MT_uvs.append(menu_func)


def unregister():
    bpy.utils.unregister_class(ExportUVInfoOperator)
    bpy.utils.unregister_class(UVIslandFillOperator)
    bpy.utils.unregister_class(ProcessMultipleOperator)
    bpy.types.IMAGE_MT_uvs.remove(menu_func)


if __name__ == '__main__':
    register()
