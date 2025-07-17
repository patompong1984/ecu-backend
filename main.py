from flask import Flask, request, jsonify, send_file
from flask_cors import CORS
import logging
import struct
import io
import json
from werkzeug.middleware.proxy_fix import ProxyFix

app = Flask(__name__)
CORS(app)
# ปรับปรุง format ของ log เพื่อให้มี timestamp และระดับความสำคัญ
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app.config['MAX_CONTENT_LENGTH'] = 6 * 1024 * 1024 # เพิ่มขนาดไฟล์
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# ==============================================================================
# IMPORTANT: MAP_OFFSETS and MAP_CONVERSION_SETTINGS are REMOVED from the backend.
# The frontend is now responsible for sending the full map definition,
# including offset, size, data type, endianness, and conversion factors.
# ==============================================================================

# Helper functions for display names and units (can still be useful for generic naming)
def get_map_display_name(map_name, default_display_name=None):
    # This function can still provide a more user-friendly name based on a predefined list
    # or just return the provided display_name from the map definition.
    names = {
        "limit_iq_1": "Limit IQ 1",
        "limit_iq_2": "Limit IQ 2",
        "limit_iq_3": "Limit IQ 3",
        "torque_tps_1": "Torque TPS 1 (Driver’s Wish)",
        "torque_tps_2": "Torque TPS 2",
        "torque_tps_3": "Torque TPS 3",
        "egr_target": "EGR Target",
        "pump_command": "Pump Command (Injection Quantity)",
        "injector_1": "Injector Map 1 (Duration)",
        "injector_2": "Injector Map 2 (Duration)",
        "limit_baro_1": "Limit Barometric Pressure 1",
        "limit_baro_2": "Limit Barometric Pressure 2",
        "limit_baro_3": "Limit Barometric Pressure 3",
        "limit_torque": "Limit Torque",
        "torque_gear": "Torque Gear Correction",
        "limit_crp": "Rail Pressure Limit (CRP)",
        "green_1": "Fuel Map Green 1",
        "green_2": "Fuel Map Green 2",
        "green_3": "Fuel Map Green 3",
        "green_4": "Fuel Map Green 4",
        "green_5": "Fuel Map Green 5",
        "turbo": "Turbo Boost Map",
        "turbo_meter": "Turbo Metering Map",
        "dtc_off": "DTC Off Table",
        "rail_pressure": "Rail Pressure Map"
    }
    return default_display_name if default_display_name else names.get(map_name, map_name.replace('_', ' ').title())

def get_map_unit(map_name, default_unit=None):
    # This function can still provide common units for known map types
    units = {
        "limit_iq_1": "mg/stroke",
        "limit_iq_2": "mg/stroke",
        "limit_iq_3": "mg/stroke",
        "torque_tps_1": "%",
        "torque_tps_2": "%",
        "torque_tps_3": "%",
        "egr_target": "%",
        "pump_command": "bar",
        "injector_1": "° BTDC",
        "injector_2": "° BTDC",
        "limit_baro_1": "mbar",
        "limit_baro_2": "mbar",
        "limit_baro_3": "mbar",
        "limit_torque": "Nm",
        "torque_gear": "Nm",
        "limit_crp": "bar",
        "green_1": "mg/stroke",
        "green_2": "mg/stroke",
        "green_3": "mg/stroke",
        "green_4": "mg/stroke",
        "green_5": "mg/stroke",
        "turbo": "mbar",
        "turbo_meter": "mbar",
        "dtc_off": "",
        "rail_pressure": "bar"
    }
    return default_unit if default_unit else units.get(map_name, "")


