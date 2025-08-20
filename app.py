import os
import json
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

# --- Prompt base para Gemini ---
PROMPT_BASE = """
Eres un asistente experto en manipulación de DataFrames de Pandas.
Tu única tarea es escribir una función de Python llamada modificar_df(df) 
que modifique el DataFrame según la instrucción del usuario y devuelva el resultado.

Reglas estrictas:
- Siempre devuelve solo una función válida de Python, sin texto adicional.
- Usa pandas (pd) y numpy (np).
- El DataFrame puede estar vacío (en ese caso debes crearlo según la instrucción).
- El usuario puede pedir tareas básicas como:
  - Crear DataFrames desde cero (con columnas y valores si se especifica).
  - Filtrar filas (ejemplo: 'Notas' > 3.0).
  - Añadir o eliminar filas/columnas.
  - Modificar valores.
  - Calcular sumas, promedios o conteos.
  - Crear nuevas columnas basadas en condiciones.

Ejemplos de comportamiento esperado:

1. Instrucción: "Crea un archivo con las columnas 'Nombre' y 'Edad'."
   Respuesta:
   def modificar_df(df):
       df = pd.DataFrame(columns=['Nombre', 'Edad'])
       return df

2. Instrucción: "Crea un archivo que tenga una columna 'Estudiantes' con los valores ['Nicolás','Sandra','Juan'] y otra columna 'Notas' con [1.0, 2.0, 5.0]."
   Respuesta:
   def modificar_df(df):
       df = pd.DataFrame({
           'Estudiantes': ['Nicolás','Sandra','Juan'],
           'Notas': [1.0, 2.0, 5.0]
       })
       return df

3. Instrucción: "Filtra las filas donde 'Notas' sea mayor que 3.0."
   Respuesta:
   def modificar_df(df):
       df = df[df['Notas'] > 3.0]
       return df

4. Instrucción: "Promedia los valores de la columna 'Precio' y crea una nueva columna 'Estado' con 'Económico' si el valor < promedio, si no 'Caro'."
   Respuesta:
   def modificar_df(df):
       promedio = df['Precio'].mean()
       df['Estado'] = np.where(df['Precio'] < promedio, 'Económico', 'Caro')
       return df
"""

# --- Fallback mínimo ---
def fallback_processing(df, instruction):
    try:
        if instruction.lower().startswith("crea un archivo"):
            return pd.DataFrame()
    except:
        return None
    return None

# --- La Ruta Principal del Servidor ---
@app.route('/process-excel', methods=['POST'])
def process_excel():
    instruction = request.form.get('instruction', '')
    file = request.files.get('file')

    if not instruction:
        return jsonify({"error": "Por favor, ingresa una instrucción."}), 400

    # Determinar si el usuario subió un archivo o quiere crear uno
    if file:
        try:
            df = pd.read_excel(file)
        except Exception as e:
            return jsonify({"error": "No se pudo leer el archivo de Excel.", "detalle_tecnico": str(e)}), 400
    else:
        df = pd.DataFrame()

    try:
        # Extraer contexto
        columnas = list(df.columns)
        columnas_str = ", ".join([f"'{col}'" for col in columnas])
        primeras_filas = df.head(5).to_string()

        # Construir prompt
        prompt = (
            PROMPT_BASE
            + "\n--- Contexto del Documento ---\n"
            + (f"Columnas del DataFrame: {columnas_str}\nPrimeras 5 filas:\n{primeras_filas}\n" if columnas else "El DataFrame está vacío.\n")
            + "--- Instrucción del Usuario ---\n"
            + instruction
        )

        # Enviar a Gemini
        response = model.generate_content(prompt)
        gemini_code = response.text.strip('`').strip()

        # Validaciones básicas
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
        print(f"Error con IA, intentando fallback: {e}")
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
                download_name="resultado.xlsx"
            )
        else:
            return jsonify({
                "error": "Lo siento, no pude entender esa instrucción.",
                "detalle_tecnico": str(e),
                "codigo_generado_por_gemini": gemini_code if 'gemini_code' in locals() else 'No disponible'
            }), 500

if __name__ == '__main__':
    app.run(debug=True)
