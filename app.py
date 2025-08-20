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

    # Detectar si la instrucción es "crear archivo con columnas y valores"
    pattern = r"columna '([^']+)'[^\)]*?son ([^)]*)"
    matches = re.findall(pattern, instruction, flags=re.IGNORECASE)

    if matches:
        data = {}
        for col, values_str in matches:
            # Separar valores por coma y limpiar espacios
            values = [v.strip() for v in values_str.split(",")]
            parsed_values = []
            for v in values:
                try:
                    # Intentar convertir a número si aplica
                    if v.replace(".", "", 1).isdigit():
                        parsed_values.append(float(v) if "." in v else int(v))
                    else:
                        parsed_values.append(v)
                except:
                    parsed_values.append(v)
            data[col] = parsed_values
        return pd.DataFrame(data)

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

    # Tarea 2: Sumar una columna
    if ("suma los valores" in instruction_lower or "calcula la suma" in instruction_lower) and "columna" in instruction_lower:
        try:
            col_name = instruction_lower.split("la columna '")[1].split("'")[0]
            df.loc[len(df)] = [None] * len(df.columns)
            df.loc[len(df) - 1, col_name] = df[col_name].sum()
            return df
        except:
            return None

    # Tarea 3: Evaluar notas por encima del promedio
    if "calcula el promedio" in instruction_lower and ("evaluación" in instruction_lower or "valoración" in instruction_lower):
        try:
            promedio = df['Notas'].mean()
            df['Evaluación'] = np.where(df['Notas'] >= promedio, 'Bien', 'Regular')
            return df
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
        if not ("crea un archivo" in instruction.lower() or "crea un excel" in instruction.lower()):
            return jsonify({"error": "Para crear un archivo, la instrucción debe empezar con 'crea un archivo' o 'crea un excel'."}), 400

    try:
        # Extraer el contexto del documento para la IA
        columnas = list(df.columns)
        columnas_str = ", ".join([f"'{col}'" for col in columnas])
        primeras_filas = df.head(5).to_string()

        # Generar el prompt enriquecido
        prompt = (
            f"Basándote en la siguiente instrucción de usuario y en el contexto del documento de Excel, "
            f"escribe **ÚNICAMENTE** una función de Python llamada 'modificar_df' "
            f"que tome un DataFrame de Pandas 'df' y lo modifique, y que devuelva el DataFrame modificado.\n"
            f"Si el DataFrame 'df' está vacío, tu tarea es crearlo en base a la instrucción del usuario.\n"
            f"El código debe ser sintácticamente correcto y estar listo para ser ejecutado. "
            f"No incluyas ningún texto o explicación adicional.\n"
            f"--- Contexto del Documento ---\n"
            f"Columnas del DataFrame: {columnas_str if columnas else 'No hay columnas. El DataFrame está vacío.'}\n"
            f"Primeras 5 filas:\n{primeras_filas}\n"
            f"--- Instrucción del Usuario ---\n"
            f"Instrucción: {instruction}\n"
            f"--- Ejemplos de Tarea ---\n"
            f"1. Si la instrucción es 'Crea un archivo con las columnas 'Nombre', 'Edad', 'Ciudad'', la respuesta debería ser:\n"
            f"def modificar_df(df):\n"
            f"    df = pd.DataFrame(columns=['Nombre', 'Edad', 'Ciudad'])\n"
            f"    return df\n\n"
            f"2. Si la instrucción es 'Crea un archivo con las columnas 'Nombre', 'Edad', 'Ciudad' con valores: "
            f"Nombre: Juan, María, Pedro | Edad: 25, 30, 22 | Ciudad: Madrid, Barcelona, Valencia', la respuesta debería ser:\n"
            f"def modificar_df(df):\n"
            f"    data = {{\n"
            f"        'Nombre': ['Juan', 'María', 'Pedro'],\n"
            f"        'Edad': [25, 30, 22],\n"
            f"        'Ciudad': ['Madrid', 'Barcelona', 'Valencia']\n"
            f"    }}\n"
            f"    df = pd.DataFrame(data)\n"
            f"    return df\n\n"
            f"3. Si la instrucción es 'Crea un archivo que tenga una columna 'Estudiantes' "
            f"(los valores en la columna 'Estudiantes' son Nicolás, Sandra y Juan) y otra que diga 'Notas' "
            f"(los valores en la columna 'Notas' son 1.0, 2.0, 5.0)', la respuesta debería ser:\n"
            f"def modificar_df(df):\n"
            f"    data = {{\n"
            f"        'Estudiantes': ['Nicolás', 'Sandra', 'Juan'],\n"
            f"        'Notas': [1.0, 2.0, 5.0]\n"
            f"    }}\n"
            f"    df = pd.DataFrame(data)\n"
            f"    return df\n\n"
        )
        
        response = model.generate_content(prompt)
        gemini_code = response.text.strip('`').strip()

        # Validaciones de seguridad
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
        # Lógica de respaldo
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