# Function to parse axis values (moved from main route for reusability)
def parse_axis_values(raw_bytes, scale, data_type="8bit", endian=None):
    values = []
    bytes_per_axis_value = 2 if data_type == "16bit" else 1

    for i in range(0, len(raw_bytes), bytes_per_axis_value):
        if i + bytes_per_axis_value > len(raw_bytes):
            logging.warning(f"Incomplete bytes for {data_type} axis value at index {i}. Skipping.")
            values.append(None)
            continue

        raw_value = None
        if data_type == "8bit":
            raw_value = raw_bytes[i]
        elif data_type == "16bit":
            if endian is None:
                logging.error(f"16bit axis requires 'endian' but it's missing.")
                values.append(None)
                continue
            try:
                raw_value = struct.unpack(endian, raw_bytes[i:i+bytes_per_axis_value])[0]
            except struct.error as se:
                logging.error(f"Struct unpack error for 16bit axis at index {i}. Bytes: {raw_bytes[i:i+bytes_per_axis_value].hex()}, Endian: {endian}. Error: {se}")
                values.append(None)
                continue
        else:
            logging.error(f"Unknown data_type '{data_type}' for axis.")
            values.append(None)
            continue

        if raw_value is not None:
            values.append(round(raw_value * scale, 2))
        else:
            values.append(None)
    return values

# Health Check Route
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "ECU Map Analyzer"}), 200

