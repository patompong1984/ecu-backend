from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os

# สร้าง Flask App
app = Flask(__name__)
# เปิดใช้งาน CORS (Cross-Origin Resource Sharing) เพื่อให้ Frontend สามารถเรียกใช้ Backend ได้
CORS(app)
# ตั้งค่าระบบ Log ให้แสดงข้อความ INFO ขึ้นไป
logging.basicConfig(level=logging.INFO)

# --- การตั้งค่า Conversion Factors และ Offsets สำหรับแต่ละ Map ---
# ค่าเหล่านี้ใช้ในการแปลงค่าดิบ (raw byte) ที่อ่านจากไฟล์ .bin ให้เป็นค่าจริงที่มีหน่วย
# **สำคัญ:** ค่าเหล่านี้เป็นค่าประมาณการณ์จากข้อมูลทั่วไปของ ECU ที่คล้ายกัน
# **คุณอาจต้องปรับค่า 'factor' และ 'offset' ให้ตรงกับ ECU ของ Isuzu D-Max 1.9L ของคุณจริงๆ
#    โดยการวิเคราะห์จากโปรแกรมจูนกล่อง ECU มืออาชีพ (เช่น WinOLS, Dimsport Race EVO)**
MAP_CONVERSION_SETTINGS = {
    # 'factor': ตัวคูณที่ใช้กับค่าดิบ (raw byte)
    # 'offset': ค่าชดเชยที่บวกเพิ่มหลังจากคูณด้วย factor
    
    # Fuel Map: ปริมาณน้ำมัน (มิลลิกรัม/จังหวะ)
    # มักใช้ factor น้อยๆ เช่น 0.01 หรือ 0.0123
    "fuel": {"factor": 0.01, "offset": 0}, 
    
    # Torque Limiter: จำกัดแรงบิด (นิวตันเมตร)
    # มักใช้ factor เช่น 0.5 หรือ 0.01
    "torque_limiter": {"factor": 0.5, "offset": 0}, 
    
    # Drivers Wish: แรงบิดตามที่ผู้ขับต้องการ (นิวตันเมตร)
    "drivers_wish": {"factor": 0.5, "offset": 0}, 
    
    # Fuel Quantity: ปริมาณน้ำมันจริงที่ฉีด (มิลลิเมตรกำลังสาม/จังหวะ)
    # อาจมี factor คล้าย Fuel Map
    "fuel_quantity": {"factor": 0.01, "offset": 0}, 
    
    # Injection Timing: จังหวะการฉีด (องศา BTDC)
    # มักมี factor และ offset ที่ละเอียด เช่น 0.0234375, -10.0
    "injection_timing": {"factor": 0.0234375, "offset": -10.0}, 
    
    # Boost Pressure: แรงดันอากาศจากเทอร์โบ (มิลลิบาร์)
    # มักมี offset ที่เป็นค่า Barometric Pressure (ประมาณ 800-1000 mbar)
    "boost_pressure": {"factor": 0.015625, "offset": 800}, 
    
    # Rail Pressure: แรงดันน้ำมันในราง Common Rail (บาร์)
    # สำหรับ 8-bit (0-255) map ค่า factor 9.765625 เป็นที่นิยม
    # 255 * 9.765625 = 2490.28 บาร์ (ค่าสูงสุดที่เหมาะสม)
    "rail_pressure": {"factor": 9.765625, "offset": 0}, 
    
    # Turbo Duty: ระดับสั่งงาน Turbo Actuator (% Duty Cycle)
    # มักใช้ factor เช่น 0.390625
    "turbo_duty": {"factor": 0.390625, "offset": 0}, 
    
    # Smoke Limiter: จำกัดควันดำ (มิลลิกรัม/จังหวะ)
    # คล้าย Fuel Map
    "smoke_limiter": {"factor": 0.01, "offset": 0}, 
    
    # IAT & ECT Correction: การปรับแก้ตามอุณหภูมิไอดีและน้ำหล่อเย็น
    # อาจมี factor 1.0 หรืออื่นๆ ขึ้นอยู่กับหน่วยการปรับแก้
    "iat_ect_correction": {"factor": 1.0, "offset": 0}, 
    
    # EGR: ควบคุมระบบ EGR (% เปิด)
    "egr": {"factor": 0.390625, "offset": 0}, 
    
    # Throttle: ลิ้นปีกผีเสื้อ (% เปิด)
    "throttle": {"factor": 0.390625, "offset": 0}, 
    
    # DTC Off: ตารางปิดไฟแจ้งเตือน DTC (มักใช้ factor 1.0 หรือไม่มีการแปลงค่า)
    "dtc_off": {"factor": 1.0, "offset": 0} 
}

