import os
import json
import google.generativeai as genai
from flask import Flask, request, jsonify, send_file
import pandas as pd
import io
import numpy as np
from dotenv import load_dotenv

# --- Configuración Inicial ---
# Carga las variables desde el archivo .env (API KEY IA)
load_dotenv()

# Configura la API de Gemini
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
# Elige el modelo de IA que usaremos
model = genai.GenerativeModel('gemini-1.5-flash')

# Crea una aplicación web con Flask
app = Flask(__name__)

# --- Lógica de Respaldo para Tareas Comunes (Fallback) ---
def fallback_processing(df, instruction):
    """
    Intenta procesar la instrucción con lógica predefinida si la IA falla.
    Puedes añadir más tareas comunes aquí de manera modular.
    """
    instruction_lower = instruction.lower()

    # Tarea 1: Añadir columna y asignar un valor
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

    # Tarea 3: Evaluar notas por encima de un promedio
    if "calcula el promedio" in instruction_lower and ("evaluación" in instruction_lower or "valoración" in instruction_lower):
        try:
            promedio = df['Notas'].mean()
            df['Evaluación'] = np.where(df['Notas'] >= promedio, 'Bien', 'Regular')
            return df
        except:
            return None
    
    # Puedes añadir más lógicas de respaldo aquí
    # if "filtrar" in instruction_lower:
    #    ...

    return None

# --- La Ruta Principal del Servidor ---
@app.route('/process-excel', methods=['POST'])
def process_excel():
    if 'file' not in request.files or 'instruction' not in request.form:
        return jsonify({"error": "Archivo o instrucción faltante."}), 400

    file = request.files['file']
    instruction = request.form.get('instruction', '')

    try:
        df = pd.read_excel(file)
    except Exception as e:
        return jsonify({"error": "No se pudo leer el archivo de Excel.", "detalle_tecnico": str(e)}), 400

    try:
        # PASO CLAVE: EXTRAER INFORMACIÓN DEL DOCUMENTO
        columnas = list(df.columns)
        columnas_str = ", ".join([f"'{col}'" for col in columnas])
        primeras_filas = df.head(5).to_string()

        # --- PRIMER INTENTO: Generación de código con IA ---
        prompt = (
            f"Basándote en la siguiente instrucción de usuario y en el contexto del documento de Excel, "
            f"escribe **ÚNICAMENTE** una función de Python llamada 'modificar_df' "
            f"que tome un DataFrame de Pandas 'df' y lo modifique, y que devuelva el DataFrame modificado.\n"
            f"El código debe ser sintácticamente correcto y estar listo para ser ejecutado. "
            f"No incluyas ningún texto o explicación adicional.\n"
            f"--- Contexto del Documento ---\n"
            f"Columnas del DataFrame: {columnas_str}\n"
            f"Primeras 5 filas:\n{primeras_filas}\n"
            f"--- Instrucción del Usuario ---\n"
            f"Instrucción: {instruction}\n"
            f"--- Ejemplo de Tarea ---\n"
            f"Si la instrucción es 'Crea una columna 'Total' sumando las columnas 'Ventas' y 'Costos'', la respuesta debería ser:\n"
            f"def modificar_df(df):\n"
            f"    df['Total'] = df['Ventas'] + df['Costos']\n"
            f"    return df"
        )
        
        response = model.generate_content(prompt)
        gemini_code = response.text.strip('`').strip()

        # Validaciones de seguridad para evitar código malicioso
        if "os." in gemini_code or "subprocess" in gemini_code or "shutil" in gemini_code:
            raise ValueError("Código malicioso detectado.")

        # Ejecución del código generado
        globals_dict = {'pd': pd, 'np': np, 'df': df.copy()}
        exec(gemini_code, globals_dict)
        df_modified = globals_dict['modificar_df'](df.copy())

        # Si el código se ejecuta sin errores, devolvemos el resultado
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
        # --- SEGUNDO INTENTO: Lógica de respaldo (Fallback) ---
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
                "error": "Lo siento, no pude entender esa instrucción. Por favor, intenta de nuevo con una tarea más sencilla.",
                "detalle_tecnico": str(e),
                "codigo_generado_por_gemini": gemini_code if 'gemini_code' in locals() else 'No disponible'
            }), 500

if __name__ == '__main__':
    app.run(debug=True)