# Main Analysis Route (now fully relies on frontend map definition)
@app.route("/analyze", methods=["POST"])
def analyze_dynamic_map():
    if 'bin' not in request.files:
        logging.error("No file uploaded in the request.")
        return jsonify({"error": "No file uploaded"}), 400

    custom_map_definition_str = request.form.get("custom_map_definition")
    if not custom_map_definition_str:
        logging.error("No custom_map_definition provided in the request.")
        return jsonify({"error": "No map definition provided. Please define a map."}), 400

    try:
        map_def = json.loads(custom_map_definition_str)
    except json.JSONDecodeError as e:
        logging.error(f"Invalid JSON for custom_map_definition: {e}")
        return jsonify({"error": "Invalid map definition format. Please check JSON syntax."}), 400

    # Extract all necessary info directly from map_def
    map_name = map_def.get("name")
    display_name = map_def.get("displayName", map_name)
    unit = map_def.get("unit")
    block_offset = map_def.get("block")
    rows = map_def.get("rows")
    cols = map_def.get("cols")
    data_type = map_def.get("dataType")
    factor = map_def.get("factor")
    offset_val = map_def.get("offset")
    endian = map_def.get("endian") # For map data itself

    # X-axis specific settings
    x_axis_offset = map_def.get("xAxisOffset")
    x_axis_data_type = map_def.get("xAxisDataType", data_type) # Default to map's data_type
    x_axis_endian = map_def.get("xAxisEndian", endian) # Default to map's endian
    x_scale = map_def.get("xScale", 1.0) # Default scale for data/axis

    # Y-axis specific settings
    y_axis_offset = map_def.get("yAxisOffset")
    y_axis_data_type = map_def.get("yAxisDataType", data_type) # Default to map's data_type
    y_axis_endian = map_def.get("yAxisEndian", endian) # Default to map's endian
    y_scale = map_def.get("yScale", 1.0) # Default scale for data/axis

    # Basic validation for essential fields
    if any(val is None for val in [map_name, block_offset, rows, cols, data_type, factor, offset_val]):
        logging.error(f"Missing essential map definition fields: {map_def}")
        return jsonify({"error": "Incomplete map definition. Missing name, offset, dimensions, data type, factor, or offset."}), 400

    if data_type == "16bit" and endian is None:
        logging.error(f"16bit map '{map_name}' requires 'endian' property in definition.")
        return jsonify({"error": f"16-bit map '{map_name}' requires 'endian' property."}), 400

    byte_per_value = 2 if data_type == "16bit" else 1
    total_map_bytes = rows * cols * byte_per_value

    # Calculate required size for file bounds check
    required_size = block_offset + total_map_bytes
    if x_axis_offset is not None:
        x_axis_bytes_len = cols * (2 if x_axis_data_type == "16bit" else 1)
        required_size = max(required_size, x_axis_offset + x_axis_bytes_len)
    if y_axis_offset is not None:
        y_axis_bytes_len = rows * (2 if y_axis_data_type == "16bit" else 1)
        required_size = max(required_size, y_axis_offset + y_axis_bytes_len)

    try:
        bin_file = request.files["bin"]
        content = bin_file.read()

        if len(content) < required_size:
            logging.error(f"File too small for map '{map_name}'. File size: {len(content)} bytes, Required: {required_size} bytes. Check map definition or use correct BIN file.")
            return jsonify({"error": f"File too small for selected map. Expected at least {required_size} bytes, got {len(content)} bytes. Please check the BIN file or map offsets."}), 400

        # Read map block
        if block_offset < 0 or block_offset + total_map_bytes > len(content):
            logging.error(f"Map block read out of bounds for '{map_name}'. Offset: {hex(block_offset)}, Expected end: {hex(block_offset + total_map_bytes)}, File size: {hex(len(content))}.")
            return jsonify({"error": "Map data out of file bounds. Check map block offset and size."}), 400

        raw_block = content[block_offset : block_offset + total_map_bytes]
        if len(raw_block) != total_map_bytes:
            logging.error(f"Incomplete raw block for map '{map_name}'. Read {len(raw_block)} bytes, expected {total_map_bytes}. Check map size.")
            return jsonify({"error": "Incomplete map data in file. Check map dimensions."}), 400

        # Check for all identical bytes (might indicate empty map or wrong offset)
        if raw_block and all(b == raw_block[0] for b in raw_block):
            logging.warning(f"{map_name.upper()} map block contains all identical bytes: {raw_block[0]} (Offset: {hex(block_offset)}). This might indicate an incorrect offset or an empty/null map.")

        map_data = []
        for i in range(rows):
            row = []
            for j in range(cols):
                raw_value = None

                start_idx = (i * cols + j) * byte_per_value
                end_idx = start_idx + byte_per_value

                if end_idx > len(raw_block):
                    logging.warning(f"Map data out of bounds for {map_name} at [{i},{j}]. Block read {len(raw_block)} bytes, Expected idx {start_idx}. Filling with None.")
                    processed_value = None
                    row.append(processed_value)
                    continue

                if data_type == "8bit":
                    raw_value = raw_block[start_idx]
                elif data_type == "16bit":
                    if endian is None: # Redundant check, but good for safety
                        logging.error(f"16bit map '{map_name}' requires 'endian' in definition but it's missing.")
                        row.append(None)
                        continue
                    try:
                        raw_value = struct.unpack(endian, raw_block[start_idx:end_idx])[0]
                    except struct.error as se:
                        logging.error(f"Struct unpack error for 16bit map '{map_name}' at index {start_idx}. Bytes: {raw_block[start_idx:end_idx].hex()}, Endian: {endian}. Error: {se}. Filling with None.")
                        row.append(None)
                        continue
                else:
                    logging.error(f"Unknown data_type '{data_type}' for map '{map_name}'. Filling with None.")
                    row.append(None)
                    continue

                processed_value = None
                if raw_value is not None:
                    processed_value = raw_value * factor + offset_val
                    # Special handling for potentially negative values (e.g., pressure, duty cycle)
                    # You might want to make this configurable in the frontend map definition if needed.
                    # For now, keeping a general clamp for pressure-like values.
                    if unit in ["bar", "mbar", "% duty"] and processed_value < 0:
                         processed_value = 0

                row.append(round(processed_value, 2) if processed_value is not None else None)
            map_data.append(row)

        # Read and parse X and Y axes
        x_axis = []
        y_axis = []

        if x_axis_offset is not None:
            x_axis_raw_bytes_len = cols * (2 if x_axis_data_type == "16bit" else 1)
            if x_axis_offset < 0 or x_axis_offset + x_axis_raw_bytes_len > len(content):
                logging.warning(f"X-axis read out of bounds for {map_name}. Offset: {hex(x_axis_offset)}, Expected end: {hex(x_axis_offset + x_axis_raw_bytes_len)}, File size: {hex(len(content))}. Generating generic X-axis.")
                x_axis = [round(i * x_scale, 2) for i in range(cols)]
            else:
                x_axis_raw_bytes = content[x_axis_offset : x_axis_offset + x_axis_raw_bytes_len]
                x_axis = parse_axis_values(x_axis_raw_bytes, x_scale, x_axis_data_type, x_axis_endian)
        else:
            x_axis = [round(i * x_scale, 2) for i in range(cols)]
            logging.info(f"X-axis offset not specified for {map_name}. Generating generic X-axis with scale {x_scale}.")

        if y_axis_offset is not None:
            y_axis_raw_bytes_len = rows * (2 if y_axis_data_type == "16bit" else 1)
            if y_axis_offset < 0 or y_axis_offset + y_axis_raw_bytes_len > len(content):
                logging.warning(f"Y-axis read out of bounds for {map_name}. Offset: {hex(y_axis_offset)}, Expected end: {hex(y_axis_offset + y_axis_raw_bytes_len)}, File size: {hex(len(content))}. Generating generic Y-axis.")
                y_axis = [round(i * y_scale, 2) for i in range(rows)]
            else:
                y_axis_raw_bytes = content[y_axis_offset : y_axis_offset + y_axis_raw_bytes_len]
                y_axis = parse_axis_values(y_axis_raw_bytes, y_scale, y_axis_data_type, y_axis_endian)
        else:
            y_axis = [round(i * y_scale, 2) for i in range(rows)]
            logging.info(f"Y-axis offset not specified for {map_name}. Generating generic Y-axis with scale {y_scale}.")

        # Ensure axis lengths match map dimensions
        while len(x_axis) < cols:
            x_axis.append(None)
        while len(x_axis) > cols:
            x_axis.pop()

        while len(y_axis) < rows:
            y_axis.append(None)
        while len(y_axis) > rows:
            y_axis.pop()

        logging.info(f"Successfully analyzed '{map_name}' map ({data_type}). Dimensions: {rows}x{cols}. Block Offset: {hex(block_offset)}")
        return jsonify({
            "type": map_name, # Return map's name as 'type'
            "display_name": get_map_display_name(map_name, display_name),
            "offset": hex(block_offset), # Send offset as hex string
            "x_axis_offset": hex(x_axis_offset) if x_axis_offset is not None else "N/A",
            "y_axis_offset": hex(y_axis_offset) if y_axis_offset is not None else "N/A",
            "x_axis": x_axis,
            "y_axis": y_axis,
            "unit": get_map_unit(map_name, unit),
            "map": map_data
        })

    except Exception as e:
        logging.exception(f"Unhandled error during analysis for {map_name}.")
        return jsonify({"error": f"An unexpected error occurred during map analysis: {str(e)}. Please check log for details."}), 500