# --- ตำแหน่ง Offset ของ Map Block และ แกน X/Y ในไฟล์ .bin ---
# ค่า Offset เหล่านี้คือตำแหน่งเริ่มต้นของข้อมูลในไฟล์ไบนารี (ระบุเป็นเลขฐาน 16)
# **คุณต้องแน่ใจว่า Offset เหล่านี้ถูกต้องสำหรับไฟล์ .bin ที่คุณใช้อยู่**
# **หากไฟล์ .bin มาจาก ECU ที่แตกต่างกัน Offset เหล่านี้อาจไม่ตรงกัน**
MAP_OFFSETS = {
    "fuel": {
        "block": 0x1D8710, # ตำแหน่งเริ่มต้นของ Map (16x16 = 256 bytes)
        "x_axis": 0x1D8610, # ตำแหน่งเริ่มต้นของแกน X (16 bytes)
        "y_axis": 0x1D8600  # ตำแหน่งเริ่มต้นของแกน Y (16 bytes)
    },
    "torque_limiter": {
        "block": 0x1DA000,
        "x_axis": 0x1D9F10,
        "y_axis": 0x1D9F00
    },
    "drivers_wish": {
        "block": 0x1DB000,
        "x_axis": 0x1DAF10,
        "y_axis": 0x1DAF00
    },
    "fuel_quantity": {
        "block": 0x1DC000,
        "x_axis": 0x1DBF10,
        "y_axis": 0x1DBF00
    },
    "injection_timing": {
        "block": 0x1DD000,
        "x_axis": 0x1DCF10,
        "y_axis": 0x1DCF00
    },
    "boost_pressure": {
        "block": 0x1DE000,
        "x_axis": 0x1DDF10,
        "y_axis": 0x1DDF00
    },
    "rail_pressure": {
        "block": 0x1DF000,
        "x_axis": 0x1DEF10,
        "y_axis": 0x1DEF00
    },
    "turbo_duty": {
        "block": 0x1E0000,
        "x_axis": 0x1DFF10,
        "y_axis": 0x1DFF00
    },
    "smoke_limiter": {
        "block": 0x1E1000,
        "x_axis": 0x1E0F10,
        "y_axis": 0x1E0F00
    },
    "iat_ect_correction": {
        "block": 0x1E2000,
        "x_axis": 0x1E1F10,
        "y_axis": 0x1E1F00
    },
    "egr": {
        "block": 0x1E3000,
        "x_axis": 0x1E2F10,
        "y_axis": 0x1E2F00
    },
    "throttle": {
        "block": 0x1E4000,
        "x_axis": 0x1E3F10,
        "y_axis": 0x1E3F00
    },
    "dtc_off": {
        "block": 0x1F0000,
        "x_axis": 0x1EFF10,
        "y_axis": 0x1EFF00
    }
}

# ฟังก์ชันสำหรับแปลงค่าแกน X หรือ Y
def parse_axis(raw_bytes, scale):
    """
    แปลงค่าดิบ (bytes) ของแกน X หรือ Y ให้เป็นค่าจริง
    :param raw_bytes: ข้อมูล byte ดิบจากไฟล์ .bin (16 bytes)
    :param scale: ตัวคูณสำหรับแปลงค่าดิบ
    :return: ลิสต์ของค่าแกนที่แปลงแล้ว
    """
    # แกน X (โหลด) มักจะใช้ scale 1.0 (ถ้าค่าดิบคือ %) หรือ 0.1 หากเป็นค่าอื่นๆ
    # แกน Y (รอบเครื่อง) มักจะใช้ scale 20.0 สำหรับ RPM (ค่าดิบ 1 = 20 RPM)
    return [round(b * scale) for b in raw_bytes]

