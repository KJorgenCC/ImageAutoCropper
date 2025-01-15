bl_info = {
    "name": "ExportUVsData",
    "blender": (3, 5, 0),
    "category": "Object",
    "author": "SirUka",
    "version": (1, 0, 0),
    "description": "An addon designed to extract Uv coordinates translating to pixels and automatically cropping textures from a 3d model",
    "warning": "",
    "doc_url": "",
    "tracker_url": "",
    "support": "COMMUNITY",
}

import bpy
import bmesh
import os

class ExportUVInfoOperator(bpy.types.Operator):
    """Export UV coordinates, image name, and image size to separate text files"""
    bl_idname = "uv.export_uv_info"
    bl_label = "Export UV Info"
    
    def execute(self, context):
        obj = context.object
        if obj is None or obj.type != 'MESH':
            self.report({'WARNING'}, "Select a mesh object in Edit mode.")
            return {'CANCELLED'}
        
        bm = bmesh.from_edit_mesh(obj.data)
        uv_layer = bm.loops.layers.uv.active
        if not uv_layer:
            self.report({'WARNING'}, "No valid UVs found.")
            return {'CANCELLED'}
        
        # File paths
        base_path = r"C:\Users\irlan\OneDrive\Escritorio\TESTEONG"
        coord_filepath = os.path.join(base_path, "uv_coordinates.txt")
        name_filepath = os.path.join(base_path, "image_names.txt")
        name_to_crop_filepath = os.path.join(base_path, "image_names_to_crop.txt")
        size_filepath = os.path.join(base_path, "image_sizes.txt")

        # Data containers
        coord_data = []
        name_data = []
        name_to_crop_data = []
        size_data = []

        # Store unique coordinates and names for cropping and output
        unique_coords = {}  # To store unique coordinates for each image
        image_dimensions = {}  # To store image name and dimensions (width, height)
        image_coord_count = {}  # Track how many coords for each image

        # Iterate over all faces to collect UV info
        for face in bm.faces:
            uv_coords = [loop[uv_layer].uv for loop in face.loops]
            uv_pixel_coords = [(uv.x * context.space_data.image.size[0], uv.y * context.space_data.image.size[1]) for uv in uv_coords]

            # Calculate the crop bounds (xmin, ymin, xmax, ymax)
            uv_x_coords = [uv[0] for uv in uv_pixel_coords]
            uv_y_coords = [uv[1] for uv in uv_pixel_coords]
            
            xmin, xmax = min(uv_x_coords), max(uv_x_coords)
            ymin, ymax = min(uv_y_coords), max(uv_y_coords)

            # Adjust Y-axis to match Blender's coordinate system
            xmin, ymin, xmax, ymax = self.convert_coords((xmin, ymin, xmax, ymax), context.space_data.image.size[1])

            bounds = (int(xmin), int(ymin), int(xmax), int(ymax))

            # Get the image associated with the face's material (first texture)
            image = self.get_image_from_face(face)
            if image:
                image_name = bpy.path.basename(image.filepath)
                image_height = image.size[1]
                image_width = image.size[0]
                
                # Save image dimensions
                if image_name not in image_dimensions:
                    image_dimensions[image_name] = (image_width, image_height)
            else:
                image_name = "No image"
                image_width = 0
                image_height = 0

            # Store coordinates and manage duplicates
            if image_name not in unique_coords:
                unique_coords[image_name] = []

            # Check if this set of bounds is unique for the image
            if bounds not in unique_coords[image_name]:
                unique_coords[image_name].append(bounds)
                name_data.append(f'"{image_name}_variant{len(unique_coords[image_name])}",')  # Add variant name for image
                name_to_crop_data.append(f'"{image_name}",')  # Add the real image name for cropping
                coord_data.append(f"{bounds},    # Coordinates for '{image_name}_variant{len(unique_coords[image_name])}'")

                # Track number of coordinates for this image
                if image_name not in image_coord_count:
                    image_coord_count[image_name] = 0
                image_coord_count[image_name] += 1

        # Write to files
        with open(coord_filepath, "w") as coord_file:
            coord_file.write("\n".join(coord_data))
        
        with open(name_filepath, "w") as name_file:
            name_file.write("\n".join(name_data) + ",\n    \"back\",")  # Add the "back" at the end
            
        with open(name_to_crop_filepath, "w") as name_to_crop_file:
            name_to_crop_file.write("\n".join(name_to_crop_data) + ",\n    \"back\",")  # Add the "back" at the end
        
        # Export image dimensions (width, height) to a separate file
        with open(size_filepath, "w") as size_file:
            for image_name, (width, height) in image_dimensions.items():
                # Ensure dimensions are written for each set of coordinates of that image
                for _ in range(image_coord_count[image_name]):
                    size_file.write(f'("{image_name}", {width}, {height}),  # Image with {width}px width and {height}px height\n')

        self.report({'INFO'}, f"Data exported to {base_path}")
        return {'FINISHED'}

    def convert_coords(self, coords, image_height):
        """Convert coordinates from GIMP to Blender by adjusting Y-axis"""
        xmin, ymin, xmax, ymax = coords
        # Invert the Y-coordinate (Blender uses the bottom-left corner as origin for the image)
        return xmin, image_height - ymax, xmax, image_height - ymin

    def get_image_from_face(self, face):
        """Get the image associated with a face's material (first texture)"""
        for loop in face.loops:
            # Check the material of the face and get the image texture
            material = loop.face.material_index
            mat = bpy.context.object.data.materials[material]
            if mat and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'TEX_IMAGE':
                        return node.image
        return None

# Register the export functionality
def menu_func(self, context):
    self.layout.operator(ExportUVInfoOperator.bl_idname)

def register():
    bpy.utils.register_class(ExportUVInfoOperator)
    bpy.types.IMAGE_MT_view.append(menu_func)

def unregister():
    bpy.utils.unregister_class(ExportUVInfoOperator)
    bpy.types.IMAGE_MT_view.remove(menu_func)

if __name__ == "__main__":
    register()
