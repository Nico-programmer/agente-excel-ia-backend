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

# --- Lógica de Respaldo para Tareas Comunes (Fallback) ---
def fallback_processing(df, instruction):
    """
    Intenta procesar la instrucción con lógica predefinida si la IA falla.
    """
    instruction_lower = instruction.lower()

    # Tarea 1: Añadir columna con un valor
    if "añade una columna" in instruction_lower and "con el valor" in instruction_lower:
        try:
            parts = instruction_lower.split("añade una columna llamada '")
            col_name = parts[1].split("'")[0]
            value = instruction.split("con el valor '")[1].split("'")[0]
            df[col_name] = value
            return df
        except:
            return None

    # Tarea 2: Sumar una columna y colocar el resultado al final
    if ("suma los valores" in instruction_lower or "calcula la suma" in instruction_lower) and "columna" in instruction_lower:
        try:
            col_name = instruction_lower.split("la columna '")[1].split("'")[0]
            df.loc[len(df)] = [None] * len(df.columns)
            df.loc[len(df) - 1, col_name] = df[col_name].sum()
            return df
        except:
            return None

    # Tarea 3: Evaluar notas con promedio
    if "calcula el promedio" in instruction_lower and ("evaluación" in instruction_lower or "valoración" in instruction_lower):
        try:
            promedio = df['Notas'].mean()
            df['Evaluación'] = np.where(df['Notas'] >= promedio, 'Bien', 'Regular')
            return df
        except:
            return None
    
    return None

# --- Ruta Principal ---
@app.route('/process-excel', methods=['POST'])
def process_excel():
    instruction = request.form.get('instruction', '')
    file = request.files.get('file')

    if not instruction:
        return jsonify({"error": "Por favor, ingresa una instrucción."}), 400

    # Si subió un archivo
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
        # Contexto para IA
        columnas = list(df.columns)
        columnas_str = ", ".join([f"'{col}'" for col in columnas])
        primeras_filas = df.head(5).to_string()

        # Prompt estricto
        prompt = (
            f"Escribe ÚNICAMENTE una función Python válida llamada modificar_df(df).\n"
            f"- Debe recibir un DataFrame de Pandas llamado df y devolver el DataFrame modificado.\n"
            f"- Si df está vacío, debes crearlo en base a la instrucción del usuario.\n"
            f"- No escribas explicaciones, texto adicional ni comentarios, solo el código.\n"
            f"- No uses ``` ni bloques markdown.\n"
            f"- El código debe ser ejecutable directamente con exec() en Python.\n\n"
            f"--- Contexto del Documento ---\n"
            f"Columnas: {columnas_str if columnas else 'No hay columnas, DataFrame vacío.'}\n"
            f"Primeras filas:\n{primeras_filas}\n\n"
            f"--- Instrucción del Usuario ---\n"
            f"{instruction}\n"
        )

        response = model.generate_content(prompt)
        gemini_code = response.text.strip()

        # Limpieza de código
        if gemini_code.startswith("```"):
            gemini_code = gemini_code.strip("`")
        if gemini_code.lower().startswith("python"):
            gemini_code = gemini_code[6:].strip()

        if "def modificar_df" not in gemini_code:
            raise ValueError("La IA no devolvió una función válida.")

        # Validaciones de seguridad
        if any(x in gemini_code for x in ["os.", "subprocess", "shutil", "open(", "exec(", "eval("]):
            raise ValueError("Código malicioso detectado.")

        # Ejecutar código generado
        globals_dict = {'pd': pd, 'np': np, 'df': df.copy()}
        exec(gemini_code, globals_dict)
        df_modified = globals_dict['modificar_df'](df.copy())

        # Respuesta con archivo Excel
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_modified.to_excel(writer, index=False)
        output.seek(0)
        
        return send_file(
            output,
            mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            as_attachment=True,
            download_name="resultado.xlsx"
        )

    except Exception as e:
        # Intentar fallback
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