# Endpoint สำหรับวิเคราะห์ไฟล์ .bin
@app.route("/analyze", methods=["POST"])
def analyze_bin():
    """
    รับไฟล์ .bin และประเภทของ Map จาก Frontend
    อ่านข้อมูลจากไฟล์ตาม offset ที่กำหนด และแปลงเป็น 2D Map
    ส่งผลลัพธ์กลับในรูปแบบ JSON
    """
    bin_file = request.files.get('bin') # รับไฟล์จาก Form data
    map_type = (request.form.get('type') or 'fuel').lower() # รับประเภท Map และแปลงเป็นตัวพิมพ์เล็ก

    # ตรวจสอบว่ามีไฟล์และ Map Type ที่รองรับหรือไม่
    if not bin_file or map_type not in MAP_OFFSETS:
        app.logger.warning(f"Invalid request: bin_file={bool(bin_file)}, map_type={map_type}")
        return jsonify({ "error": "Missing file or unsupported map type" }), 400

    content = bin_file.read() # อ่านเนื้อหาทั้งหมดของไฟล์เป็น bytes
    offsets = MAP_OFFSETS[map_type] # ดึง offset สำหรับ Map ที่เลือก

    # ดึงค่า factor และ offset สำหรับ Map ที่เลือกจาก MAP_CONVERSION_SETTINGS
    # หากไม่พบ map_type ใน settings (ซึ่งไม่ควรเกิดขึ้นถ้า MAP_OFFSETS ถูกต้อง)
    # จะใช้ค่าเริ่มต้น factor=1.0, offset=0
    conversion_settings = MAP_CONVERSION_SETTINGS.get(map_type, {"factor": 1.0, "offset": 0})
    factor = conversion_settings["factor"]
    offset_value = conversion_settings["offset"]

    try:
        # ตรวจสอบขนาดไฟล์ขั้นต่ำที่จำเป็นต้องมี เพื่อป้องกัน Index out of range
        # block_end = offsets["block"] + 256
        # x_axis_end = offsets["x_axis"] + 16
        # y_axis_end = offsets["y_axis"] + 16
        # max_required_offset = max(block_end, x_axis_end, y_axis_end)

        # เนื่องจาก .bin file มักจะมีขนาดที่แน่นอน (เช่น 2MB) การเช็คเฉพาะ offset สูงสุด
        # ที่จะอ่านได้ก็เพียงพอแล้ว
        max_offset_needed = max(
            offsets["block"] + 256,
            offsets["x_axis"] + 16,
            offsets["y_axis"] + 16
        )

        if len(content) < max_offset_needed:
            app.logger.error(f"File too small for expected offset. Map Type: {map_type}, Required: {max_offset_needed} bytes, Got: {len(content)} bytes.")
            return jsonify({ 
                "error": f"File too small for expected data. Minimum size for '{map_type}' map is around {max_offset_needed} bytes, but the uploaded file is only {len(content)} bytes. Please check if this is the correct .BIN file for this ECU." 
            }), 400

        # อ่านข้อมูลดิบของแกน X และ Y (แต่ละแกนมี 16 bytes)
        x_raw = content[offsets["x_axis"] : offsets["x_axis"] + 16]
        y_raw = content[offsets["y_axis"] : offsets["y_axis"] + 16]

        # แปลงค่าดิบของแกน X และ Y เป็นค่าจริง
        # **คุณอาจต้องปรับ scale ของแกน X และ Y ให้ถูกต้องกับไฟล์ .bin ของคุณ**
        x_axis = parse_axis(x_raw, scale=1.0)     # ตัวอย่าง: สำหรับ % Load
        y_axis = parse_axis(y_raw, scale=20.0)    # ตัวอย่าง: สำหรับ RPM

        # อ่านข้อมูลดิบของ Map block (16x16 = 256 bytes)
        block = content[offsets["block"] : offsets["block"] + 256]
        
        # แปลงค่าดิบใน Map block เป็นค่า 2D Map (16x16)
        # ใช้ factor และ offset_value ที่ดึงมาสำหรับ Map ประเภทนั้นๆ
        map_2d = []
        for i in range(16): # 16 แถว
            row = []
            for j in range(16): # 16 คอลัมน์
                # ดึงค่า byte ดิบจาก block
                raw_byte_value = block[i * 16 + j]
                # แปลงค่าดิบเป็นค่าจริงโดยใช้ factor และ offset ที่กำหนด
                actual_value = (raw_byte_value * factor) + offset_value
                # ปัดเศษให้เหลือทศนิยม 2 ตำแหน่ง
                row.append(round(actual_value, 2))
            map_2d.append(row)

        app.logger.info(f"Successfully analyzed '{map_type}' map from offset {hex(offsets['block'])}. Map data: {map_2d[:2]}...") # Log 2 แถวแรก
        
        return jsonify({
            "type": map_type.capitalize(),
            "offset": hex(offsets["block"]), # ส่ง offset กลับไปด้วยเพื่อการอ้างอิง
            "x_axis": x_axis,
            "y_axis": y_axis,
            "map": map_2d
        })
    
    except Exception as e:
        # ดักจับข้อผิดพลาดระหว่างการประมวลผล
        app.logger.error(f"Processing error for map type '{map_type}': {str(e)}", exc_info=True)
        return jsonify({ "error": f"Processing error: {str(e)}. Please check the file format or selected map type." }), 500

