bl_info = {
    "name": "CropImages",
    "blender": (3, 5, 0),
    "category": "Object",
    "author": "SirUka",
    "version": (1, 0, 0),
    "description": "An addon designed to extract Uv coordinates translating to pixels and automatically cropping textures from a 3d model",
    "warning": "USE THIS ONLY IN THE FOLDER WHERE THE TEXTURES YOU WANT TO BE CROPPED ARE",
    "doc_url": "",
    "tracker_url": "",
    "support": "COMMUNITY",
}

import bpy
import os
from bpy.props import StringProperty
from bpy.types import Operator, Panel
from bpy_extras.io_utils import ImportHelper

# Coordenadas de recorte para cada imagen
coords = [
    (256, 64, 320, 128),    # Coordenadas para 'tex1617470959-0006021Bc1b3.bmp_variant1'
    (320, 64, 384, 128),    # Coordenadas para 'tex1617470959-0006021Bc1b3.bmp_variant2'
    (384, 64, 448, 128),    # Coordenadas para 'tex1617470959-0006021Bc1b3.bmp_variant3'
    (192, 64, 256, 128),    # Coordenadas para 'tex1617470959-0006021Bc1b3.bmp_variant4'
]

# Nombres de las imágenes originales (estos son los nombres exactos que se usarán para encontrar las imágenes)
crop_names = [
    "tex1617470959-0006021Bc1b3.bmp",  # Nombre base de la imagen original
    "tex1617470959-0006021Bc1b3.bmp",
    "tex1617470959-0006021Bc1b3.bmp",
    "tex1617470959-0006021Bc1b3.bmp",
]

# Nombres de las imágenes recortadas (esto es lo que se usará al guardar las imágenes recortadas)
names = [
    "tex1617470959-0006021Bc1b3.bmp_variant1",
    "tex1617470959-0006021Bc1b3.bmp_variant2",
    "tex1617470959-0006021Bc1b3.bmp_variant3",
    "tex1617470959-0006021Bc1b3.bmp_variant4",
]

# Lista de dimensiones (ancho, alto) para cada imagen
height_width = [
    ("tex1617470959-0006021Bc1b3.bmp", 1024, 128),  # Imagen con 1024px de ancho y 128px de alto
    ("tex1617470959-0006021Bc1b3.bmp", 512, 128),   # Imagen con 512px de ancho y 128px de alto
    ("tex1617470959-0006021Bc1b3.bmp", 1024, 128),  # Otra imagen con 1024px de ancho y 128px de alto
    ("tex1617470959-0006021Bc1b3.bmp", 512, 128),   # Otra imagen con 512px de ancho y 128px de alto
]

# Función para obtener las dimensiones de la imagen basada en su nombre
def get_image_dimensions(image_name):
    for name, width, height in height_width:
        if name == image_name:
            return width, height
    return None, None  # Si no se encuentra el nombre, devolver None

# Convertir coordenadas Y de GIMP a Blender, tomando en cuenta el alto y ancho de la imagen
def convert_coords(coords, image_width, image_height):
    xmin, ymin, xmax, ymax = coords
    
    # Calcular el factor de escala basado en el ancho de la imagen
    scale_factor_x = image_width / 1024.0  # Se compara con el tamaño de referencia de 1024px de ancho
    
    # Escalar las coordenadas proporcionalmente según el ancho de la imagen
    xmin = int(xmin * scale_factor_x)
    xmax = int(xmax * scale_factor_x)
    
    # Convertir coordenadas Y de GIMP a Blender (invertir la coordenada Y)
    return (xmin, image_height - ymax, xmax, image_height - ymin)

# Función para recortar una imagen
def crop_image(image, coords, image_name):
    xmin, ymin, xmax, ymax = coords
    width = xmax - xmin
    height = ymax - ymin
    
    # Crear una nueva imagen recortada
    image_cropped = bpy.data.images.new(image_name, width, height)
    
    # Copiar los píxeles recortados a la nueva imagen
    pixels = list(image.pixels)
    pixels_cropped = [0] * (width * height * 4)  # RGBA channels
    for y in range(height):
        for x in range(width):
            src_x = xmin + x
            src_y = ymin + y
            src_idx = (src_y * image.size[0] + src_x) * 4
            dest_idx = (y * width + x) * 4
            pixels_cropped[dest_idx:dest_idx+4] = pixels[src_idx:src_idx+4]
    
    # Asignar los píxeles a la imagen recortada
    image_cropped.pixels = pixels_cropped
    
    return image_cropped

