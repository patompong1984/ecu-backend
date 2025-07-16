from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

# 🔧 ตำแหน่ง offset ของแต่ละประเภทแผนที่
MAP_OFFSETS = {
    "fuel":     0x1D8710,
    "ignition": 0x1F2000,
    "boost":    0x1C4000
}

@app.route("/analyze", methods=["POST"])
def analyze_bin():
    bin_file = request.files.get('bin')
    map_type = request.form.get('type', 'fuel').lower()

    # ตรวจสอบว่าไฟล์และประเภทถูกส่งมาครบ
    if not bin_file:
        print("[ERROR] ไม่พบไฟล์ 'bin'")
        return jsonify({ "error": "Missing file 'bin'" }), 400

    if map_type not in MAP_OFFSETS:
        print(f"[ERROR] ไม่รองรับประเภท map: '{map_type}'")
        return jsonify({ "error": f"Unsupported map type '{map_type}'" }), 400

    # อ่านไฟล์และเตรียมแปลงข้อมูล
    content = bin_file.read()
    offset = MAP_OFFSETS[map_type]
    print(f"[INFO] วิเคราะห์ '{map_type}' ที่ offset {hex(offset)} ขนาดไฟล์: {len(content)} bytes")

    if len(content) < offset + 256:
        print("[ERROR] ไฟล์เล็กเกินกว่าที่จะอ่าน block ที่ต้องการ")
        return jsonify({ "error": "File too small for expected offset" }), 400

    # ดึงข้อมูล map และคูณ scaling factor
    block = content[offset : offset + 256]
    map_2d = []

    for i in range(16):
        row = block[i*16 : (i+1)*16]
        scaled = [round(b * 0.05, 2) for b in row]  # หน่วยอาจเป็น mg/stroke
        map_2d.append(scaled)

    print(f"[INFO] ส่งผลลัพธ์ map ประเภท '{map_type}' กลับ client")

    return jsonify({
        "type": map_type.capitalize(),
        "offset": hex(offset),
        "map": map_2d
    })

if __name__ == "__main__":
    app.run()