# รัน Flask App
from flask import Flask, request, jsonify
from flask_cors import CORS
import logging
import os
from werkzeug.middleware.proxy_fix import ProxyFix

# สร้าง Flask App
app = Flask(__name__)
# เปิดใช้งาน CORS (Cross-Origin Resource Sharing) เพื่อให้ Frontend สามารถเรียกใช้ Backend ได้
CORS(app)
# ตั้งค่าระบบ Log ให้แสดงข้อความ INFO ขึ้นไป
logging.basicConfig(level=logging.INFO)
# จำกัดขนาดไฟล์อัปโหลดสูงสุด 4MB
app.config['MAX_CONTENT_LENGTH'] = 4 * 1024 * 1024
# ตั้งค่าให้ Flask รองรับ Reverse Proxy
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# --- การตั้งค่า Conversion Factors และ Offsets สำหรับแต่ละ Map ---
# ค่าเหล่านี้ใช้ในการแปลงค่าดิบ (raw byte) ที่อ่านจากไฟล์ .bin ให้เป็นค่าจริงที่มีหน่วย
MAP_CONVERSION_SETTINGS = {
    "fuel": {
        "factor": 0.01, 
        "offset": 0,
        "x_scale": 1.0,      # % Load
        "y_scale": 20.0       # RPM (1 unit = 20 RPM)
    },
    "torque_limiter": {
        "factor": 0.5,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "drivers_wish": {
        "factor": 0.5,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "fuel_quantity": {
        "factor": 0.01,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "injection_timing": {
        "factor": 0.0234375,
        "offset": -10.0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "boost_pressure": {
        "factor": 0.015625,
        "offset": 800,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "rail_pressure": {
        "factor": 9.765625,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "turbo_duty": {
        "factor": 0.390625,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "smoke_limiter": {
        "factor": 0.01,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "iat_ect_correction": {
        "factor": 1.0,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "egr": {
        "factor": 0.390625,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "throttle": {
        "factor": 0.390625,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 20.0
    },
    "dtc_off": {
        "factor": 1.0,
        "offset": 0,
        "x_scale": 1.0,
        "y_scale": 1.0
    }
}

# --- ตำแหน่ง Offset ของ Map Block และ แกน X/Y ในไฟล์ .bin ---
MAP_OFFSETS = {
    "fuel": {
        "block": 0x1D8710,
        "x_axis": 0x1D8610,
        "y_axis": 0x1D8600
    },
    "torque_limiter": {
        "block": 0x1DA000,
        "x_axis": 0x1D9F10,
        "y_axis": 0x1D9F00
    },
    "drivers_wish": {
        "block": 0x1DB000,
        "x_axis": 0x1DAF10,
        "y_axis": 0x1DAF00
    },
    "fuel_quantity": {
        "block": 0x1DC000,
        "x_axis": 0x1DBF10,
        "y_axis": 0x1DBF00
    },
    "injection_timing": {
        "block": 0x1DD000,
        "x_axis": 0x1DCF10,
        "y_axis": 0x1DCF00
    },
    "boost_pressure": {
        "block": 0x1DE000,
        "x_axis": 0x1DDF10,
        "y_axis": 0x1DDF00
    },
    "rail_pressure": {
        "block": 0x1DF000,
        "x_axis": 0x1DEF10,
        "y_axis": 0x1DEF00
    },
    "turbo_duty": {
        "block": 0x1E0000,
        "x_axis": 0x1DFF10,
        "y_axis": 0x1DFF00
    },
    "smoke_limiter": {
        "block": 0x1E1000,
        "x_axis": 0x1E0F10,
        "y_axis": 0x1E0F00
    },
    "iat_ect_correction": {
        "block": 0x1E2000,
        "x_axis": 0x1E1F10,
        "y_axis": 0x1E1F00
    },
    "egr": {
        "block": 0x1E3000,
        "x_axis": 0x1E2F10,
        "y_axis": 0x1E2F00
    },
    "throttle": {
        "block": 0x1E4000,
        "x_axis": 0x1E3F10,
        "y_axis": 0x1E3F00
    },
    "dtc_off": {
        "block": 0x1F0000,
        "x_axis": 0x1EFF10,
        "y_axis": 0x1EFF00
    }
}

# ฟังก์ชันสำหรับแปลงค่าแกน X หรือ Y
def parse_axis(raw_bytes, scale):
    """
    แปลงค่าดิบ (bytes) ของแกน X หรือ Y ให้เป็นค่าจริง
    :param raw_bytes: ข้อมูล byte ดิบจากไฟล์ .bin (16 bytes)
    :param scale: ตัวคูณสำหรับแปลงค่าดิบ
    :return: ลิสต์ของค่าแกนที่แปลงแล้ว
    """
    return [round(b * scale) for b in raw_bytes]

# Health Check Endpoint
@app.route("/health", methods=["GET"])
def health_check():
    return jsonify({"status": "healthy", "service": "ECU Map Analyzer"}), 200

# Error Handler
@app.errorhandler(400)
def bad_request(e):
    app.logger.warning(f"Bad request: {str(e)}")
    return jsonify({"error": "Bad request"}), 400

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(413)
def request_too_large(e):
    app.logger.warning("Uploaded file exceeds size limit")
    return jsonify({"error": "File too large. Maximum size is 4MB"}), 413

@app.errorhandler(500)
def internal_error(e):
    app.logger.error(f"Internal server error: {str(e)}")
    return jsonify({"error": "Internal server error"}), 500

# Endpoint สำหรับวิเคราะห์ไฟล์ .bin
@app.route("/analyze", methods=["POST"])
def analyze_bin():
    """
    รับไฟล์ .bin และประเภทของ Map จาก Frontend
    อ่านข้อมูลจากไฟล์ตาม offset ที่กำหนด และแปลงเป็น 2D Map
    ส่งผลลัพธ์กลับในรูปแบบ JSON
    """
    # ตรวจสอบการมีอยู่ของไฟล์
    if 'bin' not in request.files:
        app.logger.warning("No file part in request")
        return jsonify({"error": "No file uploaded"}), 400
        
    bin_file = request.files['bin']
    map_type = (request.form.get('type') or 'fuel').lower()

    # ตรวจสอบชื่อไฟล์
    if bin_file.filename == '':
        app.logger.warning("No selected file")
        return jsonify({"error": "No selected file"}), 400

    # ตรวจสอบ Map Type
    if map_type not in MAP_OFFSETS:
        app.logger.warning(f"Unsupported map type: {map_type}")
        return jsonify({"error": f"Unsupported map type: {map_type}"}), 400

    try:
        content = bin_file.read()
        offsets = MAP_OFFSETS[map_type]
        conversion_settings = MAP_CONVERSION_SETTINGS.get(map_type, {
            "factor": 1.0,
            "offset": 0,
            "x_scale": 1.0,
            "y_scale": 1.0
        })

        # ตรวจสอบขนาดไฟล์
        max_offset_needed = max(
            offsets["block"] + 256,
            offsets["x_axis"] + 16,
            offsets["y_axis"] + 16
        )

        if len(content) < max_offset_needed:
            error_msg = (
                f"File too small for map '{map_type}'. "
                f"Required: {max_offset_needed} bytes, Got: {len(content)} bytes. "
                "Please ensure this is a valid ECU BIN file."
            )
            app.logger.error(error_msg)
            return jsonify({"error": error_msg}), 400

        # อ่านและแปลงแกน X/Y
        x_raw = content[offsets["x_axis"]:offsets["x_axis"] + 16]
        y_raw = content[offsets["y_axis"]:offsets["y_axis"] + 16]
        x_axis = parse_axis(x_raw, conversion_settings["x_scale"])
        y_axis = parse_axis(y_raw, conversion_settings["y_scale"])

        # อ่านและแปลง Map data
        block = content[offsets["block"]:offsets["block"] + 256]
        factor = conversion_settings["factor"]
        offset_value = conversion_settings["offset"]
        
        map_2d = []
        for i in range(16):
            row = []
            for j in range(16):
                raw_value = block[i * 16 + j]
                actual_value = (raw_value * factor) + offset_value
                row.append(round(actual_value, 2))
            map_2d.append(row)

        app.logger.info(f"Successfully analyzed '{map_type}' map. Dimensions: 16x16")
        
        return jsonify({
            "type": map_type,
            "offset": hex(offsets["block"]),
            "x_axis": x_axis,
            "y_axis": y_axis,
            "map": map_2d
        })
    
    except Exception as e:
        app.logger.exception(f"Error processing {map_type} map")
        return jsonify({
            "error": f"Processing error: {str(e)}",
            "map_type": map_type
        }), 500

# รัน Flask App
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == "true"
    
    # สำหรับ Production ใช้ Waitress
    if not debug_mode:
        try:
            from waitress import serve
            app.logger.info(f"Starting PRODUCTION server on port {port}")
            serve(app, host="0.0.0.0", port=port)
        except ImportError:
            app.logger.warning("Waitress not found. Using built-in server")
            app.run(host="0.0.0.0", port=port, debug=False)
    else:
        app.logger.info(f"Starting DEVELOPMENT server on port {port}")
        app.run(host="0.0.0.0", port=port, debug=True)
