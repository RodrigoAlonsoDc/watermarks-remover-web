import streamlit as st
import subprocess
import os
import tempfile
import json
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
from streamlit_drawable_canvas import st_canvas
import base64
from io import BytesIO
from st_img_pastebutton import paste

st.set_page_config(
    page_title="AI Watermarks Remover",
    page_icon="🧼",
    layout="centered"
)

st.title("🧼 AI Watermarks Remover")
st.markdown("""
Esta herramienta te ayuda a limpiar marcas de agua invisibles y metadatos generados por Inteligencia Artificial de tus textos y archivos.
""")

# Rutas de los scripts
BASE_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = BASE_DIR / "skills" / "remove-ai-marks" / "scripts"

tab_text, tab_visual = st.tabs(["📝 Limpiar Texto", "🖌️ Borrar Marca Visual"])

# --- Pestaña: Limpiar Texto ---
with tab_text:
    st.header("Limpiar Texto")
    st.markdown("Elimina caracteres invisibles (como ZWSP, espacios exóticos y caracteres bidireccionales).")
    
    input_text = st.text_area("Pega tu texto aquí:", height=200)
    
    if st.button("Limpiar Texto"):
        if not input_text.strip():
            st.warning("Por favor, ingresa algún texto.")
        else:
            with st.spinner("Limpiando..."):
                # Creamos archivos temporales para pasarle al script
                with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".txt", encoding="utf-8") as tmp_in:
                    tmp_in.write(input_text)
                    tmp_in_path = tmp_in.name
                
                tmp_out_path = tmp_in_path + ".cleaned.txt"
                
                try:
                    # Ejecutar clean_text.py
                    result = subprocess.run(
                        ["python", str(SCRIPTS_DIR / "clean_text.py"), tmp_in_path, "-o", tmp_out_path, "--stats", "--json"],
                        capture_output=True,
                        text=True,
                        check=False
                    )
                    
                    if os.path.exists(tmp_out_path):
                        with open(tmp_out_path, "r", encoding="utf-8") as f:
                            cleaned_text = f.read()
                        
                        st.success("¡Texto limpiado exitosamente!")
                        st.text_area("Texto Limpio:", value=cleaned_text, height=200)
                        
                        # Mostrar estadísticas si están disponibles
                        try:
                            # clean_text.py con --json imprime el json en stdout
                            output_json = json.loads(result.stdout.strip())
                            stats = output_json.get("stats", {})
                            st.info(f"Caracteres eliminados: {stats.get('removed_count', 0)} | Caracteres reemplazados: {stats.get('replaced_count', 0)}")
                        except json.JSONDecodeError:
                            pass
                        
                    else:
                        st.error(f"Error al limpiar el texto. Detalles:\n{result.stderr}")
                
                finally:
                    # Limpiar archivos temporales
                    if os.path.exists(tmp_in_path):
                        os.remove(tmp_in_path)
                    if os.path.exists(tmp_out_path):
                        os.remove(tmp_out_path)


# --- Pestaña: Borrar Marca Visual ---
with tab_visual:
    st.header("Borrar Marca Visual")
    st.markdown("Pinta sobre la marca de agua (texto o logo) para que el algoritmo intente rellenar el fondo.")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        visual_file = st.file_uploader("Sube tu imagen (PNG, JPG):", type=["png", "jpg", "jpeg"], key="visual_upload")
    with col2:
        st.write("O pega una imagen desde tu portapapeles:")
        pasted_data = paste(label="📋 Pegar Imagen", key="image_clipboard")
    
    image = None
    canvas_key = "canvas_empty"
    
    if pasted_data is not None:
        header, encoded = pasted_data.split(",", 1)
        binary_data = base64.b64decode(encoded)
        bytes_data = BytesIO(binary_data)
        image = Image.open(bytes_data).convert("RGB")
        canvas_key = f"canvas_pasted_{len(binary_data)}"
        file_name = "imagen_pegada.png"
    elif visual_file is not None:
        image = Image.open(visual_file).convert("RGB")
        canvas_key = f"canvas_{visual_file.name}_{visual_file.size}"
        file_name = visual_file.name
        
    if image is not None:
        
        # Redimensionar si es muy grande para que el canvas no se desborde
        max_width = 800
        if image.width > max_width:
            ratio = max_width / image.width
            new_size = (max_width, int(image.height * ratio))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
            st.info(f"Imagen redimensionada a {new_size[0]}x{new_size[1]} para mejor rendimiento en web.")
        
        st.write("Dibuja sobre el texto o logo:")
        
        stroke_width = st.slider("Grosor del pincel:", 1, 50, 10)
        
        # Canvas para pintar la máscara
        canvas_result = st_canvas(
            fill_color="rgba(255, 0, 0, 0.3)",  # Pincel rojo translúcido
            stroke_width=stroke_width,
            stroke_color="#FF0000",
            background_image=image,
            update_streamlit=True,
            height=image.height,
            width=image.width,
            drawing_mode="freedraw",
            key=canvas_key,
        )
        
        st.write("---")
        import io
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        st.download_button(
            label="📥 Descargar Imagen Directamente (Limpia de Metadatos)",
            data=buf.getvalue(),
            file_name=f"limpia_{file_name}",
            mime="image/png"
        )
        st.write("---")
        if st.button("Eliminar Marca Pintada"):
            if canvas_result.image_data is not None:
                with st.spinner("Procesando imagen con OpenCV..."):
                    # Extraer el canal alpha (donde se dibujó) de image_data como la máscara
                    mask = canvas_result.image_data[:, :, 3].astype(np.uint8)
                    
                    if np.sum(mask) == 0:
                        st.warning("No dibujaste nada. Usa el pincel sobre la marca de agua.")
                    else:
                        # Convertir la imagen original a formato BGR para OpenCV
                        img_bgr = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
                        
                        # Inpainting (telea algorithm)
                        inpaint_radius = max(3, stroke_width // 2)
                        result_bgr = cv2.inpaint(img_bgr, mask, inpaint_radius, cv2.INPAINT_TELEA)
                        
                        # Convertir de vuelta a RGB
                        result_rgb = cv2.cvtColor(result_bgr, cv2.COLOR_BGR2RGB)
                        result_image = Image.fromarray(result_rgb)
                        
                        st.success("¡Procesamiento terminado!")
                        st.image(result_image, caption="Resultado sin marca de agua visual")
                        
                        # Botón para descargar
                        import io
                        buf = io.BytesIO()
                        result_image.save(buf, format="PNG")
                        st.download_button(
                            label="📥 Descargar Imagen Resultante",
                            data=buf.getvalue(),
                            file_name=f"sin_marca_{file_name}",
                            mime="image/png"
                        )