# Endpoint for saving tuned bin file (now fully relies on frontend map definition)
@app.route("/save_tuned_bin", methods=["POST"])
def save_tuned_bin():
    if 'original_bin' not in request.files:
        logging.error("No original_bin file provided for saving.")
        return jsonify({"error": "No original .bin file provided"}), 400

    original_bin_file = request.files['original_bin']
    modified_map_data_str = request.form.get("modified_map_data")
    custom_map_definition_str = request.form.get("custom_map_definition")

    if not modified_map_data_str or not custom_map_definition_str:
        logging.error("Missing modified_map_data or custom_map_definition in save request.")
        return jsonify({"error": "Missing modified data or map definition"}), 400

    try:
        modified_map_data = json.loads(modified_map_data_str)
        map_def = json.loads(custom_map_definition_str)
        content = bytearray(original_bin_file.read()) # Use bytearray for mutability
    except json.JSONDecodeError as e:
        logging.error(f"JSON Decode Error for modified_map_data or custom_map_definition: {e}")
        return jsonify({"error": f"Invalid data format: {str(e)}"}), 400

    # Extract all necessary info directly from map_def for saving
    map_name = map_def.get("name")
    block_offset = map_def.get("block")
    rows = map_def.get("rows")
    cols = map_def.get("cols")
    data_type = map_def.get("dataType")
    factor = map_def.get("factor")
    offset_val = map_def.get("offset")
    endian = map_def.get("endian") # For map data itself

    # Basic validation for essential fields for saving
    if any(val is None for val in [map_name, block_offset, rows, cols, data_type, factor, offset_val]):
        logging.error(f"Missing essential map definition fields for saving: {map_def}")
        return jsonify({"error": "Incomplete map definition for saving. Missing name, offset, dimensions, data type, factor, or offset."}), 400

    if data_type == "16bit" and endian is None:
        logging.error(f"16bit map '{map_name}' requires 'endian' property in definition for saving.")
        return jsonify({"error": f"16-bit map '{map_name}' requires 'endian' property for saving."}), 400

    byte_per_value = 2 if data_type == "16bit" else 1
    total_map_bytes = rows * cols * byte_per_value

    # Check if the file is large enough to contain the map data block
    if block_offset < 0 or block_offset + total_map_bytes > len(content):
        logging.error(f"Original file is too small to write map '{map_name}'. File size: {len(content)} bytes, Required end offset: {block_offset + total_map_bytes} bytes. Check map block offset and size.")
        return jsonify({"error": "Original file too small to write map data. Check map block offset and size."}), 400

    # Convert modified map data back to raw bytes and overwrite
    for i in range(rows):
        for j in range(cols):
            tuned_value = modified_map_data[i][j]

            # Handle None values from frontend gracefully
            if tuned_value is None:
                raw_tuned_value = 0 # Default to 0 if None. Consider a more appropriate default if needed for specific maps.
                logging.warning(f"Tuned value for {map_name} at [{i},{j}] is None. Setting to raw 0 for conversion.")
            else:
                # Reverse the conversion: raw = (value - offset) / factor
                if factor == 0:
                    logging.error(f"Factor is 0 for {map_name}. Cannot reverse convert tuned value at [{i},{j}]. Setting to 0.")
                    raw_tuned_value = 0
                else:
                    raw_tuned_value_float = (tuned_value - offset_val) / factor

                    if data_type == "8bit":
                        raw_tuned_value = int(round(raw_tuned_value_float))
                        # Clamp 8-bit values to 0-255
                        raw_tuned_value = max(0, min(255, raw_tuned_value))
                    elif data_type == "16bit":
                        raw_tuned_value = int(round(raw_tuned_value_float))
                        # Clamp 16-bit values to 0-65535 (unsigned short)
                        raw_tuned_value = max(0, min(65535, raw_tuned_value))
                    else:
                        logging.error(f"Unknown data_type '{data_type}' during reverse conversion for {map_name}. Setting raw value to 0.")
                        return jsonify({"error": "Internal server error: Unknown data type for saving"}), 500


            start_idx = block_offset + (i * cols + j) * byte_per_value
            end_idx = start_idx + byte_per_value

            # Check bounds for writing map data
            if end_idx > len(content):
                logging.error(f"Attempted to write map '{map_name}' out of file bounds at offset {hex(start_idx)}. File length: {len(content)}. Data for [{i},{j}] skipped.")
                continue

            if data_type == "8bit":
                content[start_idx] = raw_tuned_value
            elif data_type == "16bit":
                if endian is None:
                    logging.error(f"Endianness not specified for 16bit map '{map_name}' during save. Skipping write for [{i},{j}].")
                    continue
                try:
                    packed_bytes = struct.pack(endian, raw_tuned_value)
                    content[start_idx:end_idx] = packed_bytes
                except struct.error as se:
                    logging.error(f"Struct packing error for {map_name} at [{i},{j}]. Value: {raw_tuned_value}, Endian: {endian}. Error: {se}. Skipping write.")
                    continue

    # ======================================================================
    # !!! สำคัญมาก: LOGIC สำหรับการคำนวณและอัปเดต CHECKSUM !!!
    # ======================================================================
    # ส่วนนี้เป็นสิ่งสำคัญที่สุดที่คุณต้องเพิ่มเพื่อให้ไฟล์ที่จูนแล้ว
    # สามารถใช้งานได้จริงกับ ECU หากไม่มีการคำนวณ Checksum ที่ถูกต้อง
    # ECU จะถือว่าไฟล์เสียหายหรือไม่ถูกต้อง และจะไม่ยอมรับไฟล์นั้น
    #
    # คุณต้อง:
    # 1. ระบุ Algorithm ของ Checksum (เช่น CRC16, CRC32, Simple Sum, etc.)
    #    ที่ ECU รุ่นนี้ใช้.
    # 2. ระบุตำแหน่ง (Offset) ที่ Checksum ถูกเก็บไว้ในไฟล์.
    # 3. ระบุขอบเขต (Range) ของข้อมูลในไฟล์ .bin ที่ถูกนำไปคำนวณ Checksum.
    #
    # ตัวอย่าง (นี่คือ PSEUDOCODE คุณต้องเขียนฟังก์ชัน calculate_checksum() เอง):
    #
    # def calculate_checksum(data_bytes_segment):
    #     # Implement the specific checksum algorithm for your ECU here.
    #     # Example for a simple 16-bit sum:
    #     checksum = sum(data_bytes_segment) & 0xFFFF # Modulo 65536 for 16-bit
    #     return checksum
    #
    # # ตัวอย่างการนำไปใช้:
    # # if map_name == "torque_tps_1": # ตัวอย่าง: Checksum อาจจะเฉพาะ Map หรือเฉพาะ ECU
    # #     checksum_start_offset = 0x000000 # ต้องหาเอง
    # #     checksum_end_offset = 0x1FFFFF   # ต้องหาเอง
    # #     checksum_location_offset = 0x1FFFFC # ต้องหาเอง (เช่น 2 bytes)
    #
    # #     if checksum_start_offset < len(content) and checksum_end_offset <= len(content) and checksum_location_offset + 2 <= len(content):
    # #         data_for_checksum = content[checksum_start_offset:checksum_end_offset]
    # #         new_checksum_value = calculate_checksum(data_for_checksum)
    #
    # #         # เขียน Checksum กลับลงไปในไฟล์ (สมมติว่าเป็น 16-bit Little-endian)
    # #         content[checksum_location_offset:checksum_location_offset + 2] = struct.pack("<H", new_checksum_value)
    # #         logging.info(f"Checksum updated to {hex(new_checksum_value)} at {hex(checksum_location_offset)} for {map_name}.")
    # #     else:
    # #         logging.warning(f"Checksum calculation skipped for {map_name} due to invalid offsets/bounds.")
    # # else:
    # #     logging.info(f"No specific checksum logic defined or applied for {map_name}. File might be invalid for ECU if checksum is required.")
    # #
    # ======================================================================

    # Send the modified file back
    modified_file_stream = io.BytesIO(content)
    modified_file_stream.seek(0)

    logging.info(f"Successfully tuned and prepared file for {map_name}.")
    return send_file(
        modified_file_stream,
        mimetype='application/octet-stream',
        as_attachment=True,
        download_name=f"{map_name}_tuned_map.bin"
    )

