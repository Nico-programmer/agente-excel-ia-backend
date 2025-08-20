import os
import json
import google.generativeai as genai
from flask import Flask, request, jsonify, send_file
import pandas as pd
import io
from dotenv import load_dotenv

# --- Configuración Inicial ---
load_dotenv()
genai.configure(api_key=os.environ.get("GOOGLE_API_KEY"))
model = genai.GenerativeModel('gemini-1.5-flash')
app = Flask(__name__)

# --- Lógica de Respaldo para Tareas Básicas (Fallback) ---
def fallback_processing(df, instruction):
    # Lógica para "añadir columna"
    if "añade una columna" in instruction.lower() and "con el valor" in instruction.lower():
        try:
            # Extraer el nombre de la columna y el valor
            parts = instruction.lower().split("añade una columna llamada '")
            col_name_part = parts[1].split("'")[0]
            val_part = instruction.split("con el valor '")
            value = val_part[1].split("'")[0]
            
            df[col_name_part] = value
            return df
        except:
            return None  # Devuelve None si la lógica de respaldo falla

    # Puedes añadir más lógicas de respaldo aquí
    # Por ejemplo, para sumar una columna
    # if "suma la columna" in instruction.lower():
    #     ...

    return None # Si no hay lógica de respaldo que coincida

# --- La Ruta Principal del Servidor ---
@app.route('/process-excel', methods=['POST'])
def process_excel():
    if 'file' not in request.files or 'instruction' not in request.form:
        return jsonify({"error": "Archivo o instrucción faltante."}), 400

    file = request.files['file']
    instruction = request.form.get('instruction', '')

    df = pd.read_excel(file)

    try:
        # --- PRIMER INTENTO: Generación de código con IA ---
        prompt = (
            f"Basándote en la siguiente instrucción, escribe **ÚNICAMENTE** una función de Python llamada 'modificar_df' "
            f"que tome un DataFrame de Pandas 'df' y lo modifique, y que devuelva el DataFrame modificado. "
            f"El código debe ser sintácticamente correcto y estar listo para ser ejecutado. "
            f"No incluyas ningún texto o explicación adicional. "
            f"Instrucción: {instruction}"
            f"Ejemplo: Para 'Añade una columna llamada 'Estado' con el valor 'Pendiente'' la respuesta es:\n"
            f"def modificar_df(df):\n"
            f"    df['Estado'] = 'Pendiente'\n"
            f"    return df"
        )
        
        response = model.generate_content(prompt)
        gemini_code = response.text.strip('`').strip()

        # Validaciones de seguridad
        if "os." in gemini_code or "subprocess" in gemini_code:
            raise ValueError("Código malicioso detectado.")

        # Ejecución del código generado
        globals_dict = {'pd': pd, 'df': df.copy()}
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
            # Si el fallback funciona, devuelve el archivo
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
            # Si ambos fallan, muestra un error amigable
            return jsonify({
                "error": "Lo siento, no pude entender esa instrucción. Por favor, intenta de nuevo con una tarea más sencilla.",
                "detalle_tecnico": str(e),
                "codigo_generado_por_gemini": gemini_code if 'gemini_code' in locals() else 'No disponible'
            }), 500

if __name__ == '__main__':
    app.run(debug=True)