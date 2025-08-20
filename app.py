import os
import json
import re
import google.generativeai as genai
from flask import Flask, request, jsonify, send_file
import pandas as pd
import io
import numpy as np
from dotenv import load_dotenv

# --- Configuración Inicial ---
load_dotenv()
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')
app = Flask(__name__)

# --- Lógica de Respaldo para Tareas Comunes (Fallback) ---
def fallback_processing(df, instruction):
    """
    Intenta procesar la instrucción con lógica predefinida si la IA falla.
    """
    instruction_lower = instruction.lower()

    # Añadir columna y asignar un valor fijo
    if "añade una columna" in instruction_lower and "con el valor" in instruction_lower:
        try:
            parts = instruction_lower.split("añade una columna llamada '")
            col_name = parts[1].split("'")[0]
            value = instruction.split("con el valor '")[1].split("'")[0]
            df[col_name] = value
            return df
        except:
            return None

    # Filtrar filas por condición
    if "filtra" in instruction_lower and "columna" in instruction_lower:
        try:
            col_name = instruction.split("columna '")[1].split("'")[0]
            if "menor que" in instruction_lower:
                value = float(re.findall(r"menor que (\d+\.?\d*)", instruction_lower)[0])
                return df[df[col_name] < value]
            elif "mayor que" in instruction_lower:
                value = float(re.findall(r"mayor que (\d+\.?\d*)", instruction_lower)[0])
                return df[df[col_name] > value]
            elif "igual a" in instruction_lower:
                value = re.findall(r"igual a (\d+\.?\d*)", instruction_lower)[0]
                return df[df[col_name] == float(value)]
        except:
            return None

    # Sumar valores de una columna y poner total al final
    if "suma" in instruction_lower and "columna" in instruction_lower:
        try:
            col_name = instruction.split("columna '")[1].split("'")[0]
            total = df[col_name].sum()
            nueva_fila = {col: None for col in df.columns}
            nueva_fila[col_name] = total
            df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
            return df
        except:
            return None

    # Calcular promedio de cualquier columna numérica y crear evaluación
    if "calcula el promedio" in instruction_lower:
        try:
            col_name = instruction.split("columna '")[1].split("'")[0]
            promedio = df[col_name].mean()
            df['Evaluación'] = np.where(df[col_name] >= promedio, 'Arriba del promedio', 'Debajo del promedio')
            return df
        except:
            return None

    return None


# --- Ruta principal ---
@app.route('/process-excel', methods=['POST'])
def process_excel():
    instruction = request.form.get('instruction', '')
    file = request.files.get('file')

    if not instruction:
        return jsonify({"error": "Por favor, ingresa una instrucción."}), 400

    # Cargar archivo si fue subido
    if file:
        try:
            df = pd.read_excel(file)
        except Exception as e:
            return jsonify({"error": "No se pudo leer el archivo de Excel.", "detalle_tecnico": str(e)}), 400
    else:
        df = pd.DataFrame()
        if not ("crea un archivo" in instruction.lower() or "crea un excel" in instruction.lower()):
            return jsonify({"error": "Para crear un archivo, la instrucción debe empezar con 'crea un archivo' o 'crea un excel'."}), 400

    try:
        # Contexto
        columnas = list(df.columns)
        columnas_str = ", ".join([f"'{col}'" for col in columnas])
        primeras_filas = df.head(5).to_string()

        # Prompt enriquecido
        prompt = f"""
Basándote en la siguiente instrucción y en el contexto del Excel, escribe **ÚNICAMENTE**
una función de Python llamada 'modificar_df' que reciba un DataFrame 'df' de pandas, lo modifique y lo retorne.

- Si el DataFrame está vacío, debes crearlo según la instrucción.
- El código debe ser válido y sin explicaciones extra.
- Usa pandas correctamente.

--- Contexto ---
Columnas actuales: {columnas_str if columnas else 'No hay columnas'}
Primeras filas:
{primeras_filas}

--- Instrucción del Usuario ---
{instruction}

--- Ejemplos ---
Instrucción: "Crea un archivo con columnas 'Nombre', 'Edad'"
Respuesta:
def modificar_df(df):
    df = pd.DataFrame(columns=['Nombre','Edad'])
    return df

Instrucción: "Filtra las filas donde 'Notas' sea menor que 3.0"
Respuesta:
def modificar_df(df):
    df = df[df['Notas'] < 3.0]
    return df

Instrucción: "Suma los valores de la columna 'Precio' y coloca el total en la última fila"
Respuesta:
def modificar_df(df):
    total = df['Precio'].sum()
    nueva_fila = {col: None for col in df.columns}
    nueva_fila['Precio'] = total
    df = pd.concat([df, pd.DataFrame([nueva_fila])], ignore_index=True)
    return df
"""

        response = model.generate_content(prompt)
        gemini_code = response.text.strip('`').strip()

        # Seguridad
        if "os." in gemini_code or "subprocess" in gemini_code or "shutil" in gemini_code:
            raise ValueError("Código malicioso detectado.")

        # Ejecutar el código generado
        globals_dict = {'pd': pd, 'np': np, 'df': df.copy()}
        exec(gemini_code, globals_dict)
        df_modified = globals_dict['modificar_df'](df.copy())

        # Exportar a Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_modified.to_excel(writer, index=False)
        output.seek(0)
        
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="archivo_modificado.xlsx"
        )

    except Exception as e:
        # Fallback
        print(f"Error con IA, intentando lógica de respaldo: {e}")
        df_modified_fallback = fallback_processing(df.copy(), instruction)
        
        if df_modified_fallback is not None:
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df_modified_fallback.to_excel(writer, index=False)
            output.seek(0)
            return send_file(
                output,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name="archivo_modificado.xlsx"
            )
        else:
            return jsonify({
                "error": "No pude entender esa instrucción.",
                "detalle_tecnico": str(e),
                "codigo_generado_por_gemini": gemini_code if 'gemini_code' in locals() else 'No disponible'
            }), 500

if __name__ == '__main__':
    app.run(debug=True)