---

**เพิ่ม Endpoint ใหม่นี้:**

```python
@app.route("/read_full_bin", methods=["POST"])
def read_full_bin():
    if 'bin' not in request.files:
        logging.error("No file uploaded for full BIN read.")
        return jsonify({"error": "No file uploaded"}), 400

    try:
        bin_file = request.files["bin"]
        content = bin_file.read() # อ่านเนื้อหาทั้งหมดของไฟล์

        # คุณสามารถเลือกที่จะส่งเป็นไบนารีโดยตรง หรือแปลงเป็น Hex String
        # การส่งเป็นไบนารีโดยตรง:
        # return send_file(
        #     io.BytesIO(content),
        #     mimetype='application/octet-stream',
        #     as_attachment=False, # ไม่ส่งเป็น attachment เพื่อให้ฟรอนต์เอนด์อ่านตรงๆ
        #     download_name="full_bin_data.bin" # ชื่อไฟล์ถ้าเบราว์เซอร์ดาวน์โหลด
        # )

        # หรือแปลงเป็น Hex String เพื่อการแสดงผลที่ง่ายขึ้นบนเว็บ (อาจมีขนาดใหญ่มาก)
        hex_data = content.hex()
        logging.info(f"Successfully read full BIN file. Size: {len(content)} bytes.")
        return jsonify({"data": hex_data, "length": len(content)}), 200

    except Exception as e:
        logging.exception(f"Unhandled error during full BIN file read.")
        return jsonify({"error": f"An unexpected error occurred during full BIN file read: {str(e)}. Please check log for details."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=10000, debug=True)