# Función para procesar las imágenes basadas en las coordenadas y nombres
def process_image(image_path, coords, crop_name, save_name):
    # Cargar la imagen desde el path
    image = bpy.data.images.load(image_path)
    
    # Obtener las dimensiones reales de la imagen usando la lista height_width
    image_width, image_height = get_image_dimensions(crop_name)
    
    if image_width is None or image_height is None:
        print(f"No se encontraron dimensiones para la imagen {crop_name}.")
        return
    
    # Convertir coordenadas a formato Blender usando la altura y el ancho de la imagen real
    coords_for_crop = convert_coords(coords, image_width, image_height)  # Usar el alto y el ancho de la imagen cargada
    image_cropped = crop_image(image, coords_for_crop, save_name)
    
    # Guardar la imagen recortada en la misma carpeta de origen
    original_folder = os.path.dirname(image_path)
    cropped_image_path = os.path.join(original_folder, save_name + ".png")
    image_cropped.filepath_raw = cropped_image_path
    image_cropped.save()
    print(f"Imagen {save_name}.png guardada en {original_folder}")

# Función para manejar el recorte de imágenes para todas las coordenadas y nombres
def crop_images_from_folder(main_folder):
    # Recorrer todas las imágenes y aplicar el recorte
    for root, dirs, files in os.walk(main_folder):
        for file in files:
            # Solo procesar imágenes que estén en la lista 'crop_names'
            if file in crop_names:
                image_path = os.path.join(root, file)
                
                # Encontrar el índice del name en la lista de crop_names
                index = crop_names.index(file)  # Encuentra el índice basado en el nombre del archivo
                
                # Recortar la imagen para cada coordenada asociada
                for i in range(len(coords)):
                    if crop_names[i] == file:  # Si las coordenadas pertenecen a esta imagen
                        save_name = names[i]  # Obtener el nombre de la variante
                        process_image(image_path, coords[i], file, save_name)
                        print(f"Recorte realizado para {save_name}.")
            else:
                print(f"Imagen {file} no corresponde a un recorte válido.")
                
    print("Recorte de imágenes completado.")

class OT_SelectMainFolder(Operator, ImportHelper):
    bl_idname = "file.select_main_folder"
    bl_label = "Select Main Folder"
    
    directory: StringProperty(
        name="Directory",
        description="Select the main folder",
        maxlen=1024,
        subtype='DIR_PATH',
    )
    
    def execute(self, context):
        main_folder = self.directory
        print(f"Selected main folder: {main_folder}")
        
        # Procesar las imágenes para todas las coordenadas y nombres
        crop_images_from_folder(main_folder)
        
        return {'FINISHED'}

class OT_CleanTextures(Operator):
    bl_idname = "object.clean_textures"
    bl_label = "Clean Textures"
    
    def execute(self, context):
        bpy.ops.file.select_main_folder('INVOKE_DEFAULT')
        return {'FINISHED'}

class PT_MainPanel(Panel):
    bl_idname = "PT_MainPanel"
    bl_label = "Clean Textures Panel"
    bl_category = "Clean Textures"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    
    def draw(self, context):
        layout = self.layout
        layout.operator("object.clean_textures", text="Clean Textures")

def register():
    bpy.utils.register_class(OT_SelectMainFolder)
    bpy.utils.register_class(OT_CleanTextures)
    bpy.utils.register_class(PT_MainPanel)

def unregister():
    bpy.utils.unregister_class(OT_SelectMainFolder)
    bpy.utils.unregister_class(OT_CleanTextures)
    bpy.utils.unregister_class(PT_MainPanel)

if __name__ == "__main__":
    register()
